"""
AndroidIOTracer - orchestrates ftrace event collection and periodic snapshots.

Ties together:
  * :class:`FtraceManager`  - enables block (and optional fs) tracepoints and
    streams ``trace_pipe`` lines.
  * :mod:`parsers`          - turns those lines into ``ds``/``fs`` schema rows
    (the :class:`BlockPairer` recovers per-request device latency).
  * :class:`WriteManager`   - buffers rows, rotates/compresses CSVs, writes a
    manifest.
  * snappers                - system spec (once), process + filesystem snapshots.

Collection runs until interrupted (Ctrl-C / SIGTERM), at which point all buffers
are flushed, the ftrace state is restored, and ``manifest.json`` is written.
"""

import signal
import threading
import time

from .FtraceManager import FtraceManager, BLOCK_EVENTS, FS_EVENTS
from .WriterManager import WriteManager
from . import parsers
from ..utility.utils import format_csv_row, logger, mono_ns_to_datetime_str
from .snappers.SystemSnapper import SystemSnapper
from .snappers.ProcessSnapper import ProcessSnapper
from .snappers.FilesystemSnapper import FilesystemSnapper


class AndroidIOTracer:
    def __init__(self, output_dir, anonymous=False, trace_fs=False,
                 fs_snapshot=False, tracefs_path=None,
                 process_interval_s=300):
        self.output_dir = output_dir
        self.anonymous = anonymous
        self.trace_fs = trace_fs
        self.fs_snapshot = fs_snapshot
        self.process_interval_s = process_interval_s

        self.wm = WriteManager(output_dir)
        self.ftrace = FtraceManager(tracefs_path)
        self.block_pairer = parsers.BlockPairer()
        self._stop = threading.Event()
        self._offset = self.wm.mono_to_real_offset_ns

        self.events_enabled = []
        self.lines_seen = 0
        self.ds_rows = 0
        self.fs_rows = 0

    # -- per-line handling ------------------------------------------------ #

    def _handle_line(self, line: str):
        self.lines_seen += 1
        common = parsers.parse_common(line)
        if common is None:
            return
        event = common["event"]
        if event == "block_rq_issue":
            self.block_pairer.on_issue(common)
        elif event == "block_rq_complete":
            row = self.block_pairer.on_complete(common)
            if row is not None:
                self._emit_ds(row)

    def _emit_ds(self, r: dict):
        ts = mono_ns_to_datetime_str(r["mono_ns"], self._offset)
        self.wm.append("ds", format_csv_row(
            ts, r["operation"], r["pid"], r["tid"], r["command"], r["sector"],
            r["size"], r["latency_ms"], r["device"], r["flags"], r["cpu_id"],
            r["ppid"], r["queue_latency_ms"], r["command_flags"],
            r["operation_code"], r["request_id"], r["mono_ns"],
        ))
        self.ds_rows += 1

    # -- lifecycle -------------------------------------------------------- #

    def _install_signal_handlers(self):
        def handler(signum, _frame):
            logger("info", f"Received signal {signum}; shutting down...")
            self.stop()
        try:
            signal.signal(signal.SIGINT, handler)
            signal.signal(signal.SIGTERM, handler)
        except ValueError:
            # Not on the main thread (e.g. under tests) - skip.
            pass

    def trace(self):
        if not self.ftrace.available:
            logger("error",
                   "tracefs not found / not accessible. The block-I/O collector "
                   "needs ftrace at /sys/kernel/tracing and root privileges "
                   "(run via 'adb shell su' on a rooted/userdebug device).")
            logger("info", "Snapshots (process/filesystem/system) can still run; "
                           "continuing without ftrace event streams.")

        self._install_signal_handlers()

        # 1) One-shot system spec.
        SystemSnapper(self.wm).capture_spec_snapshot()

        # 2) Periodic process snapshots in the background.
        self.proc_snapper = ProcessSnapper(
            self.wm, anonymous=self.anonymous, interval_s=self.process_interval_s)
        self.proc_snapper.run()

        # 3) Optional one-shot filesystem inventory.
        if self.fs_snapshot:
            threading.Thread(
                target=lambda: FilesystemSnapper(
                    self.wm, anonymous=self.anonymous).take_snapshot(),
                daemon=True,
            ).start()

        # 4) ftrace event streaming (blocks until stop).
        if self.ftrace.available:
            events = list(BLOCK_EVENTS) + (list(FS_EVENTS) if self.trace_fs else [])
            self.events_enabled = self.ftrace.setup(events)
            logger("info", "Tracing started. Press Ctrl-C to stop and flush.")
            stream_thread = threading.Thread(
                target=self.ftrace.stream, args=(self._handle_line,), daemon=True)
            stream_thread.start()
            # Periodic flush of event buffers so long runs land data incrementally.
            while not self._stop.is_set():
                self._stop.wait(timeout=30)
                self.wm.flush("ds")
                self.wm.flush("fs")
        else:
            logger("info", "Running in snapshot-only mode. Press Ctrl-C to stop.")
            while not self._stop.is_set():
                self._stop.wait(timeout=1)

        self._shutdown()

    def stop(self):
        self._stop.set()
        self.ftrace.stop()

    def _shutdown(self):
        logger("info", "Flushing buffers and writing manifest...")
        if hasattr(self, "proc_snapper"):
            self.proc_snapper.stop()
        if self.ftrace.available:
            self.ftrace.teardown()
        self.wm.flush_all()
        manifest_path = self.wm.write_manifest(extra={
            "events_enabled": self.events_enabled,
            "lines_seen": self.lines_seen,
            "block_inflight_unmatched": self.block_pairer.inflight_count(),
        })
        logger("info", f"Done. Output in {self.output_dir} (manifest: {manifest_path})")
        logger("info", f"ds rows: {self.ds_rows}, lines parsed: {self.lines_seen}")

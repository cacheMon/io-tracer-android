"""
FtraceManager - configure the kernel ftrace ring buffer and stream events.

Android (like any modern Linux kernel) exposes ftrace under tracefs, normally
mounted at ``/sys/kernel/tracing`` (older devices: ``/sys/kernel/debug/tracing``).
This manager enables a chosen set of tracepoint events, switches the trace clock
to ``mono`` (CLOCK_MONOTONIC) so timestamps line up with the snapshot streams'
``mono_ns`` column, then yields raw lines from ``trace_pipe``.

It needs root (or the right SELinux/`CAP_SYS_ADMIN` context) on the device, which
is why it is typically run via ``adb shell su`` or on a userdebug/rooted build.
All enable/disable is restored on exit so the device's tracing state is left as
it was found.
"""

import os
import threading

from ..utility.utils import logger


# Candidate tracefs mount points, most-preferred first.
_TRACEFS_CANDIDATES = (
    "/sys/kernel/tracing",
    "/sys/kernel/debug/tracing",
)

# Tracepoint events we know how to parse, grouped by logical stream.
BLOCK_EVENTS = ("block/block_rq_issue", "block/block_rq_complete")
# Best-effort filesystem read/write events (availability is kernel-dependent).
FS_EVENTS = (
    "f2fs/f2fs_dataread_start",
    "f2fs/f2fs_datawrite_start",
    "ext4/ext4_es_lookup_extent_exit",
)


class FtraceManager:
    """Owns the tracefs configuration for one tracing session."""

    def __init__(self, tracefs: str | None = None):
        self.tracefs = tracefs or self._find_tracefs()
        self._enabled_events: list[str] = []
        self._orig_clock: str | None = None
        self._stop = threading.Event()

    # -- discovery -------------------------------------------------------- #

    @staticmethod
    def _find_tracefs() -> str | None:
        for path in _TRACEFS_CANDIDATES:
            if os.path.isdir(path) and os.path.exists(os.path.join(path, "trace_pipe")):
                return path
        return None

    @property
    def available(self) -> bool:
        # Valid only if the (auto-detected or user-supplied) path actually exposes
        # a readable trace_pipe — an explicit --tracefs override is validated too.
        return bool(self.tracefs) and os.path.exists(os.path.join(self.tracefs, "trace_pipe"))

    def _path(self, *parts) -> str:
        return os.path.join(self.tracefs, *parts)

    def _write(self, rel: str, value: str) -> bool:
        """Write ``value`` to a tracefs control file; return success."""
        try:
            with open(self._path(rel), "w") as f:
                f.write(value)
            return True
        except OSError as e:
            logger("warning", f"ftrace: could not write '{value}' to {rel}: {e}")
            return False

    def _read(self, rel: str) -> str | None:
        try:
            with open(self._path(rel)) as f:
                return f.read()
        except OSError:
            return None

    def event_available(self, event: str) -> bool:
        return os.path.isdir(self._path("events", event))

    # -- lifecycle -------------------------------------------------------- #

    def setup(self, events) -> list[str]:
        """Enable the available subset of ``events`` and set ``trace_clock=mono``.

        Returns the list of events that were actually enabled.
        """
        if not self.available:
            raise RuntimeError(
                "tracefs not found. ftrace must be mounted at /sys/kernel/tracing "
                "(or /sys/kernel/debug/tracing) and accessible to root."
            )

        # Record and switch the trace clock so event timestamps are CLOCK_MONOTONIC.
        clock_line = self._read("trace_clock") or ""
        for tok in clock_line.split():
            if tok.startswith("[") and tok.endswith("]"):
                self._orig_clock = tok.strip("[]")
        self._write("trace_clock", "mono")

        # Make sure tracing is on and the buffer starts clean.
        self._write("tracing_on", "0")
        self._write("trace", "")  # truncate existing buffer

        for ev in events:
            if not self.event_available(ev):
                logger("info", f"ftrace: event {ev} not present on this kernel, skipping")
                continue
            if self._write(os.path.join("events", ev, "enable"), "1"):
                self._enabled_events.append(ev)

        if self._enabled_events:
            self._write("tracing_on", "1")
            logger("info", f"ftrace: enabled {len(self._enabled_events)} event(s): "
                           f"{', '.join(self._enabled_events)}")
        else:
            logger("warning", "ftrace: no requested events were available to enable")
        return list(self._enabled_events)

    def stream(self, on_line, poll_block_size: int = 1):
        """Read ``trace_pipe`` line by line, calling ``on_line(str)`` for each.

        Blocks until :meth:`stop` is called (or the pipe closes). ``trace_pipe``
        is a blocking read that drains as it is consumed, so it will not busy-spin.
        """
        pipe_path = self._path("trace_pipe")
        try:
            # Line-buffered text read; trace_pipe blocks when the buffer is empty.
            with open(pipe_path, "r", buffering=1, errors="replace") as pipe:
                while not self._stop.is_set():
                    line = pipe.readline()
                    if not line:
                        break
                    on_line(line.rstrip("\n"))
        except OSError as e:
            if not self._stop.is_set():
                logger("error", f"ftrace: error reading trace_pipe: {e}")

    def stop(self):
        self._stop.set()

    def teardown(self):
        """Disable everything we enabled and restore the original trace clock."""
        for ev in self._enabled_events:
            self._write(os.path.join("events", ev, "enable"), "0")
        self._enabled_events.clear()
        self._write("tracing_on", "0")
        if self._orig_clock:
            self._write("trace_clock", self._orig_clock)

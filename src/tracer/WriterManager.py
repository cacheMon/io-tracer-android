"""
WriteManager - buffer trace rows, rotate/compress CSV files, emit a manifest.

A pared-down, dependency-free analogue of the Linux tracer's WriteManager. It
keeps one buffer per stream, flushes to a timestamped CSV when the buffer fills
(or on demand), compresses finished files to ``.csv.zst`` (when ``zstandard`` is
installed), and writes a self-describing ``manifest.json`` derived from
``schema.py`` at session end.

On-disk layout mirrors the Linux tracer::

    {output_dir}/
      manifest.json
      ds/ds_{YYYYMMDD_HHMMSS_mmm}_{seq}.csv.zst
      fs/fs_{...}.csv.zst
      process/process_{...}.csv.zst
      filesystem_snapshot/filesystem_snapshot_{...}.csv.zst
      system_spec/*.json
"""

import json
import os
import threading
import time
from collections import deque
from datetime import datetime

from . import schema
from ..utility.utils import capture_machine_id, compress_log, logger, mono_to_real_offset_ns


# Continuous event streams that rotate on a buffer-count threshold.
_EVENT_STREAMS = ("ds", "fs")
# Snapshot streams written as whole units (one snapshot -> one file).
_SNAPSHOT_STREAMS = ("process", "filesystem_snapshot")
_ALL_STREAMS = _EVENT_STREAMS + _SNAPSHOT_STREAMS


class WriteManager:
    def __init__(self, output_dir: str, flush_threshold: int = 80000):
        self.output_dir = output_dir
        self.flush_threshold = flush_threshold
        self.machine_id = capture_machine_id().upper()
        self.mono_to_real_offset_ns = mono_to_real_offset_ns()
        self.session_start = datetime.now()

        self._buffers = {k: deque() for k in _ALL_STREAMS}
        self._locks = {k: threading.Lock() for k in _ALL_STREAMS}
        self._seq = {k: 0 for k in _ALL_STREAMS}
        self.rows_written = {k: 0 for k in _ALL_STREAMS}
        self.files_written = {k: 0 for k in _ALL_STREAMS}

        for key in schema.STREAMS:
            os.makedirs(os.path.join(output_dir, schema.STREAMS[key]["subdir"]), exist_ok=True)
        os.makedirs(os.path.join(output_dir, "system_spec"), exist_ok=True)

    # -- appending -------------------------------------------------------- #

    def append(self, stream: str, row: str):
        """Append one CSV row (without trailing newline) to ``stream``'s buffer."""
        if stream not in self._buffers:
            logger("error", f"WriteManager: unknown stream '{stream}'")
            return
        with self._locks[stream]:
            self._buffers[stream].append(row)
            full = len(self._buffers[stream]) >= self.flush_threshold
        # Auto-rotate continuous event streams; snapshots flush explicitly.
        if full and stream in _EVENT_STREAMS:
            self.flush(stream)

    # -- flushing / rotation ---------------------------------------------- #

    def _write_file(self, stream: str, rows: list[str]) -> str | None:
        """Write ``rows`` to a fresh timestamped CSV (with header). Returns path."""
        if not rows:
            return None
        s = schema.STREAMS[stream]
        self._seq[stream] += 1
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        name = f"{s['filename_prefix']}_{ts}_{self._seq[stream]:04d}.csv"
        path = os.path.join(self.output_dir, s["subdir"], name)
        with open(path, "w") as f:
            f.write(schema.header_line(stream) + "\n")
            f.write("\n".join(rows) + "\n")
        self.rows_written[stream] += len(rows)
        self.files_written[stream] += 1
        return path

    def flush(self, stream: str):
        """Drain ``stream``'s buffer to a CSV file and compress it."""
        with self._locks[stream]:
            if not self._buffers[stream]:
                return
            rows = list(self._buffers[stream])
            self._buffers[stream].clear()
        path = self._write_file(stream, rows)
        if path:
            compress_log(path)  # -> .csv.zst when zstandard is available

    def flush_all(self):
        for stream in _ALL_STREAMS:
            self.flush(stream)

    # -- system spec (direct JSON) ---------------------------------------- #

    def direct_write(self, filename: str, content: str):
        path = os.path.join(self.output_dir, "system_spec", filename)
        try:
            with open(path, "w") as f:
                f.write(content)
        except OSError as e:
            logger("error", f"Failed writing system spec {filename}: {e}")

    # -- manifest --------------------------------------------------------- #

    def write_manifest(self, extra: dict | None = None):
        """Write the self-describing ``manifest.json`` at the session root."""
        manifest = schema.schema_for_manifest()
        manifest["machine_id"] = self.machine_id
        manifest["session_start"] = self.session_start.strftime("%Y-%m-%d %H:%M:%S.%f")
        manifest["session_end"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        manifest["platform"] = "android"
        manifest["collector"] = "ftrace+proc"
        manifest["clock"] = {
            "mono_to_real_offset_ns": self.mono_to_real_offset_ns,
            "note": "wall_clock_ns = mono_ns + mono_to_real_offset_ns",
        }
        manifest["rows_written"] = dict(self.rows_written)
        manifest["files_written"] = dict(self.files_written)
        if extra:
            manifest.update(extra)
        path = os.path.join(self.output_dir, "manifest.json")
        with open(path, "w") as f:
            json.dump(manifest, f, indent=2)
        return path

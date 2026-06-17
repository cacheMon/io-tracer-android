"""
FilesystemSnapper - one-shot directory-tree inventory snapshot.

Walks a root path and records each regular file's path/size/timestamps, emitting
the ``filesystem_snapshot`` schema stream. Android has no ``st_birthtime`` so the
creation column falls back to ``st_ctime``. Paths are hashed in anonymous mode.
"""

import os
import stat as stat_mod
import time
from datetime import datetime

from ...utility.utils import anonymize_path, format_csv_row, logger


def _ts(epoch: float) -> str:
    return datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M:%S.%f")


class FilesystemSnapper:
    def __init__(self, wm, roots=None, anonymous: bool = False, max_entries: int = 500000):
        self.wm = wm
        # Default to the app/data and shared-storage roots most relevant on Android.
        self.roots = roots or ["/data", "/storage/emulated/0"]
        self.anonymous = anonymous
        self.max_entries = max_entries

    def take_snapshot(self):
        snap_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        mono_ns = time.monotonic_ns()
        count = 0
        for root in self.roots:
            if not os.path.isdir(root):
                continue
            for dirpath, _dirs, files in os.walk(root, onerror=lambda e: None):
                for fname in files:
                    if count >= self.max_entries:
                        logger("warning", f"Filesystem snapshot capped at {self.max_entries} entries")
                        self.wm.flush("filesystem_snapshot")
                        return count
                    full = os.path.join(dirpath, fname)
                    try:
                        st = os.lstat(full)
                    except OSError:
                        continue
                    if not stat_mod.S_ISREG(st.st_mode):
                        continue
                    path_out = anonymize_path(full) if self.anonymous else full
                    self.wm.append("filesystem_snapshot", format_csv_row(
                        snap_ts, path_out, st.st_size,
                        _ts(st.st_ctime), _ts(st.st_mtime), _ts(st.st_atime), mono_ns,
                    ))
                    count += 1
        self.wm.flush("filesystem_snapshot")
        logger("info", f"Filesystem snapshot: {count} files")
        return count

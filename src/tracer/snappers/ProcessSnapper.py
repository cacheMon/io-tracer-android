"""
ProcessSnapper - periodic process-state snapshots parsed directly from /proc.

Mirrors the Linux tracer's ``process`` stream but uses no third-party libraries
(no psutil), so it runs on a bare Android device. CPU-percent-over-interval is
not derivable from a single /proc pass without historical sampling, so the
``cpu_5s/2m/1h`` columns are emitted as 0.0 (schema-compatible placeholders);
``vms_kb``/``rss_kb``/``status``/``creation_time`` are real.
"""

import os
import threading
import time
from datetime import datetime

from ...utility.utils import format_csv_row, logger, simple_hash


# Linux/Android USER_HZ for converting starttime jiffies to seconds.
_USER_HZ = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
_PAGE_KB = (os.sysconf("SC_PAGE_SIZE") // 1024) if hasattr(os, "sysconf") else 4

_STATUS_MAP = {
    "R": "running", "S": "sleeping", "D": "disk-sleep", "Z": "zombie",
    "T": "stopped", "t": "tracing-stop", "X": "dead", "I": "idle",
}


class ProcessSnapper:
    def __init__(self, wm, anonymous: bool = False, interval_s: int = 300):
        self.wm = wm
        self.anonymous = anonymous
        self.interval_s = interval_s
        self.running = True
        self._boot_time = self._read_boot_time()

    @staticmethod
    def _read_boot_time() -> float:
        """Seconds since epoch at boot, from /proc/stat 'btime'."""
        try:
            with open("/proc/stat") as f:
                for line in f:
                    if line.startswith("btime "):
                        return float(line.split()[1])
        except OSError:
            pass
        return 0.0

    def _read_proc_row(self, pid: str, ts: str, mono_ns: int):
        """Build one process CSV row for ``pid``, or ``None`` if it vanished."""
        base = f"/proc/{pid}"
        try:
            with open(f"{base}/stat") as f:
                stat = f.read()
            # comm may contain spaces/parens; it is wrapped in the first (...).
            lp, rp = stat.index("("), stat.rindex(")")
            name = stat[lp + 1:rp]
            rest = stat[rp + 2:].split()
            # rest[0]=state ... rest[19]=starttime (0-based after comm); see proc(5).
            state = rest[0]
            starttime_jiffies = int(rest[19])
            with open(f"{base}/statm") as f:
                size_pages, rss_pages = f.read().split()[:2]
            vms_kb = int(size_pages) * _PAGE_KB
            rss_kb = int(rss_pages) * _PAGE_KB
            try:
                with open(f"{base}/cmdline", "rb") as f:
                    cmdline = f.read().replace(b"\x00", b" ").decode("utf-8", "replace").strip()
            except OSError:
                cmdline = ""
            if not cmdline:
                cmdline = name
            if self.anonymous:
                cmdline = simple_hash(cmdline, 12)
                name = simple_hash(name, 12)
            create_epoch = self._boot_time + (starttime_jiffies / _USER_HZ)
            create_str = datetime.fromtimestamp(create_epoch).strftime("%Y-%m-%d %H:%M:%S.%f") \
                if self._boot_time else ""
            status = _STATUS_MAP.get(state, state)
            return format_csv_row(
                ts, pid, name, cmdline, float(vms_kb), float(rss_kb),
                create_str, 0.0, 0.0, 0.0, status, mono_ns,
            )
        except (OSError, ValueError):
            return None

    def take_snapshot(self):
        """Capture all current processes into the writer's ``process`` buffer."""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        mono_ns = time.monotonic_ns()
        count = 0
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            row = self._read_proc_row(pid, ts, mono_ns)
            if row is not None:
                self.wm.append("process", row)
                count += 1
        self.wm.flush("process")
        logger("info", f"Process snapshot: {count} processes")
        return count

    def _loop(self):
        next_due = 0.0
        while self.running:
            now = time.monotonic()
            if now >= next_due:
                try:
                    self.take_snapshot()
                except Exception as e:
                    logger("warning", f"Process snapshot failed: {e}")
                next_due = time.monotonic() + self.interval_s
            time.sleep(1)

    def run(self):
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()
        return t

    def stop(self):
        self.running = False

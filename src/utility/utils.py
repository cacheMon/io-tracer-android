"""
Utility functions for the Android IO Tracer.

Deliberately dependency-free (standard library only) so the tracer can run on a
device under Termux or be driven over ``adb shell`` without pip-installing
anything. The optional ``zstandard`` module is imported lazily for compression;
when it is missing, trace files are simply left uncompressed.

Provides:
- Hashing helpers for anonymization
- A tiny logger
- CSV row formatting
- Android machine-id capture (stable, anonymized)
- A CLOCK_MONOTONIC -> CLOCK_REALTIME offset for deriving wall-clock timestamps
- Optional Zstandard compression
"""

import csv
import datetime
import hashlib
import io
import os
import subprocess
import threading
import time
from pathlib import Path


# ---------------------------------------------------------------------------
# Hashing / anonymization
# ---------------------------------------------------------------------------

_HASH_CACHE: dict[str, str] = {}


def simple_hash(content: str, length: int = 12) -> str:
    """Return a truncated SHA-256 hex digest of ``content``."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:length]


def hash_component(name: str, keep_ext: bool = True, length: int = 12) -> str:
    """Hash a single path component, optionally preserving its extension."""
    if keep_ext and "." in name and not name.startswith("."):
        stem, ext = os.path.splitext(name)
        key = f"{stem}|{length}"
        if key not in _HASH_CACHE:
            _HASH_CACHE[key] = hashlib.sha256(stem.encode("utf-8")).hexdigest()[:length]
        return _HASH_CACHE[key] + ext
    key = f"{name}|{length}"
    if key not in _HASH_CACHE:
        _HASH_CACHE[key] = hashlib.sha256(name.encode("utf-8")).hexdigest()[:length]
    return _HASH_CACHE[key]


def anonymize_path(path, keep_ext: bool = True, length: int = 12) -> str:
    """Anonymize a filesystem path by hashing every component.

    The leading "/" is preserved so absolute paths stay absolute and directory
    depth is retained, but no component is ever left in cleartext.
    """
    parts = list(Path(path).parts)
    if not parts:
        return path
    out = []
    for i, comp in enumerate(parts):
        if i == 0 and comp == os.sep:
            out.append(comp)
        else:
            out.append(hash_component(comp, keep_ext=keep_ext, length=length))
    return str(Path(*out))


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def logger(error_scale: str, string: str, timestamp: bool = False):
    """Print a formatted log message to stderr-style stdout."""
    logo = {
        "warning": "[WARN]",
        "error": "[ERROR]",
        "info": "[INFO]",
    }.get(error_scale, f"[{error_scale}]")
    if timestamp:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        logo += f" [{now}]"
    print(logo + " " + string, flush=True)


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

def format_csv_row(*fields) -> str:
    """Format fields as one CSV row (no trailing newline), with proper quoting."""
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="")
    writer.writerow(["" if f is None else f for f in fields])
    return output.getvalue()


# ---------------------------------------------------------------------------
# Clock: derive wall-clock time from CLOCK_MONOTONIC
# ---------------------------------------------------------------------------

def mono_to_real_offset_ns() -> int:
    """Return ``CLOCK_REALTIME_ns - CLOCK_MONOTONIC_ns`` sampled now.

    ftrace event timestamps (with ``trace_clock=mono``) are CLOCK_MONOTONIC.
    Adding this offset recovers a wall-clock instant. Captured once at session
    start and recorded in ``manifest.json`` so consumers can re-derive it.
    """
    mono = time.monotonic_ns()
    real = time.time_ns()
    return real - mono


def mono_ns_to_datetime_str(mono_ns: int, offset_ns: int) -> str:
    """Format a CLOCK_MONOTONIC ns reading as a wall-clock string."""
    real_ns = int(mono_ns) + int(offset_ns)
    dt = datetime.datetime.fromtimestamp(real_ns / 1e9)
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")


# ---------------------------------------------------------------------------
# Machine ID (Android-aware, anonymized)
# ---------------------------------------------------------------------------

def _read_first(*paths) -> str | None:
    for p in paths:
        try:
            with open(p) as f:
                v = f.read().strip()
                if v:
                    return v
        except OSError:
            continue
    return None


def _getprop(name: str) -> str | None:
    """Read an Android system property via ``getprop`` if available."""
    try:
        out = subprocess.check_output(
            ["getprop", name], text=True, stderr=subprocess.DEVNULL, timeout=5
        ).strip()
        return out or None
    except Exception:
        return None


def capture_machine_id() -> str:
    """Capture a stable, anonymized 16-char machine identifier.

    Tries, in order: Android serial number / boot id via ``getprop``, the Linux
    ``/etc/machine-id`` or ``/proc/sys/kernel/random/boot_id``, then the
    hostname. Whatever raw identifier is found is hashed, so the on-disk id never
    reveals the real device serial.
    """
    raw = (
        _getprop("ro.serialno")
        or _getprop("ro.boot.serialno")
        or _read_first("/etc/machine-id", "/proc/sys/kernel/random/boot_id")
        or _read_first("/proc/sys/kernel/hostname")
        or "unknown-device"
    )
    return simple_hash(raw, 16)


# ---------------------------------------------------------------------------
# Optional Zstandard compression
# ---------------------------------------------------------------------------

ZSTD_LEVEL = 3
_zstd_warned = False
_zstd_warn_lock = threading.Lock()


def zstandard_available():
    """Return the ``zstandard`` module if importable, else ``None`` (warn once)."""
    global _zstd_warned
    try:
        import zstandard
    except ImportError:
        with _zstd_warn_lock:
            if not _zstd_warned:
                _zstd_warned = True
                logger(
                    "warning",
                    "The 'zstandard' library is not installed; trace files will be "
                    "kept uncompressed. Install it with 'pip install zstandard' to "
                    "enable .zst compression.",
                )
        return None
    return zstandard


def compress_file_zstd(src: str, dst: str, level: int = ZSTD_LEVEL) -> bool:
    """Stream-compress ``src`` to ``dst`` (.zst). Returns False if zstd missing."""
    zstandard = zstandard_available()
    if zstandard is None:
        return False
    cctx = zstandard.ZstdCompressor(level=level)
    with open(src, "rb") as f_in, open(dst, "wb") as f_out:
        cctx.copy_stream(f_in, f_out)
    return True


def compress_log(input_file: str) -> str:
    """Compress ``input_file`` to ``.zst`` and remove the original on success.

    Returns the path that now holds the data (``.zst`` when compressed, else the
    original uncompressed path).
    """
    if not os.path.exists(input_file):
        return input_file
    dst = input_file + ".zst"
    if compress_file_zstd(input_file, dst):
        os.remove(input_file)
        return dst
    return input_file

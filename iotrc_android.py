#!/usr/bin/env python3
"""
Android IO Tracer - an I/O logging tool that collects the same kind of data as
the Linux io-tracer, but on Android.

Where the Linux tracer uses eBPF/BCC, this tool uses the kernel's **ftrace**
interface (``/sys/kernel/tracing``) plus ``/proc``, so it needs no compiler, no
BCC, and no third-party Python packages on the device. It emits the identical
on-disk schema (see ``src/tracer/schema.py``) so traces from either OS can be
read by a single parser.

Streams collected:
  * ds  (block I/O)            - paired block_rq_issue/complete tracepoints
  * fs  (filesystem, optional) - f2fs/ext4 read/write tracepoints (--trace-fs)
  * process snapshots          - periodic /proc walk
  * filesystem snapshot        - one-shot directory inventory (--fs-snapshot)
  * system_spec                - device hardware/software JSON

Run with root on the device (block tracing needs CAP_SYS_ADMIN on tracefs):

    adb push . /data/local/tmp/iotracer
    adb shell "su 0 python3 /data/local/tmp/iotracer/iotrc_android.py -o /data/local/tmp/trace"

Then pull the results:

    adb pull /data/local/tmp/trace ./trace

Usage:
    python3 iotrc_android.py [-o OUTPUT_DIR] [-a] [--trace-fs] [--fs-snapshot]
                             [--tracefs PATH] [--computer-id]
"""

import argparse
import os
import sys
import tempfile

# Allow running both as "python3 iotrc_android.py" and "python3 -m ...".
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.tracer.AndroidIOTracer import AndroidIOTracer
from src.utility.utils import capture_machine_id


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Trace Android I/O (block + snapshots) via ftrace and /proc.")
    parser.add_argument("-o", "--output", default=None,
                        help="Output directory (default: a timestamped dir under TMPDIR).")
    parser.add_argument("-a", "--anonymize", action="store_true",
                        help="Hash process names, command lines, and file paths.")
    parser.add_argument("--trace-fs", action="store_true",
                        help="Also enable best-effort f2fs/ext4 filesystem tracepoints.")
    parser.add_argument("--fs-snapshot", action="store_true",
                        help="Capture a one-shot filesystem inventory snapshot at start.")
    parser.add_argument("--tracefs", default=None,
                        help="Override the tracefs mount point (default: auto-detect).")
    parser.add_argument("--process-interval", type=int, default=300,
                        help="Seconds between process snapshots (default: 300).")
    parser.add_argument("--computer-id", action="store_true",
                        help="Print this device's anonymized machine ID and exit.")
    args = parser.parse_args(argv)

    if args.computer_id:
        print(f"Here is your device ID: {capture_machine_id().upper()}")
        return 0

    output_dir = args.output or os.path.join(
        tempfile.gettempdir(),
        "android_trace_" + capture_machine_id().upper(),
    )
    os.makedirs(output_dir, exist_ok=True)

    tracer = AndroidIOTracer(
        output_dir=output_dir,
        anonymous=args.anonymize,
        trace_fs=args.trace_fs,
        fs_snapshot=args.fs_snapshot,
        tracefs_path=args.tracefs,
        process_interval_s=args.process_interval,
    )
    tracer.trace()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

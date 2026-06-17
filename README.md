# IO-Tracer (Android)

An I/O logging tool for Android that collects the **same kind of data as the
[Linux io-tracer](https://github.com/cacheMon/io-tracer-linux)** — block-device
I/O, process state, filesystem inventory, and system specs — and writes it in the
**same on-disk schema**, so a single downstream parser can read traces from either
operating system.

## How it differs from the Linux tracer

The Linux tracer collects events with **eBPF/BCC**. That stack is impractical on a
stock Android device (no BCC, no compiler, no on-device Python packages), so this
tool collects the equivalent data through interfaces every Android kernel already
ships:

| Concern            | Linux io-tracer            | Android io-tracer                         |
|--------------------|----------------------------|-------------------------------------------|
| Block I/O          | eBPF kprobes               | **ftrace** `block_rq_issue`/`block_rq_complete` |
| Process snapshots  | `psutil`                   | direct `/proc` parsing (no deps)          |
| Filesystem snapshot| `os.walk`                  | `os.walk` (Android roots)                 |
| System spec        | `psutil` + `lsblk`         | `/proc` + `getprop`                       |
| Output schema      | `schema.py` v3             | **identical** `schema.py` v3              |
| Dependencies       | psutil, requests, zstd     | **stdlib only** (zstd optional)           |

The on-disk column layout is byte-for-byte compatible with the Linux tracer (see
[`src/tracer/schema.py`](src/tracer/schema.py)), and every record carries a
`mono_ns` (CLOCK_MONOTONIC) column for cross-stream correlation.

> **Prefer a UI?** There is also a native **Android app** (`app/` module) that
> runs the same rooted block-I/O collection with a Start/Stop screen and a
> foreground service — no host/`adb` driving required. See
> [docs/ANDROID_APP.md](docs/ANDROID_APP.md). The CLI below remains the reference
> collector and host driver.

## Requirements

- An Android device with **root** (the block-I/O collector needs `CAP_SYS_ADMIN`
  on tracefs — a rooted or `userdebug` build).
- `python3` available on the device (e.g. via Termux) **or** drive it from a host
  over `adb`.
- ftrace mounted at `/sys/kernel/tracing` (or `/sys/kernel/debug/tracing`).
- Optional: `pip install zstandard` to compress traces to `.csv.zst` (without it
  the tracer still runs and leaves CSVs uncompressed).

No other Python packages are required.

## Usage

```
usage: iotrc_android.py [-h] [-o OUTPUT] [-a] [--trace-fs] [--fs-snapshot]
                        [--tracefs PATH] [--process-interval N] [--computer-id]

options:
  -o, --output OUTPUT     Output directory (default: timestamped dir in TMPDIR)
  -a, --anonymize         Hash process names, command lines, and file paths
  --trace-fs              Also enable best-effort f2fs/ext4 filesystem tracepoints
  --fs-snapshot           Capture a one-shot filesystem inventory at start
  --tracefs PATH          Override the tracefs mount point (default: auto-detect)
  --process-interval N    Seconds between process snapshots (default: 300)
  --computer-id           Print this device's anonymized machine ID and exit
```

### Run on-device (rooted, with Python)

```bash
adb push . /data/local/tmp/iotracer
adb shell "su 0 python3 /data/local/tmp/iotracer/iotrc_android.py \
    -o /data/local/tmp/trace --fs-snapshot"
# ... Ctrl-C / send SIGTERM to stop ...
adb pull /data/local/tmp/trace ./trace
```

The tracer runs until it receives `SIGINT`/`SIGTERM`, then flushes all buffers,
restores the device's original ftrace state, and writes `manifest.json`.

### Snapshot-only mode

If tracefs is not accessible (no root, or block events unavailable), the tool
automatically falls back to **snapshot-only mode**: it still collects process,
filesystem, and system-spec data and writes a valid session — only the `ds`/`fs`
event streams are skipped.

## Output

```
{output_dir}/
├── manifest.json               # schema + machine id + clock offset + row counts
├── ds/                         # block I/O events  (ds_*.csv.zst)
├── fs/                         # filesystem events (fs_*.csv.zst, with --trace-fs)
├── process/                    # periodic /proc snapshots
├── filesystem_snapshot/        # one-shot inventory (with --fs-snapshot)
└── system_spec/                # cpu/memory/disk/os JSON
```

See [docs/TRACE_TYPES.md](docs/TRACE_TYPES.md) and
[docs/TRACE_FORMAT.md](docs/TRACE_FORMAT.md) for the full schema, and
[docs/traces/BLOCK_IO_EVENTS.md](docs/traces/BLOCK_IO_EVENTS.md) for how block
latency is recovered from the issue/complete tracepoint pair.

### Reading a trace

```python
import glob, pandas as pd
# pandas reads .zst natively when the `zstandard` package is installed.
df = pd.concat(pd.read_csv(f) for f in glob.glob("trace/ds/ds_*.csv.zst"))
print(df.groupby("operation")["latency_ms"].describe())
```

## Tests

```bash
pip install pytest
python3 -m pytest -q
```

The suite covers ftrace line parsing, block issue/complete pairing and latency
recovery, the cross-OS schema contract, the writer's on-disk layout/manifest, and
the `/proc` process snapper (the last runs against the live `/proc`, so it works
on any Linux/Android host).

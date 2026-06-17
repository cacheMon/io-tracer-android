# IO-Tracer (Android)

An I/O logging tool for Android that collects the **same kind of data as the
[Linux io-tracer](https://github.com/cacheMon/io-tracer-linux)** — block-device
I/O, process state, and system specs — and writes it in the **same on-disk
schema**, so a single downstream parser can read traces from either operating
system.

It ships in two forms that produce the same trace schema:

| | **📱 Android app** (default) | Command-line collector |
|---|---|---|
| Use it when | You want a one-tap, on-device tracer | Scripting / host-driven captures over `adb` |
| Interface | Start/Stop UI + foreground service | `iotrc_android.py` CLI |
| Runtime | Kotlin APK, no Python needed | Python 3 (stdlib only) |
| Streams | block I/O, process, system spec | + filesystem snapshot/events |
| Compression | `.csv.gz` | `.csv.zst` (optional) |
| Docs | **[docs/ANDROID_APP.md](docs/ANDROID_APP.md)** | [below](#command-line-collector-advanced) |

Both require **root** for block-I/O tracing (they read `/sys/kernel/tracing` via
ftrace). The on-disk column layout is byte-for-byte compatible across both and
with the Linux tracer (see [`src/tracer/schema.py`](src/tracer/schema.py)); every
record carries a `mono_ns` (CLOCK_MONOTONIC) column for cross-stream correlation.

---

## 📱 Android app (recommended)

A native app (`app/` module) that runs the rooted block-I/O collector on-device
with a Jetpack Compose Start/Stop screen and a foreground service — no host or
`adb` driving required.

**Requirements:** a rooted / `userdebug` device (Android 8.0+, minSdk 26).

```bash
# Build the debug APK (or just open the repo in Android Studio and Run ▶)
gradle :app:assembleDebug

# Install on a rooted device
adb install app/build/outputs/apk/debug/app-debug.apk
```

Then on the device:

1. Launch **IO Tracer** and grant the `su` request.
2. Choose options (anonymize, snapshot interval) and tap **Start tracing**.
3. Reproduce your workload — the notification shows live event counts.
4. Tap **Stop**; buffers flush, ftrace state is restored, `manifest.json` is written.

Pull the results:

```bash
adb pull /sdcard/Android/data/com.cachemon.iotracer/files/traces ./traces
```

On Android 11+, scoped storage can block `adb` from reading another app's
`Android/data` directly (and `adb root` is unavailable on most Magisk-rooted
retail devices). If the pull fails, use the app's **Share** button, or copy the
session to a public directory as root first:

```bash
adb shell "su -c 'cp -r /sdcard/Android/data/com.cachemon.iotracer/files/traces /data/local/tmp/traces'"
adb pull /data/local/tmp/traces ./traces
```

Full build/run/architecture details — and the note on keeping the Kotlin engine
in sync with the Python schema — are in **[docs/ANDROID_APP.md](docs/ANDROID_APP.md)**.

### No rooted device?

Block-I/O tracing needs root (the kernel ftrace interface is root-only). On an
**unrooted** device you can still collect process/system/filesystem **snapshots**
using the Python CLI in Termux, and there's an emulator path for getting root
without rooting a phone — see **[docs/UNROOTED.md](docs/UNROOTED.md)**.

---

## Command-line collector (advanced)

For scripted or host-driven captures, `iotrc_android.py` collects the same data
(plus filesystem snapshots/events) via ftrace + `/proc`, using only the Python
standard library — runnable on-device under Termux or driven from a host over
`adb`.

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

```bash
# Drive a rooted device from a host
adb push . /data/local/tmp/iotracer
adb shell "su 0 python3 /data/local/tmp/iotracer/iotrc_android.py \
    -o /data/local/tmp/trace --fs-snapshot"
# ... Ctrl-C / send SIGTERM to stop ...
adb pull /data/local/tmp/trace ./trace
```

The CLI runs until it receives `SIGINT`/`SIGTERM`, then flushes all buffers,
restores the device's original ftrace state, and writes `manifest.json`.
`pip install zstandard` enables `.csv.zst` compression (without it traces are
left uncompressed). If tracefs is unavailable it falls back to **snapshot-only
mode** (process/filesystem/system specs, no `ds`/`fs` event streams).

---

## Output

Each run produces a self-describing session directory with the same layout. The
**app** writes it under `…/files/traces/<session>/`; the **CLI** writes straight
into its `-o` output directory.

```
<session>/                      # app: …/files/traces/<session>/  ·  CLI: the -o dir
├── manifest.json               # schema + machine id + clock offset + row counts
├── ds/                         # block I/O events       (.csv.gz app / .csv.zst CLI)
├── fs/                         # filesystem events      (CLI --trace-fs)
├── process/                    # periodic process snapshots
├── filesystem_snapshot/        # one-shot inventory     (CLI --fs-snapshot)
└── system_spec/                # cpu/memory/os JSON
```

Full documentation is indexed in **[docs/](docs/README.md)** —
[trace types & collection](docs/TRACE_TYPES.md),
[trace format](docs/TRACE_FORMAT.md) (the full schema), and
[block I/O events](docs/traces/BLOCK_IO_EVENTS.md) (how latency is recovered from
the issue/complete tracepoint pair).

### Reading a trace

```python
import glob, pandas as pd
# pandas reads .gz and .zst natively (.zst needs the `zstandard` package).
# App traces live in per-session subdirs (traces/<session>/ds/); the CLI writes
# straight into its -o directory (trace/ds/), so it has no extra session level.
files = glob.glob("traces/*/ds/ds_*.csv.gz") + glob.glob("trace/ds/ds_*.csv.zst")
df = pd.concat(pd.read_csv(f) for f in files)
print(df.groupby("operation")["latency_ms"].describe())
```

---

## How it differs from the Linux tracer

The Linux tracer collects events with **eBPF/BCC**. That stack is impractical on a
stock Android device (no BCC, no compiler, no on-device Python packages), so this
tool collects the equivalent data through interfaces every Android kernel already
ships:

| Concern            | Linux io-tracer            | Android io-tracer                         |
|--------------------|----------------------------|-------------------------------------------|
| Block I/O          | eBPF kprobes               | **ftrace** `block_rq_issue`/`block_rq_complete` |
| Process snapshots  | `psutil`                   | direct `/proc` / `ps` parsing             |
| System spec        | `psutil` + `lsblk`         | `/proc` + `getprop`                       |
| Output schema      | `schema.py` v3             | **identical** `schema.py` v3              |
| Dependencies       | psutil, requests, zstd     | app: none · CLI: stdlib only              |

---

## Tests

```bash
# App engine (Kotlin parser/pairer/writer/proc) — runs in CI on every push/PR
gradle :app:testDebugUnitTest

# CLI (Python)
pip install pytest
python3 -m pytest -q
```

The Python suite covers ftrace line parsing, block issue/complete pairing and
latency recovery, the cross-OS schema contract, the writer's on-disk
layout/manifest, and the `/proc` process snapper. The Kotlin suite mirrors the
parser/pairer tests and adds writer/process-line coverage.

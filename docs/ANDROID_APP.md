# Android App (rooted block-I/O tracer)

The **default, recommended way to use IO-Tracer on Android**: a native app
(`app/` module) that runs the block-I/O collector on-device with a Start/Stop UI
and a foreground service — no host or `adb` driving required. It produces the
**same CSV schema** as the Python CLI and the Linux tracer; the only difference
is the compression container (`.csv.gz` here vs `.csv.zst`). For scripted or
host-driven captures, the Python CLI (`iotrc_android.py`) remains available — see
the repository [README](../README.md).

## Requirements

- A **rooted** (or `userdebug`) device — block tracing reads `/sys/kernel/tracing`
  via `su`. Without root the app still runs but can only do process/system
  snapshots (no block I/O).
- Android 8.0+ (minSdk 26).

## What it collects

| Stream | Source | Output |
|--------|--------|--------|
| `ds` (block I/O) | ftrace `block_rq_issue`/`block_rq_complete` via `su`, paired for latency | `ds/ds_*.csv.gz` |
| `process` | `ps -A` via `su`, on an interval | `process/process_*.csv.gz` |
| system spec | `getprop` + `/proc` | `system_spec/*.json` |
| manifest | schema + machine id + clock offset + counts | `manifest.json` |

Output is written under the app's external files dir:
`Android/data/com.cachemon.iotracer/files/traces/<session>/`.

## Architecture

```
MainActivity (Compose UI)
   │  Start/Stop, options, live counters
   ▼
TracerService (foreground service)
   │  owns the engine, posts the ongoing notification
   ▼
TraceEngine
   ├─ RootShell ............. su exec + streaming
   ├─ FtraceControl ......... enable/stream/teardown tracefs scripts
   ├─ FtraceParser .......... parse trace_pipe lines  (port of parsers.py)
   ├─ BlockPairer ........... issue→complete latency   (port of BlockPairer)
   ├─ ProcSnapper / SystemSnapper
   └─ TraceWriter ........... gzip CSV streams + manifest.json
```

`FtraceParser`, `BlockPairer`, and `Schema` are 1:1 ports of the Python modules
and **must be kept in sync** (same `SCHEMA_VERSION = 3`, same column order). The
JVM unit tests in `app/src/test` mirror `tests/test_parsers.py`.

## Build

The repo has no committed Gradle wrapper jar; build with Android Studio (which
generates the wrapper) or with a system Gradle 8.7:

```bash
# Android Studio: open the repo root, let it sync, Run ▶
# or CLI:
gradle :app:assembleDebug          # APK -> app/build/outputs/apk/debug/
gradle :app:testDebugUnitTest      # run the parser/pairer unit tests
```

CI (`.github/workflows/android.yml`) runs the unit tests and assembles the debug
APK on every push/PR and uploads the APK as an artifact.

## Run

1. Install the debug APK on a rooted device (`adb install app-debug.apk`).
2. Launch **IO Tracer**; grant the `su` request when prompted.
3. Set options (anonymize, snapshot interval) and tap **Start tracing**.
4. Reproduce your workload; the notification shows live event counts.
5. Tap **Stop** — buffers flush, ftrace state is restored, `manifest.json` is written.
6. Pull the session:
   ```bash
   adb pull /sdcard/Android/data/com.cachemon.iotracer/files/traces ./traces
   ```

## Reading the output

Same as the CLI, but gzip instead of zstd:

```python
import glob, pandas as pd
df = pd.concat(pd.read_csv(f) for f in glob.glob("traces/*/ds/ds_*.csv.gz"))
print(df.groupby("operation")["latency_ms"].describe())
```

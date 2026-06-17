# Android App (rooted block-I/O tracer)

> 📖 [Docs index](README.md) · no rooted device? see [Quick start without root](UNROOTED.md).

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

## Releases (signed release APK)

A signed **release** APK is produced by `.github/workflows/release.yml`:

- **Push a tag** `vX.Y.Z` (e.g. `git tag v0.1.0 && git push origin v0.1.0`) — the
  workflow builds, signs, and publishes a **GitHub Release** with the APK attached.
- Or trigger it manually from **Actions ▸ Release APK ▸ Run workflow**; the signed
  APK is uploaded as a workflow artifact.

**Signing.** If the repo defines `KEYSTORE_BASE64`, `KEYSTORE_PASSWORD`,
`KEY_ALIAS`, and `KEY_PASSWORD` secrets, the APK is signed with that keystore —
use this so updates install in place over previous versions. Without those
secrets the workflow generates an **ephemeral** keystore so the build still yields
an installable, signed APK; note an ephemeral signature changes every run, so
those builds can't update an already-installed copy (uninstall first).

To create the keystore for the secrets path:

```bash
keytool -genkeypair -v -keystore release.jks -alias iotracer \
  -keyalg RSA -keysize 2048 -validity 10000
base64 release.jks | tr -d '\n'   # paste into the KEYSTORE_BASE64 repo secret
```

Build a signed release APK locally:

```bash
KEYSTORE_FILE=$PWD/release.jks KEYSTORE_PASSWORD=… KEY_ALIAS=iotracer KEY_PASSWORD=… \
  gradle :app:assembleRelease     # APK -> app/build/outputs/apk/release/
```

> Release builds use the same code as debug (`isMinifyEnabled = false`); only
> signing differs. The app still requires **root** at runtime.

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
   On Android 11+, scoped storage can block `adb` from reading another app's
   `Android/data` directly (and `adb root` is unavailable on most Magisk-rooted
   retail devices). If the pull fails, use the in-app **Share** button, or copy
   to a public directory as root first:
   ```bash
   adb shell "su -c 'cp -r /sdcard/Android/data/com.cachemon.iotracer/files/traces /data/local/tmp/traces'"
   adb pull /data/local/tmp/traces ./traces
   ```

## Reading the output

Same as the CLI, but gzip instead of zstd:

```python
import glob, pandas as pd
df = pd.concat(pd.read_csv(f) for f in glob.glob("traces/*/ds/ds_*.csv.gz"))
print(df.groupby("operation")["latency_ms"].describe())
```

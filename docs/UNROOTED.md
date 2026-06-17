# Quick start without a rooted phone

> 📖 [Docs index](README.md) · for the rooted flow see [Android app](ANDROID_APP.md).

Block-I/O tracing reads the kernel's **ftrace** interface
(`/sys/kernel/tracing`), which is **root-only** — so the `ds` (block I/O) stream
can't be captured without root. This guide covers what you *can* do on an
unrooted device, and the easiest ways to get root for the full block trace.

| | Unrooted device | Rooted device / emulator |
|---|---|---|
| Process snapshots | ✅ (your own / visible processes) | ✅ (all processes) |
| System spec | ✅ | ✅ |
| Filesystem snapshot | ✅ (accessible paths) | ✅ |
| **Block I/O (`ds`)** | ❌ needs root | ✅ |
| Easiest tool | **Python CLI in Termux** | App, or CLI |

---

## 1. Snapshot-only on an unrooted device (Termux)

The Python CLI reads `/proc` directly (no `su`) and **automatically falls back to
snapshot-only mode** when ftrace isn't accessible, so it runs fine as an ordinary
app. The on-device Android app, by contrast, routes its collectors through `su`,
so on an unrooted device use the CLI below.

1. Install [Termux](https://termux.dev/) (F-Droid build recommended).
2. In Termux:

   ```bash
   pkg update && pkg install -y python git
   git clone https://github.com/cacheMon/io-tracer-android
   cd io-tracer-android
   python iotrc_android.py -o "$HOME/trace" --fs-snapshot
   #  … reproduce your workload …
   #  press Ctrl-C to stop and flush
   ls "$HOME/trace"
   ```

You'll get `process/`, `system_spec/`, and (with `--fs-snapshot`)
`filesystem_snapshot/`, plus `manifest.json`. The `ds/` block stream will be
empty — the log prints a line explaining tracefs wasn't accessible.

> **Note:** without root, an app only sees processes and files your user is
> allowed to read (Android applies `hidepid`/scoped storage), so these snapshots
> are partial. They're still useful as context, but they are not a full
> system-wide inventory.

---

## 2. Getting root for the full block trace

You don't need to root your daily-driver phone — any of these works:

### a. Rootable emulator (no physical device needed)

Create an Android Virtual Device with a **non-Play** system image — a
*Google APIs* or *AOSP* image, **not** a *Google Play* one (Play images are
production-signed and refuse `adb root`):

```bash
# Android Studio ▸ Device Manager ▸ create AVD with a "Google APIs" image, then:
adb root                 # restarts adbd as root (works on non-Play images)
adb shell setenforce 0   # permissive SELinux — avoids denials when poking tracefs
adb shell 'ls /sys/kernel/tracing/trace_pipe'   # confirm tracefs is reachable
```

With `adb root`, an `adb shell` runs as root, so the **CLI** can trace block I/O
when run from that shell (push the repo and run it under a root shell that has
Python — e.g. via Termux installed in the AVD, or an image with Python). To use
the **app** on an emulator, either disable SELinux on a `userdebug` image —
`adb root` then `adb shell setenforce 0`, which lets the app use the image's
built-in `su` binary — or install Magisk on the AVD (e.g. the community
*rootAVD* script) so the app's root requests resolve.

### b. Magisk on a physical device

Root with [Magisk](https://github.com/topjohnwu/Magisk); grant the app (or
`adb shell`) root. Then follow the normal flow in the
[README](../README.md) or [ANDROID_APP.md](ANDROID_APP.md).

### c. `userdebug` / `eng` build

If you build AOSP yourself, a `userdebug` or `eng` build has `adb root` and full
tracefs access out of the box.

---

## Which streams need root?

| Stream | Source | Root required? |
|---|---|---|
| `ds` (block I/O) | ftrace `block_rq_*` | **Yes** |
| `fs` (filesystem events, CLI `--trace-fs`) | ftrace f2fs/ext4 | **Yes** |
| `process` | `/proc` (CLI) / `ps` (app) | No (CLI) — partial without root |
| `filesystem_snapshot` | `os.walk` | No — limited to accessible paths |
| `system_spec` | `/proc` + `getprop` | No |

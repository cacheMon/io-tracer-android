# Trace Types and Collection Methods (Android)

> 📖 [Docs index](README.md) · for the exact columns of each stream see
> [Trace format](TRACE_FORMAT.md).

Both the [Android app](ANDROID_APP.md) and the Python CLI collect I/O data
through the kernel **ftrace** interface (`/sys/kernel/tracing`) and `/proc`,
rather than the eBPF/BCC stack used by the Linux tracer. They produce the same
logical streams in the same on-disk schema (see
[`src/tracer/schema.py`](../src/tracer/schema.py)). Files are compressed to
`.csv.gz` (app) or `.csv.zst` (CLI); the columns are identical.

## Real-Time Trace Types

| # | Trace Type | Collection Method | Output |
|---|------------|-------------------|--------|
| 1 | [Block I/O Events](traces/BLOCK_IO_EVENTS.md) | ftrace `block:block_rq_issue` + `block:block_rq_complete`, paired by `(device, sector)` | `ds/` |
| 2 | Filesystem (VFS) Events *(experimental, CLI `--trace-fs`)* | ftrace `f2fs`/`ext4` read/write tracepoints (inode-keyed; filenames best-effort) | `fs/` |

> **Block I/O is the primary stream.** It is the most reliable signal available
> on a stock Android kernel and is what storage/cache research depends on. The
> filesystem stream is opt-in and best-effort because filename resolution from
> ftrace text is kernel-dependent.

## Snapshot Types

| # | Snapshot Type | Collection Method | Output |
|---|---------------|-------------------|--------|
| 1 | Process Snapshot | periodic `/proc` (CLI) / `ps -A` (app) | `process/` |
| 2 | Filesystem Snapshot *(CLI `--fs-snapshot`)* | `os.walk` of Android roots | `filesystem_snapshot/` |
| 3 | System Snapshot | `/proc` + `getprop` | `system_spec/*.json` |

## Architecture Overview

The diagram below shows the **CLI** collection pipeline; the app mirrors the same
stages in Kotlin (`FtraceParser`, `BlockPairer`, the snappers, `TraceWriter`) —
see [Android app › Architecture](ANDROID_APP.md#architecture).

```
┌──────────────────────────────────────────────────────────────┐
│                    Android IO Tracer                          │
├──────────────────────────────────────────────────────────────┤
│  /sys/kernel/tracing                                          │
│  ┌────────────────┐  trace_clock=mono                         │
│  │ FtraceManager  │  enables block (+fs) tracepoints          │
│  └───────┬────────┘  reads trace_pipe line by line            │
│          │                                                    │
│  ┌───────▼────────┐    ┌──────────────────────────────────┐  │
│  │   parsers      │───►│ BlockPairer: issue→complete       │  │
│  │ parse_common   │    │  → device latency, request_id     │  │
│  └───────┬────────┘    └──────────────────────────────────┘  │
│          │                                                    │
│  ┌───────▼────────┐    ┌──────────────────────────────────┐  │
│  │   snappers     │    │ SystemSnapper  (once)             │  │
│  │  (/proc)       │    │ ProcessSnapper (periodic)         │  │
│  │                │    │ FilesystemSnapper (--fs-snapshot) │  │
│  └───────┬────────┘    └──────────────────────────────────┘  │
│          │                                                    │
│  ┌───────▼────────┐  ds/*.csv.zst, fs/*.csv.zst,             │
│  │  WriteManager  │  process/*.csv.zst, filesystem_snapshot, │
│  │                │  system_spec/*.json, manifest.json       │
│  └────────────────┘                                          │
└──────────────────────────────────────────────────────────────┘
```

## Clocks

ftrace's `trace_clock` is switched to `mono` (CLOCK_MONOTONIC) for the session, so
event timestamps share a clock with the snapshot streams' `mono_ns` column. The
wall-clock `timestamp` column is derived as
`mono_ns + manifest.clock.mono_to_real_offset_ns`, where the offset is sampled
once at session start and recorded in `manifest.json`.

## Performance Considerations

- **Block tracing** has low, bounded overhead — only request issue/completion is
  recorded, not per-byte activity.
- **Filesystem tracing** (`--trace-fs`) can be noisier and is kernel-dependent;
  it is off by default.
- **Snapshots** are lightweight: the system spec is captured once, process
  snapshots run on an interval (default 5 minutes), and the filesystem inventory
  is a single opt-in pass.

## See also

- [Trace format](TRACE_FORMAT.md) — the exact CSV columns for each stream.
- [Block I/O events](traces/BLOCK_IO_EVENTS.md) — the primary `ds` stream in detail.

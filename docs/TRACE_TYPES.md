# Trace Types and Collection Methods (Android)

The Android IO Tracer collects I/O data through the kernel **ftrace** interface
(`/sys/kernel/tracing`) and `/proc`, rather than the eBPF/BCC stack used by the
Linux tracer. It produces the same logical streams in the same on-disk schema
(see [`src/tracer/schema.py`](../src/tracer/schema.py)).

## Real-Time Trace Types

| # | Trace Type | Collection Method | Output |
|---|------------|-------------------|--------|
| 1 | [Block I/O Events](traces/BLOCK_IO_EVENTS.md) | ftrace `block:block_rq_issue` + `block:block_rq_complete`, paired by `(device, sector)` | `ds/ds_*.csv.zst` |
| 2 | Filesystem (VFS) Events *(experimental, `--trace-fs`)* | ftrace `f2fs`/`ext4` read/write tracepoints (inode-keyed; filenames best-effort) | `fs/fs_*.csv.zst` |

> **Block I/O is the primary stream.** It is the most reliable signal available
> on a stock Android kernel and is what storage/cache research depends on. The
> filesystem stream is opt-in and best-effort because filename resolution from
> ftrace text is kernel-dependent.

## Snapshot Types

| # | Snapshot Type | Collection Method | Output |
|---|---------------|-------------------|--------|
| 1 | Process Snapshot | periodic `/proc/<pid>` walk | `process/*.csv.zst` |
| 2 | Filesystem Snapshot *(`--fs-snapshot`)* | `os.walk` of Android roots | `filesystem_snapshot/*.csv.zst` |
| 3 | System Snapshot | `/proc` + `getprop` | `system_spec/*.json` |

## Architecture Overview

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

# Trace Output Format (Android)

This document describes the CSV output of the Android IO Tracer. The on-disk
schema is defined once, in [`src/tracer/schema.py`](../src/tracer/schema.py),
which is the single source of truth — the CSV header rows and `manifest.json` are
both derived from it. The layout is kept **byte-for-byte compatible** with the
Linux io-tracer so one parser reads either OS. Bump `SCHEMA_VERSION` whenever
columns change.

## Output Structure

```
{output_dir}/
├── manifest.json
├── ds/                     # Block device traces
├── fs/                     # Filesystem (VFS) traces  (--trace-fs)
├── process/                # Process state snapshots
├── filesystem_snapshot/    # Filesystem inventory     (--fs-snapshot)
└── system_spec/            # System specification JSON
```

Each stream's CSV begins with a header row and ends every record with a `mono_ns`
(CLOCK_MONOTONIC nanoseconds) column — the common clock for correlating records
across streams. CSV files are compressed to `.csv.zst` (Zstandard) when the
`zstandard` package is installed; otherwise they are left as `.csv`.

File naming: `{type}_{YYYYMMDD_HHMMSS_mmm}_{seq}.csv[.zst]`.

### manifest.json

Written once at the session root. It embeds `schema_version`, the full column
list for every stream, the anonymized `machine_id`, the
`clock.mono_to_real_offset_ns` used to derive wall-clock time, and per-stream
`rows_written`/`files_written` diagnostics. Consumers should read the schema from
`manifest.json` rather than hard-coding column positions.

---

## 1. Block Device Traces (`ds`)

**Location:** `ds/ds_*.csv.zst`

**Description:** Block-layer I/O completions with device latency recovered by
pairing the `block_rq_issue` and `block_rq_complete` ftrace tracepoints.

### CSV Header

```csv
timestamp,operation,pid,tid,command,sector,size,latency_ms,device,flags,cpu_id,ppid,queue_latency_ms,command_flags,operation_code,request_id,mono_ns
```

Columns 1–10 (`timestamp` … `flags`) are the cross-OS shared prefix. `operation`
holds the base op only (`read`, `write`, `flush`, `discard`, …); rwbs sub-flags
(`sync`, `meta`, `ahead`, …) live in the dedicated `flags` column.

On Android via ftrace text, `tid`, `ppid`, `queue_latency_ms`, `command_flags`,
and `operation_code` are not available and are emitted empty. See
[traces/BLOCK_IO_EVENTS.md](traces/BLOCK_IO_EVENTS.md).

---

## 2. Filesystem (VFS) Traces (`fs`) — experimental

**Location:** `fs/fs_*.csv.zst` (only with `--trace-fs`)

### CSV Header

```csv
timestamp,operation,pid,tid,command,filename,size,offset,bytes_completed,inode,device,flags,duration_ns,return_value,errno,mmap_prot,mmap_flags,address,cmdline,ppid,container_id,fs_type,mono_ns
```

Derived from `f2fs`/`ext4` read/write tracepoints where available. `filename` is
best-effort (often empty, since ftrace cannot resolve paths); `inode`, `offset`,
and `size` are the primary signal.

---

## 3. Process Snapshots (`process`)

**Location:** `process/process_*.csv.zst`

### CSV Header

```csv
timestamp,pid,name,cmdline,vms_kb,rss_kb,creation_time,cpu_5s,cpu_2m,cpu_1h,status,mono_ns
```

Parsed from `/proc/<pid>/stat`, `statm`, and `cmdline`. `creation_time` is derived
from `/proc/stat` `btime` plus the process `starttime`. `cpu_5s/2m/1h` are emitted
as `0.0` (interval CPU% needs historical sampling not collected on-device).

---

## 4. Filesystem Snapshots (`filesystem_snapshot`)

**Location:** `filesystem_snapshot/filesystem_snapshot_*.csv.zst` (only with `--fs-snapshot`)

### CSV Header

```csv
snapshot_timestamp,file_path,size,creation_time,modification_time,access_time,mono_ns
```

`creation_time` uses `st_ctime` (Android has no `st_birthtime`).

---

## 5. System Specification Files (`system_spec`)

JSON files capturing device hardware/software at trace start:

- **cpu_info.json** — model/SoC, core count, ABI
- **memory_info.json** — total/available RAM and swap
- **disk_info.json** — mounts, statvfs usage, `/sys/block` devices
- **os_info.json** — kernel + Android build/version/model from `getprop`

---

## Data Types and Conventions

- `timestamp`: `YYYY-MM-DD HH:MM:SS.ffffff`, local time derived from CLOCK_MONOTONIC.
- `mono_ns`: raw CLOCK_MONOTONIC nanoseconds; add `manifest.clock.mono_to_real_offset_ns` for wall-clock ns.
- Sizes in bytes; `sector` is in 512-byte units; `device` is `major:minor`.
- Empty string = field not captured for this event/platform.

## Reading Compressed Traces

```python
import csv, io, zstandard
with open("ds_*.csv.zst", "rb") as fh:
    text = io.TextIOWrapper(zstandard.ZstdDecompressor().stream_reader(fh), encoding="utf-8")
    for row in csv.DictReader(text):
        print(row["operation"], row["size"], row["latency_ms"])
```

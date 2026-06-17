"""
Central trace-schema definition — the single source of truth for the on-disk
format of the Android tracer. Both the CSV headers (written by WriteManager) and
the per-session ``manifest.json`` are derived from the tables here, so they can
never drift from each other or from this module.

This schema is intentionally kept **byte-for-byte compatible** with the Linux
io-tracer (``io-tracer-linux/src/tracer/schema.py``). The Android tracer collects
the same data via ftrace (``/sys/kernel/tracing``) and ``/proc`` rather than
eBPF/BCC, but emits the identical column layout so a single downstream parser can
read traces from either OS. Streams the Android collector does not yet populate
are still described here (so the cross-OS contract holds); their output
directories are simply created empty.

Every stream carries:
  * column 1 ``timestamp``  — wall-clock (CLOCK_REALTIME), ``YYYY-MM-DD HH:MM:SS.ffffff``
  * a trailing ``mono_ns``  — CLOCK_MONOTONIC nanoseconds, the common cross-stream
                              correlation clock. For ftrace event streams this is
                              the kernel ftrace timestamp captured with
                              ``trace_clock=mono``; for the userspace snapshot
                              streams it is ``time.monotonic_ns()``.

Bump ``SCHEMA_VERSION`` whenever a stream's columns change; consumers should read
it from ``manifest.json`` and adapt.
"""

# v1: original headerless CSVs, no manifest, per-stream clocks.
# v2: CSV headers + manifest.json + a common ``mono_ns`` column on every stream.
# v3: cross-OS aligned layout for ``fs`` and ``ds`` — a fixed shared column
#     prefix (identical names/order to the Windows/Linux tracers) followed by the
#     platform-specific extras, lowercase canonical operation names, ``size``
#     (not ``size_requested``), and a dedicated block ``flags`` column (rwbs
#     sub-flags split out of ``operation``).
SCHEMA_VERSION = 3


def _col(name, ctype, unit="", desc=""):
    return {"name": name, "type": ctype, "unit": unit, "description": desc}


# The trailing common-clock column appended to every stream.
_MONO_NS = _col(
    "mono_ns", "u64", "nanoseconds",
    "CLOCK_MONOTONIC timestamp of the record — the common clock for correlating "
    "across streams. Kernel ftrace timestamp (trace_clock=mono) for event streams; "
    "time.monotonic_ns() for snapshots.",
)


def _stream(subdir, prefix, description, clock, columns):
    return {
        "subdir": subdir,
        "filename_prefix": prefix,
        "description": description,
        # Clock backing the wall-clock ``timestamp`` column.
        "wall_clock": clock,
        "columns": columns + [_MONO_NS],
    }


# stream key -> definition. Keys match the output sub-directory names.
STREAMS = {
    "fs": _stream(
        "fs", "fs",
        "VFS / filesystem operation events. On Android these are derived from "
        "f2fs/ext4 read/write tracepoints (inode-keyed; filename best-effort).",
        "CLOCK_REALTIME (derived from kernel CLOCK_MONOTONIC)",
        [
            # --- shared cross-OS prefix (columns 1-12) --- #
            _col("timestamp", "datetime", "", "Event wall-clock time (YYYY-MM-DD HH:MM:SS.ffffff)."),
            _col("operation", "string", "", "Lowercase canonical op (read, write, open, close, fsync, ...)."),
            _col("pid", "u32"),
            _col("tid", "u32"),
            _col("command", "string", "", "Process name (<=16 chars)."),
            _col("filename", "string", "", "File path when resolvable; empty otherwise."),
            _col("size", "u64", "bytes", "Requested I/O size; empty for non-I/O ops."),
            _col("offset", "u64", "bytes", "File offset for positioned I/O; empty if 0."),
            _col("bytes_completed", "u64", "bytes", "Actual bytes moved by read/write; empty otherwise."),
            _col("inode", "u64", "", "File inode; empty if 0."),
            _col("device", "string", "", "Backing device major:minor; empty when unknown."),
            _col("flags", "string", "", "Operation-specific flags; empty when none."),
            # --- platform extras (columns 13+) --- #
            _col("duration_ns", "u64", "nanoseconds", "read/write entry->return duration; empty otherwise."),
            _col("return_value", "s64", "", "Raw read/write return (bytes or -errno); empty otherwise."),
            _col("errno", "string", "", "Error name when read/write failed; empty otherwise."),
            _col("mmap_prot", "string", "", "MMAP PROT_* flags; empty for non-MMAP."),
            _col("mmap_flags", "string", "", "MMAP MAP_* flags; empty for non-MMAP."),
            _col("address", "string", "", "Mapping address (hex) for MMAP/MUNMAP/MREMAP."),
            _col("cmdline", "string", "", "Full argv of the triggering process."),
            _col("ppid", "u32"),
            _col("container_id", "u64", "", "cgroup v2 id (container identifier)."),
            _col("fs_type", "string", "", "Source filesystem name (f2fs, ext4, ...)."),
        ],
    ),
    "ds": _stream(
        "ds", "ds",
        "Block-device (disk) I/O completion events. On Android these are paired "
        "from the ftrace block:block_rq_issue and block:block_rq_complete "
        "tracepoints to recover device latency.",
        "CLOCK_REALTIME (derived from kernel CLOCK_MONOTONIC)",
        [
            # --- shared cross-OS prefix (columns 1-10) --- #
            _col("timestamp", "datetime", "", "Completion wall-clock time."),
            _col("operation", "string", "", "Base block op (read, write, flush, discard, ...)."),
            _col("pid", "u32", "", "Submitting process ID."),
            _col("tid", "u32"),
            _col("command", "string"),
            _col("sector", "u64", "", "Starting sector (LBA, 512-byte units)."),
            _col("size", "u64", "bytes", "I/O size."),
            _col("latency_ms", "float", "milliseconds", "Device latency (issue->completion)."),
            _col("device", "string", "", "Device major:minor."),
            _col("flags", "string", "", "rwbs sub-flags (sync|meta|ahead|...); empty when none."),
            # --- platform extras (columns 11+) --- #
            _col("cpu_id", "u32", "", "CPU that processed completion."),
            _col("ppid", "u32"),
            _col("queue_latency_ms", "float", "milliseconds", "Scheduler latency (insert->issue)."),
            _col("command_flags", "string", "", "REQ_* flags; empty on kernel >=5.17."),
            _col("operation_code", "string", "", "Raw REQ_OP_* name; empty on kernel >=5.17."),
            _col("request_id", "u64", "", "Monotonic per-request id (this trace session)."),
        ],
    ),
    "cache": _stream(
        "cache", "cache",
        "Page-cache events (hit/miss/dirty/writeback/evict/...). Not collected by "
        "the Android tracer yet; directory is created empty for cross-OS parity.",
        "CLOCK_REALTIME (derived from kernel CLOCK_MONOTONIC)",
        [
            _col("timestamp", "datetime"),
            _col("pid", "u32"),
            _col("command", "string"),
            _col("event_type", "string", "", "Cache event type (HIT, MISS, DIRTY, ...)."),
            _col("inode", "u64"),
            _col("page_index", "u64", "", "Page offset within file (file offset / PAGE_SIZE)."),
            _col("size_pages", "u32", "pages", "File size in pages (i_size >> 12)."),
            _col("cpu_id", "u32"),
            _col("device_id", "u32"),
            _col("count", "u32", "pages", "Pages affected by the operation."),
        ],
    ),
    "pagefault": _stream(
        "pagefault", "pagefault",
        "File-backed page-fault events (mmap I/O). Not collected by the Android "
        "tracer yet; directory is created empty for cross-OS parity.",
        "CLOCK_REALTIME (derived from kernel CLOCK_MONOTONIC)",
        [
            _col("timestamp", "datetime"),
            _col("pid", "u32"),
            _col("tid", "u32"),
            _col("command", "string"),
            _col("fault_type", "string", "", "Access type that triggered the fault."),
            _col("severity", "string", "", "Fault severity (major/minor)."),
            _col("inode", "u64", "", "Backing file inode; empty for anonymous."),
            _col("offset_pages", "u64", "pages", "File offset in pages (pgoff)."),
            _col("address", "string", "", "Faulting virtual address (hex)."),
            _col("device_id", "u32"),
        ],
    ),
    "process": _stream(
        "process", "process",
        "Periodic process-state snapshots (userspace, parsed directly from /proc).",
        "CLOCK_REALTIME",
        [
            _col("timestamp", "datetime", "", "Snapshot wall-clock time."),
            _col("pid", "integer"),
            _col("name", "string"),
            _col("cmdline", "string", "", "Full command line (hashed in anonymous mode)."),
            _col("vms_kb", "float", "KB", "Virtual memory size."),
            _col("rss_kb", "float", "KB", "Resident set size."),
            _col("creation_time", "datetime", "", "Process start time."),
            _col("cpu_5s", "float", "percent", "CPU%% over last 5s."),
            _col("cpu_2m", "float", "percent", "CPU%% over last 2m."),
            _col("cpu_1h", "float", "percent", "CPU%% over last 1h."),
            _col("status", "string"),
        ],
    ),
    "filesystem_snapshot": _stream(
        "filesystem_snapshot", "filesystem_snapshot",
        "Filesystem inventory snapshot (userspace directory walk).",
        "CLOCK_REALTIME",
        [
            _col("snapshot_timestamp", "datetime", "", "Time the snapshot was taken."),
            _col("file_path", "string", "", "Full path (hashed in anonymous mode)."),
            _col("size", "integer", "bytes"),
            _col("creation_time", "datetime", "", "st_ctime (Android has no birthtime)."),
            _col("modification_time", "datetime", "", "st_mtime."),
            _col("access_time", "datetime", "", "st_atime."),
        ],
    ),
}


def column_names(stream_key):
    """Ordered list of column names for a stream."""
    return [c["name"] for c in STREAMS[stream_key]["columns"]]


def header_line(stream_key):
    """CSV header row (no trailing newline) for a stream."""
    return ",".join(column_names(stream_key))


def schema_for_manifest():
    """The static (runtime-independent) schema block for manifest.json."""
    return {
        "schema_version": SCHEMA_VERSION,
        "streams": {
            key: {
                "subdir": s["subdir"],
                "filename_prefix": s["filename_prefix"],
                "description": s["description"],
                "wall_clock": s["wall_clock"],
                "columns": s["columns"],
            }
            for key, s in STREAMS.items()
        },
    }

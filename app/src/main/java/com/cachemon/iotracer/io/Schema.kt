package com.cachemon.iotracer.io

/**
 * On-disk trace schema — the single source of truth for the app's CSV output.
 *
 * Kept in lock-step with the Python tracer's `src/tracer/schema.py`
 * (SCHEMA_VERSION 3): identical column names and order, so a trace captured by
 * this app is byte-for-byte parseable by the same downstream tooling as the CLI
 * and the Linux tracer. The only difference is the compression container
 * (`.csv.gz` here vs `.csv.zst` in the CLI); columns are unchanged.
 *
 * If you change a column here, change it in schema.py too and bump VERSION.
 */
object Schema {
    const val VERSION = 3

    val DS = listOf(
        "timestamp", "operation", "pid", "tid", "command", "sector", "size",
        "latency_ms", "device", "flags", "cpu_id", "ppid", "queue_latency_ms",
        "command_flags", "operation_code", "request_id", "mono_ns",
    )

    val PROCESS = listOf(
        "timestamp", "pid", "name", "cmdline", "vms_kb", "rss_kb",
        "creation_time", "cpu_5s", "cpu_2m", "cpu_1h", "status", "mono_ns",
    )

    fun header(columns: List<String>): String = columns.joinToString(",")
}

/** Minimal RFC-4180 CSV field/row encoding (matches Python's csv.writer output). */
object Csv {
    fun field(value: Any?): String {
        val s = value?.toString() ?: ""
        return if (s.any { it == ',' || it == '"' || it == '\n' || it == '\r' }) {
            "\"" + s.replace("\"", "\"\"") + "\""
        } else {
            s
        }
    }

    fun row(vararg values: Any?): String = values.joinToString(",") { field(it) }
}

package com.cachemon.iotracer.io

import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.util.zip.GZIPOutputStream

/**
 * Buffers trace rows per stream and rotates them into gzip-compressed CSV files,
 * plus a self-describing `manifest.json`. The on-disk layout mirrors the Python
 * tracer (only the compression container differs: `.csv.gz` vs `.csv.zst`).
 *
 *     <sessionDir>/
 *       manifest.json
 *       ds/ds_<ts>_<seq>.csv.gz
 *       process/process_<ts>_<seq>.csv.gz
 *       system_spec/ (cpu/memory/os .json files)
 */
class TraceWriter(
    val sessionDir: File,
    private val machineId: String,
    private val monoToRealOffsetNs: Long,
    private val flushThreshold: Int = 50_000,
) {
    private val buffers = mutableMapOf(
        "ds" to mutableListOf<String>(),
        "process" to mutableListOf<String>(),
    )
    private val headers = mapOf(
        "ds" to Schema.header(Schema.DS),
        "process" to Schema.header(Schema.PROCESS),
    )
    private val seq = mutableMapOf("ds" to 0, "process" to 0)
    val rowsWritten = mutableMapOf("ds" to 0L, "process" to 0L)
    val filesWritten = mutableMapOf("ds" to 0, "process" to 0)

    private val locks = mapOf("ds" to Any(), "process" to Any())

    init {
        File(sessionDir, "ds").mkdirs()
        File(sessionDir, "process").mkdirs()
        File(sessionDir, "system_spec").mkdirs()
    }

    /** Append a CSV row to a stream; auto-rotates the `ds` stream when full. */
    fun append(stream: String, row: String) {
        val lock = locks[stream] ?: return
        val full: Boolean
        synchronized(lock) {
            val buf = buffers.getValue(stream)
            buf.add(row)
            full = buf.size >= flushThreshold
        }
        if (full && stream == "ds") flush(stream)
    }

    fun flush(stream: String) {
        val lock = locks[stream] ?: return
        val rows: List<String>
        synchronized(lock) {
            val buf = buffers.getValue(stream)
            if (buf.isEmpty()) return
            rows = buf.toList()
            buf.clear()
            seq[stream] = seq.getValue(stream) + 1
        }
        val ts = TimeFmt.fileStamp()
        val name = "${stream}_${ts}_${"%04d".format(seq.getValue(stream))}.csv.gz"
        val file = File(File(sessionDir, stream), name)
        // Buffer the file stream so GZIP's compressed output is written in large
        // chunks rather than many small syscalls.
        GZIPOutputStream(FileOutputStream(file).buffered()).bufferedWriter(Charsets.UTF_8).use { w ->
            w.append(headers.getValue(stream)).append('\n')
            for (r in rows) {
                w.append(r); w.append('\n')
            }
        }
        rowsWritten[stream] = rowsWritten.getValue(stream) + rows.size
        filesWritten[stream] = filesWritten.getValue(stream) + 1
    }

    fun flushAll() {
        flush("ds")
        flush("process")
    }

    /** Write a JSON file directly into the system_spec subdirectory. */
    fun writeSpec(filename: String, content: String) {
        File(File(sessionDir, "system_spec"), filename).writeText(content)
    }

    fun writeManifest(extra: Map<String, Any?> = emptyMap()) {
        val streams = JSONObject()
        streams.put("ds", streamSpec("ds", Schema.DS, "Block-device I/O completions (ftrace block_rq_*)."))
        streams.put("process", streamSpec("process", Schema.PROCESS, "Periodic process snapshots (ps/proc)."))

        val clock = JSONObject()
            .put("mono_to_real_offset_ns", monoToRealOffsetNs)
            .put("note", "wall_clock_ns = mono_ns + mono_to_real_offset_ns")

        val manifest = JSONObject()
            .put("schema_version", Schema.VERSION)
            .put("platform", "android")
            .put("collector", "ftrace+proc (rooted app)")
            .put("compression", "gzip")
            .put("machine_id", machineId)
            .put("clock", clock)
            .put("rows_written", JSONObject(rowsWritten as Map<*, *>))
            .put("files_written", JSONObject(filesWritten as Map<*, *>))
            .put("streams", streams)
        for ((k, v) in extra) manifest.put(k, v)

        File(sessionDir, "manifest.json").writeText(manifest.toString(2))
    }

    private fun streamSpec(subdir: String, cols: List<String>, desc: String): JSONObject {
        val arr = JSONArray()
        cols.forEach { arr.put(it) }
        return JSONObject()
            .put("subdir", subdir)
            .put("filename_prefix", subdir)
            .put("description", desc)
            .put("columns", arr)
    }
}

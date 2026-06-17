package com.cachemon.iotracer.parse

/**
 * Correlate `block_rq_issue` with `block_rq_complete` to recover device latency.
 * Direct port of the Python `BlockPairer`.
 *
 * Keyed by (device, sector) — CPU is intentionally excluded because a request
 * may be issued on one CPU and completed via an interrupt on another. A
 * monotonic [requestId] assigned at issue keeps I/Os that reuse a (dev, sector)
 * pair distinguishable.
 */
class BlockPairer(
    // Cap on outstanding issues awaiting completion. Issues whose completion is
    // never seen (lost events, merges, re-keys) would otherwise accumulate
    // unbounded over a long trace; the oldest is evicted past this limit.
    private val maxInflight: Int = 100_000,
) {

    /** A completed block I/O, ready to be written as a `ds` row. */
    data class DsRow(
        val operation: String,
        val pid: Int?,            // null when the issue was not seen
        val tid: String,
        val command: String,
        val sector: Long,
        val size: Long,
        val latencyMs: Double?,   // null when unknown
        val device: String,
        val flags: String,
        val cpuId: Int,
        val ppid: String,
        val queueLatencyMs: String,
        val commandFlags: String,
        val operationCode: String,
        val requestId: Long?,     // null when the issue was not seen
        val monoNs: Long,
    )

    private data class Inflight(
        val issueMonoNs: Long,
        val pid: Int,
        val comm: String,
        val bytes: Long,
        val nsect: Long,
        val rwbs: String,
        val requestId: Long,
    )

    // LinkedHashMap preserves insertion order so the oldest entry is evicted first.
    private val inflight = LinkedHashMap<String, Inflight>()
    private var nextRequestId = 1L

    fun inflightCount(): Int = inflight.size

    private fun key(device: String, sector: Long) = "$device|$sector"

    fun onIssue(c: FtraceParser.Common) {
        val info = FtraceParser.parseIssue(c.body) ?: return
        inflight[key(info.device, info.sector)] = Inflight(
            issueMonoNs = c.monoNs,
            pid = c.pid,
            comm = c.comm,
            bytes = info.bytes,
            nsect = info.nsect,
            rwbs = info.rwbs,
            requestId = nextRequestId++,
        )
        // Bound memory: drop the oldest outstanding issue once over the cap.
        if (inflight.size > maxInflight) {
            val it = inflight.keys.iterator()
            if (it.hasNext()) {
                it.next()
                it.remove()
            }
        }
    }

    fun onComplete(c: FtraceParser.Common): DsRow? {
        val info = FtraceParser.parseComplete(c.body) ?: return null
        val issued = inflight.remove(key(info.device, info.sector))

        val rwbs = issued?.rwbs?.takeIf { it.isNotEmpty() } ?: info.rwbs
        val (operation, flags) = FtraceParser.decodeRwbs(rwbs)

        return if (issued != null) {
            val latency = (c.monoNs - issued.issueMonoNs) / 1e6
            DsRow(
                operation = operation,
                pid = issued.pid,
                tid = "",
                command = issued.comm.take(16),
                sector = info.sector,
                size = if (issued.bytes != 0L) issued.bytes else issued.nsect * 512,
                latencyMs = Math.round(latency * 1000.0) / 1000.0,
                device = info.device,
                flags = flags,
                cpuId = c.cpu,
                ppid = "",
                queueLatencyMs = "",
                commandFlags = "",
                operationCode = "",
                requestId = issued.requestId,
                monoNs = c.monoNs,
            )
        } else {
            // Completion with no recorded issue (started before tracing began).
            DsRow(
                operation = operation,
                pid = null,
                tid = "",
                command = c.comm.take(16),
                sector = info.sector,
                size = info.nsect * 512,
                latencyMs = null,
                device = info.device,
                flags = flags,
                cpuId = c.cpu,
                ppid = "",
                queueLatencyMs = "",
                commandFlags = "",
                operationCode = "",
                requestId = null,
                monoNs = c.monoNs,
            )
        }
    }
}

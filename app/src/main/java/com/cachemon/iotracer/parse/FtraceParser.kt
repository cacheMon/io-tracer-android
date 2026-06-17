package com.cachemon.iotracer.parse

import kotlin.math.roundToLong

/**
 * Pure parsing of ftrace `trace_pipe` lines — a direct port of the Python
 * tracer's `parsers.py`. No Android dependencies, so it is unit-testable on the
 * JVM.
 *
 * Common line format:
 *
 *     <comm>-<pid> [<cpu>] <flags> <timestamp>: <event>: <body>
 */
object FtraceParser {

    /** Parsed ftrace common header. */
    data class Common(
        val comm: String,
        val pid: Int,
        val cpu: Int,
        val event: String,
        val monoNs: Long,
        val body: String,
    )

    // comm may contain dashes/slashes/colons, so the pid is anchored as the
    // digit run immediately preceding the " [cpu]" field.
    private val LINE = Regex(
        """^\s*(.+?)-(\d+)\s+\[(\d+)]\s+(\S+)\s+(\d+\.\d+):\s+([\w:]+):\s*(.*)$"""
    )

    fun parseCommon(line: String): Common? {
        val m = LINE.matchEntire(line) ?: return null
        val (comm, pid, cpu, _flags, ts, event, body) = m.destructured
        val monoNs = (ts.toDouble() * 1e9).roundToLong()
        return Common(comm, pid.toInt(), cpu.toInt(), event, monoNs, body)
    }

    // --- rwbs decoding ----------------------------------------------------- //

    private val RWBS_OP = mapOf(
        'R' to "read", 'W' to "write", 'D' to "discard",
        'E' to "secure_erase", 'F' to "flush", 'N' to "none",
    )
    private val RWBS_FLAG = mapOf(
        'S' to "sync", 'M' to "meta", 'A' to "ahead",
        'P' to "prio", 'B' to "barrier", 'F' to "fua",
    )

    /** Decode an rwbs string into (baseOperation, flagsJoined). */
    fun decodeRwbs(rwbs: String): Pair<String, String> {
        if (rwbs.isEmpty()) return "" to ""
        val op = RWBS_OP[rwbs[0]] ?: ""
        val flags = rwbs.drop(1).mapNotNull { RWBS_FLAG[it] }.joinToString("|")
        return op to flags
    }

    // --- block_rq_issue / block_rq_complete bodies ------------------------- //

    data class Issue(
        val device: String, val rwbs: String, val bytes: Long,
        val sector: Long, val nsect: Long,
    )

    data class Complete(
        val device: String, val rwbs: String,
        val sector: Long, val nsect: Long, val errno: Int,
    )

    // "8,0 W 8192 () 779 + 16 [comm]"
    private val ISSUE = Regex(
        """^(\d+,\d+)\s+(\S+)\s+(\d+)\s+\(.*?\)\s+(\d+)\s+\+\s+(\d+)"""
    )
    // "8,0 W () 779 + 16 [0]"
    private val COMPLETE = Regex(
        """^(\d+,\d+)\s+(\S+)\s+\(.*?\)\s+(\d+)\s+\+\s+(\d+)\s+\[(-?\d+)]"""
    )

    private fun devToMajMin(dev: String) = dev.replace(",", ":")

    fun parseIssue(body: String): Issue? {
        // parseCommon already strips leading space before `body`, and trailing
        // space doesn't affect find(), so no trim() allocation is needed.
        val m = ISSUE.find(body) ?: return null
        val (dev, rwbs, bytes, sector, nsect) = m.destructured
        return Issue(devToMajMin(dev), rwbs, bytes.toLong(), sector.toLong(), nsect.toLong())
    }

    fun parseComplete(body: String): Complete? {
        val m = COMPLETE.find(body) ?: return null
        val (dev, rwbs, sector, nsect, err) = m.destructured
        return Complete(devToMajMin(dev), rwbs, sector.toLong(), nsect.toLong(), err.toInt())
    }
}

package com.cachemon.iotracer

import com.cachemon.iotracer.parse.BlockPairer
import com.cachemon.iotracer.parse.FtraceParser
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** JVM unit tests mirroring the Python tracer's test_parsers.py. */
class FtraceParserTest {

    @Test
    fun parsesCommonHeader() {
        val line = "           <...>-1234  [002] d..1 1234.567890: " +
            "block_rq_issue: 8,0 W 8192 () 779 + 16 [kworker/2:1]"
        val c = FtraceParser.parseCommon(line)!!
        assertEquals(1234, c.pid)
        assertEquals(2, c.cpu)
        assertEquals("block_rq_issue", c.event)
        assertEquals(1234567890000L, c.monoNs)
        assertTrue(c.body.startsWith("8,0 W 8192"))
    }

    @Test
    fun parsesCommWithDashesAndSlashes() {
        val line = "kworker/2:1-1234  [002] .... 100.000001: block_rq_complete: 8,0 R () 5 + 8 [0]"
        val c = FtraceParser.parseCommon(line)!!
        assertEquals("kworker/2:1", c.comm)
        assertEquals(1234, c.pid)
    }

    @Test
    fun rejectsJunk() {
        assertNull(FtraceParser.parseCommon("not an ftrace line"))
        assertNull(FtraceParser.parseCommon(""))
    }

    @Test
    fun decodesRwbs() {
        assertEquals("read" to "", FtraceParser.decodeRwbs("R"))
        assertEquals("write" to "sync", FtraceParser.decodeRwbs("WS"))
        assertEquals("read" to "meta", FtraceParser.decodeRwbs("RM"))
        assertEquals("write" to "meta|ahead", FtraceParser.decodeRwbs("WMA"))
        assertEquals("discard" to "", FtraceParser.decodeRwbs("D"))
        assertEquals("" to "", FtraceParser.decodeRwbs(""))
    }

    @Test
    fun parsesIssueAndComplete() {
        val issue = FtraceParser.parseIssue("8,0 W 8192 () 779 + 16 [kworker/2:1]")!!
        assertEquals("8:0", issue.device)
        assertEquals(8192L, issue.bytes)
        assertEquals(779L, issue.sector)
        assertEquals(16L, issue.nsect)
        val comp = FtraceParser.parseComplete("8,0 W () 779 + 16 [0]")!!
        assertEquals("8:0", comp.device)
        assertEquals(779L, comp.sector)
        assertEquals(0, comp.errno)
    }

    @Test
    fun pairerMatchesAndComputesLatency() {
        val pairer = BlockPairer()
        pairer.onIssue(FtraceParser.parseCommon(
            "app-100 [001] .... 10.000000: block_rq_issue: 259,0 WS 4096 () 2048 + 8 [app]")!!)
        assertEquals(1, pairer.inflightCount())
        val row = pairer.onComplete(FtraceParser.parseCommon(
            "swapper-0 [003] d.h. 10.002000: block_rq_complete: 259,0 WS () 2048 + 8 [0]")!!)!!
        assertEquals(0, pairer.inflightCount())
        assertEquals("write", row.operation)
        assertEquals("sync", row.flags)
        assertEquals(100, row.pid)            // submitter from issue
        assertEquals("app", row.command)
        assertEquals(4096L, row.size)
        assertEquals("259:0", row.device)
        assertEquals(2048L, row.sector)
        assertEquals(2.0, row.latencyMs!!, 1e-6)
        assertEquals(3, row.cpuId)            // completion CPU
        assertEquals(1L, row.requestId)
    }

    @Test
    fun pairerHandlesCompleteWithoutIssue() {
        val pairer = BlockPairer()
        val row = pairer.onComplete(FtraceParser.parseCommon(
            "x-1 [000] .... 5.0: block_rq_complete: 8,0 R () 99 + 8 [0]")!!)!!
        assertNull(row.latencyMs)
        assertNull(row.pid)
        assertEquals(8L * 512, row.size)
        assertEquals("read", row.operation)
        assertNull(row.requestId)
    }

    @Test
    fun pairerDistinguishesReusedSector() {
        val pairer = BlockPairer()
        pairer.onIssue(FtraceParser.parseCommon(
            "a-1 [0] .... 1.0: block_rq_issue: 8,0 R 512 () 10 + 1 [a]")!!)
        val r1 = pairer.onComplete(FtraceParser.parseCommon(
            "a-1 [0] .... 1.001: block_rq_complete: 8,0 R () 10 + 1 [0]")!!)!!
        pairer.onIssue(FtraceParser.parseCommon(
            "b-2 [0] .... 2.0: block_rq_issue: 8,0 R 512 () 10 + 1 [b]")!!)
        val r2 = pairer.onComplete(FtraceParser.parseCommon(
            "b-2 [0] .... 2.001: block_rq_complete: 8,0 R () 10 + 1 [0]")!!)!!
        assertEquals(1L, r1.requestId)
        assertEquals(2L, r2.requestId)
        assertEquals(1, r1.pid)
        assertEquals(2, r2.pid)
    }

    @Test
    fun pairerEvictsOldestPastCap() {
        val pairer = BlockPairer(maxInflight = 2)
        pairer.onIssue(FtraceParser.parseCommon(
            "a-1 [0] .... 1.0: block_rq_issue: 8,0 R 512 () 10 + 1 [a]")!!)
        pairer.onIssue(FtraceParser.parseCommon(
            "b-2 [0] .... 1.1: block_rq_issue: 8,0 R 512 () 20 + 1 [b]")!!)
        // Third issue evicts the oldest (sector 10).
        pairer.onIssue(FtraceParser.parseCommon(
            "c-3 [0] .... 1.2: block_rq_issue: 8,0 R 512 () 30 + 1 [c]")!!)
        assertEquals(2, pairer.inflightCount())

        // Completion for the evicted sector 10 is unmatched (no latency / pid).
        val r10 = pairer.onComplete(FtraceParser.parseCommon(
            "x-9 [0] .... 1.3: block_rq_complete: 8,0 R () 10 + 1 [0]")!!)!!
        assertNull(r10.latencyMs)
        assertNull(r10.pid)

        // Sector 30 is still tracked, so it pairs normally.
        val r30 = pairer.onComplete(FtraceParser.parseCommon(
            "x-9 [0] .... 1.4: block_rq_complete: 8,0 R () 30 + 1 [0]")!!)!!
        assertEquals(3, r30.pid)
        assertNotNull(r30.latencyMs)
    }
}

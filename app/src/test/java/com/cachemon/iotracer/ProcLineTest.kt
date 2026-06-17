package com.cachemon.iotracer

import com.cachemon.iotracer.snap.ProcSnapper
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** Unit tests for the pure `ps` line parser used by ProcSnapper. */
class ProcLineTest {

    // process columns: timestamp,pid,name,cmdline,vms_kb,rss_kb,creation_time,
    // cpu_5s,cpu_2m,cpu_1h,status,mono_ns
    @Test
    fun parsesPsLine() {
        val row = ProcSnapper.parsePsLine(
            "123 1 4096 8192 S com.example.app", "2026-01-01 00:00:00.000000", 555L, false)!!
        val f = row.split(",")
        assertEquals("123", f[1])             // pid
        assertEquals("com.example.app", f[2]) // name
        assertEquals("8192.0", f[4])          // vms_kb = VSZ
        assertEquals("4096.0", f[5])          // rss_kb = RSS
        assertEquals("S", f[10])              // status
        assertEquals("555", f[11])            // mono_ns
    }

    @Test
    fun rejectsShortAndHeaderLines() {
        assertNull(ProcSnapper.parsePsLine("too few cols", "t", 0L, false))
        // Header row: PID column isn't numeric.
        assertNull(ProcSnapper.parsePsLine("PID PPID RSS VSZ S NAME", "t", 0L, false))
    }

    @Test
    fun anonymizesName() {
        val row = ProcSnapper.parsePsLine(
            "123 1 4096 8192 S com.example.app", "t", 0L, true)!!
        val name = row.split(",")[2]
        assertEquals(12, name.length)               // 12-char hash
        assertNotEquals("com.example.app", name)
    }
}

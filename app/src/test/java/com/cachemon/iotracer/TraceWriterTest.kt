package com.cachemon.iotracer

import com.cachemon.iotracer.io.Schema
import com.cachemon.iotracer.io.TraceWriter
import org.junit.Assert.assertEquals
import org.junit.Test
import java.io.File
import java.io.FileInputStream
import java.nio.file.Files
import java.util.zip.GZIPInputStream

/**
 * Exercises the gzip CSV output path (no org.json / manifest, so it runs under
 * plain JVM unit tests). Mirrors the Python tracer's writer tests.
 */
class TraceWriterTest {

    private fun tempDir(): File = Files.createTempDirectory("tw").toFile()

    private fun readGz(file: File): List<String> =
        GZIPInputStream(FileInputStream(file)).bufferedReader(Charsets.UTF_8).readLines()

    @Test
    fun rotatesDsOnThresholdWithHeader() {
        val dir = tempDir()
        val wm = TraceWriter(dir, "MID", 0L, flushThreshold = 2)
        wm.append("ds", "row-a")
        wm.append("ds", "row-b") // reaching the threshold auto-rotates the ds stream
        val files = File(dir, "ds").listFiles { f -> f.name.endsWith(".csv.gz") }!!
        assertEquals(1, files.size)
        val lines = readGz(files[0])
        assertEquals(Schema.header(Schema.DS), lines[0])
        assertEquals(listOf("row-a", "row-b"), lines.drop(1))
        assertEquals(2L, wm.rowsWritten["ds"])
        assertEquals(1, wm.filesWritten["ds"])
    }

    @Test
    fun snapshotStreamFlushesOnlyOnDemand() {
        val dir = tempDir()
        val wm = TraceWriter(dir, "MID", 0L, flushThreshold = 2)
        // Snapshot streams do not auto-rotate; nothing is written until flush().
        wm.append("process", "p1")
        wm.append("process", "p2")
        wm.append("process", "p3")
        assertEquals(0, File(dir, "process").listFiles { f -> f.name.endsWith(".csv.gz") }!!.size)
        wm.flush("process")
        val files = File(dir, "process").listFiles { f -> f.name.endsWith(".csv.gz") }!!
        assertEquals(1, files.size)
        val lines = readGz(files[0])
        assertEquals(Schema.header(Schema.PROCESS), lines[0])
        assertEquals(3, lines.size - 1)
    }
}

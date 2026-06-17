package com.cachemon.iotracer

import com.cachemon.iotracer.ftrace.FtraceControl
import com.cachemon.iotracer.io.TraceWriter
import com.cachemon.iotracer.parse.BlockPairer
import com.cachemon.iotracer.parse.FtraceParser
import com.cachemon.iotracer.root.RootShell
import com.cachemon.iotracer.snap.ProcSnapper
import com.cachemon.iotracer.snap.SystemSnapper
import com.cachemon.iotracer.snap.simpleHash
import java.io.BufferedReader
import java.io.File
import java.io.InputStreamReader
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

/**
 * Owns one tracing session: streams block events from ftrace via root, pairs
 * them into `ds` rows, runs periodic process/system snapshots, and writes the
 * gzip CSV streams + manifest. Lifecycle is driven by [TracerService].
 *
 * @param onProgress invoked (on background threads) after counters change so the
 *        service can refresh its notification.
 */
class TraceEngine(
    private val outputRoot: File,
    private val machineId: String,
    private val anonymous: Boolean,
    private val processIntervalSec: Int,
    private val onProgress: (TraceStatus) -> Unit,
) {
    private val root = RootShell()
    private val active = AtomicBoolean(false)
    private val pairer = BlockPairer()

    private var streamProc: Process? = null
    private var readerThread: Thread? = null
    private var snapshotThread: Thread? = null
    private lateinit var writer: TraceWriter

    @Volatile private var dsRows = 0L
    @Volatile private var linesSeen = 0L
    @Volatile private var processRows = 0L

    val sessionDir: File get() = writer.sessionDir

    fun start() {
        active.set(true)
        val sessionName = "android_trace_${machineId}_${stamp()}"
        val dir = File(outputRoot, sessionName).apply { mkdirs() }
        writer = TraceWriter(dir, machineId, realOffset)

        emit("Session: ${dir.absolutePath}")

        // System spec once.
        runCatching { SystemSnapper(root, writer).capture() }

        // Periodic process snapshots.
        val procSnapper = ProcSnapper(root, writer, anonymous)
        snapshotThread = thread(name = "iotracer-snap", isDaemon = true) {
            while (active.get()) {
                runCatching {
                    processRows += procSnapper.takeSnapshot().toLong()
                    emit("Process snapshot captured")
                }
                var slept = 0
                while (active.get() && slept < processIntervalSec) {
                    Thread.sleep(1000); slept++
                }
            }
        }

        // ftrace block stream.
        if (FtraceControl.blockEventsPresent(root)) {
            val proc = root.stream(FtraceControl.streamScript())
            streamProc = proc
            readerThread = thread(name = "iotracer-ftrace", isDaemon = true) {
                runCatching {
                    BufferedReader(InputStreamReader(proc.inputStream)).use { r ->
                        while (active.get()) {
                            val line = r.readLine() ?: break
                            handleLine(line)
                        }
                    }
                }
            }
            emit("Tracing block I/O…")
        } else {
            emit("Block tracepoints unavailable; running snapshot-only.")
        }
    }

    private fun handleLine(line: String) {
        linesSeen++
        val common = FtraceParser.parseCommon(line) ?: return
        when (common.event) {
            "block_rq_issue" -> pairer.onIssue(common)
            "block_rq_complete" -> {
                val row = pairer.onComplete(common) ?: return
                val command = if (anonymous) simpleHash(row.command) else row.command
                val ts = monoToWall(row.monoNs)
                writer.append("ds", com.cachemon.iotracer.io.Csv.row(
                    ts, row.operation, row.pid, row.tid, command, row.sector,
                    row.size, row.latencyMs, row.device, row.flags, row.cpuId,
                    row.ppid, row.queueLatencyMs, row.commandFlags,
                    row.operationCode, row.requestId, row.monoNs,
                ))
                dsRows++
                if (dsRows % 1000L == 0L) emit("ds rows: $dsRows")
            }
        }
    }

    fun stop() {
        active.set(false)
        runCatching { root.exec(FtraceControl.teardownScript()) }
        runCatching { streamProc?.destroy() }
        runCatching { readerThread?.join(2000) }
        runCatching { snapshotThread?.join(2000) }
        runCatching {
            writer.flushAll()
            writer.writeManifest(
                mapOf(
                    "lines_seen" to linesSeen,
                    "block_inflight_unmatched" to pairer.inflightCount(),
                )
            )
        }
        emit("Stopped. Saved to ${writer.sessionDir.absolutePath}")
    }

    private fun emit(msg: String) {
        onProgress(
            TraceStatus(
                running = active.get(),
                rootAvailable = true,
                dsRows = dsRows,
                linesSeen = linesSeen,
                processRows = processRows,
                sessionDir = if (::writer.isInitialized) writer.sessionDir.absolutePath else null,
                lastMessage = msg,
            )
        )
    }

    private val realOffset: Long = System.currentTimeMillis() * 1_000_000L - System.nanoTime()
    private fun monoToWall(monoNs: Long): String {
        // Reuses a thread-local formatter (see TimeFmt) — this runs once per block
        // I/O completion, which can be thousands per second.
        val realNs = monoNs + realOffset
        return com.cachemon.iotracer.io.TimeFmt.wallMillis(realNs / 1_000_000L)
    }

    private fun stamp(): String = com.cachemon.iotracer.io.TimeFmt.sessionStamp()

    companion object {
        fun checkRoot(): Boolean = RootShell().available()
    }
}

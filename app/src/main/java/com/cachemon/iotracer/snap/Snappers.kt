package com.cachemon.iotracer.snap

import com.cachemon.iotracer.io.Csv
import com.cachemon.iotracer.io.TraceWriter
import com.cachemon.iotracer.root.RootShell
import org.json.JSONObject
import java.security.MessageDigest

/** Hash helper for anonymization (matches the Python simple_hash). */
fun simpleHash(s: String, length: Int = 12): String {
    val d = MessageDigest.getInstance("SHA-256").digest(s.toByteArray())
    return d.joinToString("") { "%02x".format(it) }.take(length)
}

/**
 * Periodic process snapshot using toybox `ps` (run as root so every process is
 * visible despite hidepid). Emits the `process` schema; CPU-interval and
 * creation-time columns are placeholders, matching the CLI's on-device limits.
 */
class ProcSnapper(
    private val root: RootShell,
    private val writer: TraceWriter,
    private val anonymous: Boolean,
) {
    fun takeSnapshot(): Int {
        val ts = wallNow()
        val monoNs = System.nanoTime()
        val (code, out) = root.exec("ps -A -o PID,PPID,RSS,VSZ,S,NAME 2>/dev/null")
        if (code != 0) return 0
        var count = 0
        val lines = out.lineSequence().toList()
        for (line in lines.drop(1)) { // drop header
            val cols = line.trim().split(Regex("\\s+"))
            if (cols.size < 6) continue
            val pid = cols[0].toIntOrNull() ?: continue
            val rssKb = cols[2].toDoubleOrNull() ?: 0.0
            val vszKb = cols[3].toDoubleOrNull() ?: 0.0
            val status = cols[4]
            var name = cols.subList(5, cols.size).joinToString(" ")
            if (anonymous) name = simpleHash(name)
            writer.append("process", Csv.row(
                ts, pid, name, name, vszKb, rssKb, "", 0.0, 0.0, 0.0, status, monoNs,
            ))
            count++
        }
        writer.flush("process")
        return count
    }

    private fun wallNow(): String =
        com.cachemon.iotracer.io.TimeFmt.wall(java.util.Date())
}

/** Captures device hardware and software specs as JSON in the system_spec dir. */
class SystemSnapper(
    private val root: RootShell,
    private val writer: TraceWriter,
) {
    fun capture() {
        val props = getprops()
        val cpu = JSONObject()
            .put("brand", readProcField("/proc/cpuinfo", listOf("Hardware", "Processor", "model name"))
                .ifEmpty { props["ro.board.platform"] ?: "" })
            .put("soc_manufacturer", props["ro.soc.manufacturer"] ?: "")
            .put("soc_model", props["ro.soc.model"] ?: "")
            .put("cores_logical", Runtime.getRuntime().availableProcessors())
            .put("abi", props["ro.product.cpu.abi"] ?: "")
        writer.writeSpec("cpu_info.json", cpu.toString(2))

        val mem = meminfo()
        writer.writeSpec("memory_info.json", JSONObject()
            .put("total_bytes", (mem["MemTotal"] ?: 0L) * 1024)
            .put("available_bytes", (mem["MemAvailable"] ?: 0L) * 1024)
            .put("swap_total_bytes", (mem["SwapTotal"] ?: 0L) * 1024)
            .toString(2))

        writer.writeSpec("os_info.json", JSONObject()
            .put("system", "Android")
            .put("kernel", readFirstLine("/proc/version"))
            .put("android_release", props["ro.build.version.release"] ?: "")
            .put("android_sdk", props["ro.build.version.sdk"] ?: "")
            .put("build_fingerprint", props["ro.build.fingerprint"] ?: "")
            .put("manufacturer", props["ro.product.manufacturer"] ?: "")
            .put("model", props["ro.product.model"] ?: "")
            .put("device", props["ro.product.device"] ?: "")
            .toString(2))
    }

    private fun getprops(): Map<String, String> {
        val (code, out) = root.exec("getprop")
        if (code != 0) return emptyMap()
        val map = HashMap<String, String>()
        for (line in out.lineSequence()) {
            if (line.startsWith("[") && line.contains("]: [")) {
                val k = line.substringAfter("[").substringBefore("]")
                val v = line.substringAfter("]: [").substringBeforeLast("]")
                map[k] = v
            }
        }
        return map
    }

    private fun meminfo(): Map<String, Long> {
        val map = HashMap<String, Long>()
        runCatching {
            java.io.File("/proc/meminfo").forEachLine { line ->
                val parts = line.split(Regex(":\\s+"))
                if (parts.size >= 2) {
                    val num = parts[1].trim().split(" ").firstOrNull()?.toLongOrNull()
                    if (num != null) map[parts[0]] = num
                }
            }
        }
        return map
    }

    private fun readProcField(path: String, keys: List<String>): String {
        // useLines (unlike forEachLine) is inline, so the non-local return is legal.
        runCatching {
            java.io.File(path).useLines { seq ->
                for (line in seq) {
                    for (k in keys) if (line.startsWith(k) && line.contains(":")) {
                        return line.substringAfter(":").trim()
                    }
                }
            }
        }
        return ""
    }

    private fun readFirstLine(path: String): String =
        runCatching { java.io.File(path).readLines().firstOrNull() ?: "" }.getOrDefault("")
}

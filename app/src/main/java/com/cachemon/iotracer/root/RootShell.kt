package com.cachemon.iotracer.root

import java.io.BufferedReader
import java.io.InputStreamReader

/**
 * Thin wrapper around the device `su` binary (Magisk / standard root).
 *
 * Two modes:
 *  - [available]/[exec] run a one-shot command and wait.
 *  - [stream] starts a long-lived `su` process (e.g. `cat trace_pipe`) whose
 *    stdout the caller reads line by line; [destroy] it to stop.
 */
class RootShell {

    /** True if a root shell can be obtained (uid 0). */
    fun available(): Boolean = try {
        val p = ProcessBuilder("su", "-c", "id -u")
            .redirectErrorStream(true)
            .start()
        val out = BufferedReader(InputStreamReader(p.inputStream)).readText().trim()
        p.waitFor()
        out.lineSequence().any { it.trim() == "0" }
    } catch (e: Exception) {
        false
    }

    /** Run [script] as root, returning (exitCode, combinedOutput). */
    fun exec(script: String): Pair<Int, String> = try {
        val p = ProcessBuilder("su", "-c", script)
            .redirectErrorStream(true)
            .start()
        val out = BufferedReader(InputStreamReader(p.inputStream)).readText()
        val code = p.waitFor()
        code to out
    } catch (e: Exception) {
        -1 to (e.message ?: "su failed")
    }

    /** Start a streaming root command; caller reads stdout and later [destroy]s it. */
    fun stream(script: String): Process =
        ProcessBuilder("su", "-c", script).start()
}

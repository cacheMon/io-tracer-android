package com.cachemon.iotracer.ftrace

import com.cachemon.iotracer.root.RootShell

/**
 * Builds the root shell scripts that configure tracefs and stream block events.
 *
 * Tracefs is normally at /sys/kernel/tracing (older devices use the debugfs
 * path). The scripts resolve it at runtime so a single build works on both.
 */
object FtraceControl {

    private const val RESOLVE =
        "T=/sys/kernel/tracing; [ -d \$T ] || T=/sys/kernel/debug/tracing; "

    /** Script that enables block tracepoints (mono clock) and streams trace_pipe. */
    fun streamScript(): String = RESOLVE + buildString {
        append("echo mono > \$T/trace_clock 2>/dev/null; ")
        append("echo 0 > \$T/tracing_on 2>/dev/null; ")
        append("echo > \$T/trace 2>/dev/null; ")
        append("echo 1 > \$T/events/block/block_rq_issue/enable 2>/dev/null; ")
        append("echo 1 > \$T/events/block/block_rq_complete/enable 2>/dev/null; ")
        append("echo 1 > \$T/tracing_on 2>/dev/null; ")
        append("cat \$T/trace_pipe")
    }

    /** Script that disables the block tracepoints and restores the clock. */
    fun teardownScript(): String = RESOLVE + buildString {
        append("echo 0 > \$T/events/block/block_rq_issue/enable 2>/dev/null; ")
        append("echo 0 > \$T/events/block/block_rq_complete/enable 2>/dev/null; ")
        append("echo 0 > \$T/tracing_on 2>/dev/null; ")
        append("echo local > \$T/trace_clock 2>/dev/null; ")
        append("true")
    }

    /** Best-effort check that block tracepoints exist on this kernel. */
    fun blockEventsPresent(root: RootShell): Boolean {
        val (code, out) = root.exec(
            RESOLVE + "ls \$T/events/block/block_rq_complete/enable 2>/dev/null"
        )
        return code == 0 && out.contains("enable")
    }
}

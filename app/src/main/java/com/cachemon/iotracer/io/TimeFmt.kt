package com.cachemon.iotracer.io

import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Thread-local [SimpleDateFormat] instances. SimpleDateFormat is not thread-safe
 * and allocating one per event is wasteful on the hot tracing path, so each
 * thread reuses its own formatter.
 */
object TimeFmt {
    private val wall = ThreadLocal.withInitial {
        SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS", Locale.US)
    }
    private val fileStampFmt = ThreadLocal.withInitial {
        SimpleDateFormat("yyyyMMdd_HHmmss_SSS", Locale.US)
    }
    private val sessionStampFmt = ThreadLocal.withInitial {
        SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US)
    }

    /** Wall-clock string padded to the schema's microsecond shape (trailing 000). */
    fun wall(date: Date): String = wall.get()!!.format(date) + "000"

    fun wallMillis(epochMillis: Long): String = wall(Date(epochMillis))

    fun fileStamp(): String = fileStampFmt.get()!!.format(Date())

    fun sessionStamp(): String = sessionStampFmt.get()!!.format(Date())
}

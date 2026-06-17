package com.cachemon.iotracer

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import android.provider.Settings
import java.io.File
import java.security.MessageDigest
import kotlin.concurrent.thread

/**
 * Foreground service that owns a [TraceEngine] for the lifetime of a tracing
 * session. Started/stopped from the UI via [ACTION_START]/[ACTION_STOP]; keeps a
 * persistent notification so collection survives the screen turning off.
 */
class TracerService : Service() {

    private var engine: TraceEngine? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> startTracing(intent)
            ACTION_STOP -> stopTracing()
        }
        return START_NOT_STICKY
    }

    private fun startTracing(intent: Intent) {
        if (engine != null) return
        createChannel()
        startForeground(NOTIF_ID, buildNotification("Starting…"))

        val anonymous = intent.getBooleanExtra(EXTRA_ANON, false)
        val interval = intent.getIntExtra(EXTRA_INTERVAL, 300)
        val outDir = File(getExternalFilesDir(null), "traces").apply { mkdirs() }
        val machineId = machineId()

        TracerState.update { it.copy(running = true, lastMessage = "Starting…") }

        // Engine start touches `su`, so run it off the main thread.
        thread(name = "iotracer-start", isDaemon = true) {
            val e = TraceEngine(
                outputRoot = outDir,
                machineId = machineId,
                anonymous = anonymous,
                processIntervalSec = interval,
                onProgress = { status ->
                    TracerState.update { status }
                    updateNotification(status.lastMessage)
                },
            )
            engine = e
            runCatching { e.start() }.onFailure {
                TracerState.update { s -> s.copy(running = false, lastMessage = "Error: ${it.message}") }
                stopSelf()
            }
        }
    }

    private fun stopTracing() {
        val e = engine
        engine = null
        thread(name = "iotracer-stop", isDaemon = true) {
            runCatching { e?.stop() }
            TracerState.update { it.copy(running = false) }
            stopForegroundCompat()
            stopSelf()
        }
    }

    override fun onDestroy() {
        engine?.let { e -> runCatching { e.stop() } }
        engine = null
        super.onDestroy()
    }

    // --- notification ---------------------------------------------------- //

    private fun createChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val mgr = getSystemService(NotificationManager::class.java)
            if (mgr.getNotificationChannel(CHANNEL_ID) == null) {
                mgr.createNotificationChannel(
                    NotificationChannel(
                        CHANNEL_ID, "I/O Tracing", NotificationManager.IMPORTANCE_LOW
                    )
                )
            }
        }
    }

    private fun buildNotification(text: String): Notification {
        val builder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(this, CHANNEL_ID)
        } else {
            @Suppress("DEPRECATION") Notification.Builder(this)
        }
        return builder
            .setContentTitle("IO Tracer")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.stat_sys_download)
            .setOngoing(true)
            .build()
    }

    private fun updateNotification(text: String) {
        val mgr = getSystemService(NotificationManager::class.java)
        mgr.notify(NOTIF_ID, buildNotification(text))
    }

    private fun stopForegroundCompat() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            stopForeground(STOP_FOREGROUND_REMOVE)
        } else {
            @Suppress("DEPRECATION") stopForeground(true)
        }
    }

    private fun machineId(): String {
        val androidId = Settings.Secure.getString(contentResolver, Settings.Secure.ANDROID_ID) ?: "unknown"
        val d = MessageDigest.getInstance("SHA-256").digest(androidId.toByteArray())
        return d.joinToString("") { "%02x".format(it) }.take(16).uppercase()
    }

    companion object {
        const val ACTION_START = "com.cachemon.iotracer.START"
        const val ACTION_STOP = "com.cachemon.iotracer.STOP"
        const val EXTRA_ANON = "anonymous"
        const val EXTRA_INTERVAL = "interval"
        private const val CHANNEL_ID = "io_tracing"
        private const val NOTIF_ID = 1001

        fun start(ctx: Context, anonymous: Boolean, intervalSec: Int) {
            val i = Intent(ctx, TracerService::class.java).apply {
                action = ACTION_START
                putExtra(EXTRA_ANON, anonymous)
                putExtra(EXTRA_INTERVAL, intervalSec)
            }
            ctx.startForegroundService(i)
        }

        fun stop(ctx: Context) {
            ctx.startService(Intent(ctx, TracerService::class.java).apply { action = ACTION_STOP })
        }
    }
}

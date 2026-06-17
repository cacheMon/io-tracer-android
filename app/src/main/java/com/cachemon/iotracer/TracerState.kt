package com.cachemon.iotracer

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update

/** Immutable snapshot of tracing progress, observed by the UI. */
data class TraceStatus(
    val running: Boolean = false,
    val rootAvailable: Boolean? = null,   // null = not yet checked
    val dsRows: Long = 0,
    val linesSeen: Long = 0,
    val processRows: Long = 0,
    val sessionDir: String? = null,
    val lastMessage: String = "",
)

/** Process-wide tracing state shared between the service and the UI. */
object TracerState {
    private val _status = MutableStateFlow(TraceStatus())
    val status: StateFlow<TraceStatus> = _status.asStateFlow()

    fun update(transform: (TraceStatus) -> TraceStatus) {
        // Atomic compare-and-set retry loop; safe under concurrent writers
        // (reader/snapshot/main threads) where a plain read-modify-write could
        // drop updates.
        _status.update(transform)
    }

    fun reset() {
        _status.update { TraceStatus(rootAvailable = it.rootAvailable) }
    }
}

package com.cachemon.iotracer

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

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
        _status.value = transform(_status.value)
    }

    fun reset() {
        _status.value = TraceStatus(rootAvailable = _status.value.rootAvailable)
    }
}

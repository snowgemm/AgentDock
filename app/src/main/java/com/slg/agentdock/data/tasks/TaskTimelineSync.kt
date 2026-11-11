package com.slg.agentdock.data.tasks

import com.slg.agentdock.data.net.ApiError
import com.slg.agentdock.data.net.ApiResult
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.takeWhile

enum class StreamState { Idle, Connecting, Live, Reconnecting, Offline, Ended, AuthRequired, Failed }

data class TimelineSnapshot(
    val state: StreamState,
    val events: List<TaskEvent>,
    val reconnectAttempt: Int = 0,
    val error: ApiError? = null,
)

/** Bounded exponential backoff with jitter; attempt 0 is the shortest wait. */
class Backoff(
    private val baseMs: Long = 1_000L,
    private val maxMs: Long = 30_000L,
    private val jitter: () -> Double = Math::random,
) {
    fun delayMillis(attempt: Int): Long {
        val exponential = baseMs shl attempt.coerceIn(0, 20)
        val capped = minOf(maxMs, exponential.coerceAtLeast(baseMs))
        return (capped * (0.8 + 0.4 * jitter())).toLong()
    }
}

/**
 * Keeps one task's timeline current: REST catch-up first (so a gap can never exist),
 * then a live SSE connection from the last seen sequence. On any drop it backs off,
 * catches up over REST again and reconnects. The [TimelineBuffer] suppresses
 * duplicates, so overlap between REST and the stream (or a replay) is harmless.
 */
class TaskTimelineSync(
    private val repository: TaskRepository,
    private val stream: TaskEventStream,
    private val buffer: TimelineBuffer,
    private val backoff: Backoff = Backoff(),
) {
    private enum class Outcome { Ended, ReconnectNow, Dropped }

    fun run(taskId: String): Flow<TimelineSnapshot> = flow {
        var attempt = 0
        var firstPass = true
        while (true) {
            emit(snapshot(if (firstPass) StreamState.Connecting else StreamState.Reconnecting, attempt))
            firstPass = false

            val failure = catchUp(taskId)
            if (failure != null) {
                when (failure) {
                    ApiError.AuthRequired -> {
                        emit(snapshot(StreamState.AuthRequired, attempt, failure))
                        return@flow
                    }
                    ApiError.NotFound -> {
                        emit(snapshot(StreamState.Failed, attempt, failure))
                        return@flow
                    }
                    else -> {
                        emit(snapshot(StreamState.Offline, attempt + 1, failure))
                        delay(backoff.delayMillis(attempt++))
                        continue
                    }
                }
            }
            emit(snapshot(StreamState.Connecting, attempt))

            var outcome = Outcome.Dropped
            var dropError: ApiError? = null
            stream.open(taskId, buffer.lastSequence).takeWhile { signal ->
                when (signal) {
                    StreamSignal.Connected -> {
                        attempt = 0
                        emit(snapshot(StreamState.Live, 0))
                        true
                    }
                    is StreamSignal.Event -> {
                        if (buffer.merge(listOf(signal.event))) emit(snapshot(StreamState.Live, 0))
                        true
                    }
                    is StreamSignal.End -> {
                        outcome = Outcome.Ended
                        false
                    }
                    StreamSignal.Reconnect -> {
                        outcome = Outcome.ReconnectNow
                        false
                    }
                    is StreamSignal.ServerError -> {
                        dropError = ApiError.Server
                        false
                    }
                    is StreamSignal.Disconnected -> {
                        dropError = signal.error
                        false
                    }
                }
            }.collect()

            when (outcome) {
                Outcome.Ended -> {
                    emit(snapshot(StreamState.Ended, 0))
                    return@flow
                }
                Outcome.ReconnectNow -> Unit
                Outcome.Dropped -> {
                    if (dropError == ApiError.AuthRequired) {
                        emit(snapshot(StreamState.AuthRequired, attempt, dropError))
                        return@flow
                    }
                    val state = if (dropError == ApiError.Offline) StreamState.Offline else StreamState.Reconnecting
                    emit(snapshot(state, attempt + 1, dropError))
                    delay(backoff.delayMillis(attempt++))
                }
            }
        }
    }

    private fun snapshot(state: StreamState, attempt: Int, error: ApiError? = null) =
        TimelineSnapshot(state, buffer.snapshot(), attempt, error)

    /** Reads every event after the last one seen. Returns null on success. */
    private suspend fun catchUp(taskId: String): ApiError? {
        var pages = 0
        while (pages++ < MAX_CATCH_UP_PAGES) {
            when (val result = repository.events(taskId, buffer.lastSequence)) {
                is ApiResult.Failure -> return result.error
                is ApiResult.Success -> {
                    buffer.merge(result.value.items)
                    if (result.value.nextAfterSequence == null) return null
                }
            }
        }
        return null
    }

    private companion object {
        const val MAX_CATCH_UP_PAGES = 50
    }
}

package com.slg.agentdock.data.tasks

import com.slg.agentdock.data.net.ApiError
import com.slg.agentdock.data.net.ApiResult
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.test.currentTime
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

private fun event(sequence: Long) = TaskEvent("e$sequence", sequence, "STEP", JsonObject(emptyMap()), sequence)

private class ScriptedRepository(
    private val pages: MutableList<ApiResult<TaskEventPage>>,
) : TaskRepository {
    val afterSequences = mutableListOf<Long>()
    override suspend fun events(taskId: String, afterSequence: Long, limit: Int): ApiResult<TaskEventPage> {
        afterSequences += afterSequence
        return if (pages.size > 1) pages.removeAt(0) else pages.first()
    }

    override suspend fun create(idempotencyKey: String, title: String, prompt: String) = error("unused")
    override suspend fun list(cursor: String?, limit: Int) = error("unused")
    override suspend fun detail(taskId: String) = error("unused")
}

private class ScriptedStream(private val connections: MutableList<List<StreamSignal>>) : TaskEventStream {
    val openedAfter = mutableListOf<Long>()
    override fun open(taskId: String, afterSequence: Long): Flow<StreamSignal> {
        openedAfter += afterSequence
        val script = if (connections.isNotEmpty()) connections.removeAt(0) else listOf(StreamSignal.End("SUCCEEDED"))
        return flow { script.forEach { emit(it) } }
    }
}

private fun page(vararg sequences: Long) =
    ApiResult.Success(TaskEventPage(sequences.map(::event), null))

class TaskTimelineSyncTest {
    private val noJitter = Backoff(baseMs = 1_000, maxMs = 8_000, jitter = { 0.5 })

    @Test
    fun duplicatesFromRestAndStreamAreSuppressedAndOrderIsPreserved() = runTest {
        val repository = ScriptedRepository(mutableListOf(page(1, 2)))
        val stream = ScriptedStream(
            mutableListOf(
                listOf(
                    StreamSignal.Connected,
                    StreamSignal.Event(event(2)), // already delivered by REST
                    StreamSignal.Event(event(3)),
                    StreamSignal.Event(event(3)), // duplicate delivery
                    StreamSignal.End("SUCCEEDED"),
                ),
            ),
        )
        val buffer = TimelineBuffer()

        val updates = TaskTimelineSync(repository, stream, buffer, noJitter).run("t").toList()

        assertEquals(listOf(1L, 2L, 3L), updates.last().events.map { it.sequence })
        assertEquals(StreamState.Ended, updates.last().state)
        assertEquals(listOf(2L), stream.openedAfter) // resumed from the REST catch-up position
    }

    @Test
    fun reconnectsAfterADropWithBackoffAndRestCatchUpFillsTheGap() = runTest {
        val repository = ScriptedRepository(
            mutableListOf(page(1, 2), page(3, 4)), // second catch-up supplies events missed while offline
        )
        val stream = ScriptedStream(
            mutableListOf(
                listOf(StreamSignal.Connected, StreamSignal.Event(event(3)), StreamSignal.Disconnected(ApiError.Offline)),
                listOf(StreamSignal.Connected, StreamSignal.Event(event(5)), StreamSignal.End("SUCCEEDED")),
            ),
        )

        val updates = TaskTimelineSync(repository, stream, TimelineBuffer(), noJitter).run("t").toList()

        assertEquals(listOf(1L, 2L, 3L, 4L, 5L), updates.last().events.map { it.sequence })
        assertEquals(listOf(2L, 4L), stream.openedAfter) // second connection resumes after the catch-up
        assertEquals(listOf(0L, 3L), repository.afterSequences)
        assertTrue(updates.any { it.state == StreamState.Offline })
        assertEquals(1_000L, currentTime) // exactly one backoff wait of the base delay
    }

    @Test
    fun serverRequestedReconnectIsImmediate() = runTest {
        val repository = ScriptedRepository(mutableListOf(page(1)))
        val stream = ScriptedStream(
            mutableListOf(
                listOf(StreamSignal.Connected, StreamSignal.Reconnect),
                listOf(StreamSignal.Connected, StreamSignal.End(null)),
            ),
        )
        TaskTimelineSync(repository, stream, TimelineBuffer(), noJitter).run("t").toList()
        assertEquals(2, stream.openedAfter.size)
        assertEquals(0L, currentTime)
    }

    @Test
    fun offlineCatchUpBacksOffExponentiallyUpToTheCap() = runTest {
        val failing = ApiResult.Failure(ApiError.Offline)
        val repository = ScriptedRepository(mutableListOf(failing, failing, failing, failing, failing, page(1)))
        val stream = ScriptedStream(mutableListOf(listOf(StreamSignal.Connected, StreamSignal.End(null))))

        val updates = TaskTimelineSync(repository, stream, TimelineBuffer(), noJitter).run("t").toList()

        // waits: 1s, 2s, 4s, 8s, 8s (capped)
        assertEquals(23_000L, currentTime)
        assertEquals(StreamState.Ended, updates.last().state)
        assertEquals(5, updates.count { it.state == StreamState.Offline })
    }

    @Test
    fun expiredAuthenticationStopsReconnectingInsteadOfLooping() = runTest {
        val repository = ScriptedRepository(mutableListOf(ApiResult.Failure(ApiError.AuthRequired)))
        val stream = ScriptedStream(mutableListOf())

        val updates = TaskTimelineSync(repository, stream, TimelineBuffer(), noJitter).run("t").toList()

        assertEquals(StreamState.AuthRequired, updates.last().state)
        assertTrue(stream.openedAfter.isEmpty())
        assertEquals(0L, currentTime)
    }

    @Test
    fun streamAuthFailureAfterConnectingAlsoStops() = runTest {
        val repository = ScriptedRepository(mutableListOf(page(1)))
        val stream = ScriptedStream(mutableListOf(listOf(StreamSignal.Disconnected(ApiError.AuthRequired))))
        val updates = TaskTimelineSync(repository, stream, TimelineBuffer(), noJitter).run("t").toList()
        assertEquals(StreamState.AuthRequired, updates.last().state)
        assertEquals(1, stream.openedAfter.size)
    }

    @Test
    fun missingTaskEndsWithAFailureNotARetryLoop() = runTest {
        val repository = ScriptedRepository(mutableListOf(ApiResult.Failure(ApiError.NotFound)))
        val updates = TaskTimelineSync(repository, ScriptedStream(mutableListOf()), TimelineBuffer(), noJitter)
            .run("t").toList()
        assertEquals(StreamState.Failed, updates.last().state)
        assertEquals(ApiError.NotFound, updates.last().error)
    }

    @Test
    fun backoffDoublesAndCaps() {
        val backoff = Backoff(baseMs = 1_000, maxMs = 30_000, jitter = { 0.5 })
        assertEquals(listOf(1_000L, 2_000L, 4_000L, 8_000L, 16_000L, 30_000L, 30_000L),
            (0..6).map { backoff.delayMillis(it) })
        val jittered = Backoff(1_000, 30_000, jitter = { 0.0 }).delayMillis(0)
        assertEquals(800L, jittered)
    }
}

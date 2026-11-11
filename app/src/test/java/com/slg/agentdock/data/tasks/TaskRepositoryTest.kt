package com.slg.agentdock.data.tasks

import com.slg.agentdock.data.net.ApiError
import com.slg.agentdock.data.net.ApiResult
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.Json
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import mockwebserver3.SocketEffect
import okhttp3.OkHttpClient
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.util.concurrent.TimeUnit

class TaskRepositoryTest {
    private lateinit var server: MockWebServer
    private lateinit var repository: HttpTaskRepository

    private val taskJson = """
        {"id":"6c3f0c9e-0000-4000-8000-000000000001","title":"Review","status":"QUEUED",
         "created_at":"2026-11-11T10:00:00.000000Z","updated_at":"2026-11-11T10:00:00Z",
         "prompt":"Do the review","attributes":{},"future":1}
    """.trimIndent()

    @Before
    fun setUp() {
        server = MockWebServer().also { it.start() }
        val client = OkHttpClient.Builder().callTimeout(2, TimeUnit.SECONDS).build()
        repository = HttpTaskRepository(client, server.url("/"), Json { ignoreUnknownKeys = true })
    }

    @After
    fun tearDown() = server.close()

    @Test
    fun createSendsIdempotencyKeyAndMapsTheTask() = runTest {
        server.enqueue(MockResponse.Builder().code(201).body(taskJson).build())

        val result = repository.create("key-0123456789", "Review", "Do the review")

        val recorded = server.takeRequest()
        assertEquals("key-0123456789", recorded.headers["Idempotency-Key"])
        assertEquals("/api/v1/tasks", recorded.url.encodedPath)
        assertTrue(recorded.body!!.utf8().contains("\"title\":\"Review\""))
        val detail = (result as ApiResult.Success).value
        assertEquals(TaskStatus.QUEUED, detail.task.status)
        assertEquals("Do the review", detail.prompt)
        assertTrue(detail.task.createdAtMs > 0)
    }

    @Test
    fun retryAfterATransportFailureReusesTheSameKeyAndGetsTheSameTask() = runTest {
        val tracker = SubmissionTracker()
        server.enqueue(MockResponse.Builder().onResponseStart(SocketEffect.ShutdownConnection).build())
        server.enqueue(MockResponse.Builder().code(201).body(taskJson).build())

        val first = repository.create(tracker.keyFor("tab-1", "Review", "Do it"), "Review", "Do it")
        val second = repository.create(tracker.keyFor("tab-1", "Review", "Do it"), "Review", "Do it")

        assertEquals(ApiResult.Failure(ApiError.Offline), first)
        assertTrue(second is ApiResult.Success)
        assertEquals(
            server.takeRequest().headers["Idempotency-Key"],
            server.takeRequest().headers["Idempotency-Key"],
        )
    }

    @Test
    fun mapsHttpFailures() = runTest {
        listOf(401 to ApiError.AuthRequired, 404 to ApiError.NotFound, 409 to ApiError.Conflict,
            422 to ApiError.Invalid, 503 to ApiError.Server).forEach { (code, _) ->
            server.enqueue(MockResponse.Builder().code(code).build())
        }
        val expected = listOf(ApiError.AuthRequired, ApiError.NotFound, ApiError.Conflict, ApiError.Invalid, ApiError.Server)
        expected.forEach { error ->
            assertEquals(ApiResult.Failure(error), repository.detail("6c3f0c9e-0000-4000-8000-000000000001"))
        }
    }

    @Test
    fun malformedSuccessBodyIsReportedNotCrashed() = runTest {
        server.enqueue(MockResponse.Builder().code(200).body("""{"items": "nope"}""").build())
        assertEquals(ApiResult.Failure(ApiError.Malformed), repository.list(null))
    }

    @Test
    fun listUsesCursorAndLimitAndReturnsNextCursor() = runTest {
        server.enqueue(
            MockResponse.Builder().code(200).body(
                """{"items":[{"id":"a","title":"T","status":"RUNNING","created_at":"2026-11-11T10:00:00Z","updated_at":"2026-11-11T10:00:00Z"},
                    {"id":"b","title":"U","status":"SOMETHING_NEW","created_at":"2026-11-11T09:00:00Z","updated_at":"2026-11-11T09:00:00Z"}],
                   "next_cursor":"CUR"}""",
            ).build(),
        )

        val page = (repository.list("PREV", 10) as ApiResult.Success).value

        val recorded = server.takeRequest()
        assertEquals("10", recorded.url.queryParameter("limit"))
        assertEquals("PREV", recorded.url.queryParameter("cursor"))
        assertEquals("CUR", page.nextCursor)
        assertEquals(TaskStatus.RUNNING, page.items[0].status)
        assertEquals(TaskStatus.UNKNOWN, page.items[1].status)
    }

    @Test
    fun eventsPassAfterSequenceAndExposeNextPage() = runTest {
        server.enqueue(
            MockResponse.Builder().code(200).body(
                """{"items":[{"id":"e1","sequence":5,"event_type":"TASK_CREATED","payload":{"status":"QUEUED"},
                    "occurred_at":"2026-11-11T10:00:00Z"}],"next_after_sequence":5}""",
            ).build(),
        )

        val page = (repository.events("task-1", 4, 50) as ApiResult.Success).value

        val recorded = server.takeRequest()
        assertEquals("/api/v1/tasks/task-1/events", recorded.url.encodedPath)
        assertEquals("4", recorded.url.queryParameter("after_sequence"))
        assertEquals(5L, page.items.single().sequence)
        assertEquals(5L, page.nextAfterSequence)
    }
}

class SubmissionTrackerTest {
    @Test
    fun sameContentReusesKeyAndChangedContentOrCompletionRotatesIt() {
        var counter = 0
        val tracker = SubmissionTracker { "key-${++counter}" }

        val first = tracker.keyFor("tab", "T", "P")
        assertEquals(first, tracker.keyFor("tab", "T", "P"))
        assertEquals("key-2", tracker.keyFor("tab", "T", "P changed"))
        tracker.complete("tab")
        assertEquals("key-3", tracker.keyFor("tab", "T", "P changed"))
        assertEquals("key-4", tracker.keyFor("other-tab", "T", "P changed"))
    }

    @Test
    fun titleComesFromTheFirstNonBlankLineAndIsBounded() {
        assertEquals("Review the release", deriveTaskTitle("\n  Review   the release \nmore", "fallback"))
        assertEquals("fallback", deriveTaskTitle("   \n ", "fallback"))
        val long = deriveTaskTitle("x".repeat(300), "fallback")
        assertEquals(80, long.length)
        assertTrue(long.endsWith("…"))
    }
}

class TimelineBufferTest {
    private fun event(sequence: Long) = TaskEvent(
        id = "e$sequence",
        sequence = sequence,
        type = "T",
        payload = kotlinx.serialization.json.JsonObject(emptyMap()),
        occurredAtMs = sequence,
    )

    @Test
    fun mergeOrdersBySequenceAndSuppressesDuplicates() {
        val buffer = TimelineBuffer()
        assertTrue(buffer.merge(listOf(event(3), event(1))))
        assertTrue(buffer.merge(listOf(event(2), event(3))))
        assertEquals(listOf(1L, 2L, 3L), buffer.snapshot().map { it.sequence })
        assertEquals(3L, buffer.lastSequence)
    }

    @Test
    fun replayOfKnownEventsReportsNoChange() {
        val buffer = TimelineBuffer(listOf(event(1), event(2)))
        assertEquals(false, buffer.merge(listOf(event(2), event(1))))
        assertEquals(false, buffer.merge(listOf(event(0), event(-4))))
        assertEquals(2L, buffer.lastSequence)
    }
}

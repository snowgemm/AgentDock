package com.slg.agentdock.data.tasks

import com.slg.agentdock.data.net.ApiError
import kotlinx.coroutines.flow.takeWhile
import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.Json
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import okhttp3.OkHttpClient
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.util.concurrent.TimeUnit

class SseTaskEventStreamTest {
    private lateinit var server: MockWebServer
    private lateinit var stream: SseTaskEventStream

    @Before
    fun setUp() {
        server = MockWebServer().also { it.start() }
        stream = SseTaskEventStream(
            OkHttpClient.Builder().readTimeout(5, TimeUnit.SECONDS).build(),
            server.url("/"),
            Json { ignoreUnknownKeys = true },
        )
    }

    @After
    fun tearDown() = server.close()

    private fun sse(body: String) = MockResponse.Builder()
        .code(200)
        .addHeader("Content-Type", "text/event-stream")
        .body(body)
        .build()

    @Test
    fun parsesEventsIgnoresHeartbeatsAndSendsLastEventId() = runTest {
        server.enqueue(
            sse(
                "retry: 3000\n\n" +
                    "id: 4\nevent: task_event\ndata: {\"id\":\"e4\",\"sequence\":4,\"event_type\":\"STEP\"," +
                    "\"payload\":{\"n\":1},\"occurred_at\":\"2026-11-11T10:00:00Z\"}\n\n" +
                    ": heartbeat\n\n" +
                    "event: unknown_future_event\ndata: {}\n\n" +
                    "event: end\ndata: {\"status\":\"SUCCEEDED\",\"last_sequence\":4}\n\n",
            ),
        )

        val signals = stream.open("task-1", afterSequence = 3).takeWhile { it !is StreamSignal.End }.toList()

        val recorded = server.takeRequest()
        assertEquals("/api/v1/tasks/task-1/events/stream", recorded.url.encodedPath)
        assertEquals("3", recorded.headers["Last-Event-ID"])
        assertEquals("text/event-stream", recorded.headers["Accept"])
        assertEquals(StreamSignal.Connected, signals.first())
        val event = signals.filterIsInstance<StreamSignal.Event>().single().event
        assertEquals(4L, event.sequence)
        assertEquals("STEP", event.type)
        assertEquals(2, signals.size) // heartbeat and unknown event types produce nothing
    }

    @Test
    fun serverReconnectAndEndEventsAreSurfaced() = runTest {
        server.enqueue(sse("event: reconnect\ndata: {\"last_sequence\":9}\n\n"))
        val signals = stream.open("t", 0).takeWhile { it !is StreamSignal.Reconnect }.toList()
        assertEquals(listOf<StreamSignal>(StreamSignal.Connected), signals)
        assertTrue(server.takeRequest().headers["Last-Event-ID"] == null) // 0 means "from the start"
    }

    @Test
    fun failureCodesAreReportedNotSwallowed() = runTest {
        val expected = listOf(401 to ApiError.AuthRequired, 404 to ApiError.NotFound, 503 to ApiError.Server)
        expected.forEach { (code, _) -> server.enqueue(MockResponse.Builder().code(code).build()) }
        expected.forEach { (_, error) ->
            val signals = mutableListOf<StreamSignal>()
            stream.open("t", 0).takeWhile { signal -> signals += signal; signal !is StreamSignal.Disconnected }.toList()
            assertEquals(StreamSignal.Disconnected(error), signals.last())
        }
    }
}

package com.slg.agentdock.data.tasks

import com.slg.agentdock.data.auth.SessionUnavailableException
import com.slg.agentdock.data.auth.SignedOutException
import com.slg.agentdock.data.net.ApiError
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.HttpUrl
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.sse.EventSource
import okhttp3.sse.EventSourceListener
import okhttp3.sse.EventSources

sealed interface StreamSignal {
    data object Connected : StreamSignal

    data class Event(val event: TaskEvent) : StreamSignal

    /** The task reached a terminal state and every event was delivered. */
    data class End(val status: String?) : StreamSignal

    /** The server's connection lifetime elapsed; reconnect immediately. */
    data object Reconnect : StreamSignal

    data class ServerError(val code: String) : StreamSignal

    data class Disconnected(val error: ApiError?) : StreamSignal
}

interface TaskEventStream {
    /** Cold flow: one SSE connection per collection, cancelled when collection stops. */
    fun open(taskId: String, afterSequence: Long): Flow<StreamSignal>
}

/** [client] is the session-aware client; it adds and refreshes the bearer token. */
class SseTaskEventStream(
    private val client: OkHttpClient,
    private val baseUrl: HttpUrl,
    private val json: Json,
) : TaskEventStream {
    override fun open(taskId: String, afterSequence: Long): Flow<StreamSignal> = callbackFlow {
        val url = baseUrl.newBuilder()
            .addPathSegments("api/v1/tasks").addPathSegment(taskId)
            .addPathSegments("events/stream")
            .build()
        val request = Request.Builder()
            .url(url)
            .header("Accept", "text/event-stream")
            .apply { if (afterSequence > 0) header("Last-Event-ID", afterSequence.toString()) }
            .build()

        val listener = object : EventSourceListener() {
            override fun onOpen(eventSource: EventSource, response: Response) {
                trySend(StreamSignal.Connected)
            }

            override fun onEvent(eventSource: EventSource, id: String?, type: String?, data: String) {
                val signal = try {
                    when (type) {
                        "task_event" -> StreamSignal.Event(
                            json.decodeFromString(TaskEventDto.serializer(), data).toDomain(),
                        )
                        "end" -> StreamSignal.End(
                            (json.parseToJsonElement(data) as? JsonObject)
                                ?.get("status")?.jsonPrimitive?.contentOrNull,
                        )
                        "reconnect" -> StreamSignal.Reconnect
                        "error" -> StreamSignal.ServerError(
                            (json.parseToJsonElement(data) as? JsonObject)
                                ?.get("code")?.jsonPrimitive?.contentOrNull ?: "unknown",
                        )
                        else -> null // unknown event types are ignored for forward compatibility
                    }
                } catch (_: SerializationException) {
                    StreamSignal.Disconnected(ApiError.Malformed)
                } catch (_: IllegalArgumentException) {
                    StreamSignal.Disconnected(ApiError.Malformed)
                }
                if (signal != null) trySend(signal)
            }

            override fun onClosed(eventSource: EventSource) {
                trySend(StreamSignal.Disconnected(null))
            }

            override fun onFailure(eventSource: EventSource, t: Throwable?, response: Response?) {
                val error = when {
                    response != null -> when (response.code) {
                        401 -> ApiError.AuthRequired
                        403 -> ApiError.AuthRequired
                        404 -> ApiError.NotFound
                        else -> ApiError.Server
                    }
                    t is SignedOutException -> ApiError.AuthRequired
                    t is SessionUnavailableException -> ApiError.Offline
                    else -> ApiError.Offline
                }
                trySend(StreamSignal.Disconnected(error))
            }
        }
        val source = EventSources.createFactory(client).newEventSource(request, listener)
        awaitClose { source.cancel() }
    }
}

package com.slg.agentdock.data.tasks

import com.slg.agentdock.data.net.ApiResult
import com.slg.agentdock.data.net.callApi
import com.slg.agentdock.data.net.map
import kotlinx.serialization.json.Json
import okhttp3.HttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody

interface TaskRepository {
    /** [idempotencyKey] must be reused verbatim when the same submission is retried. */
    suspend fun create(idempotencyKey: String, title: String, prompt: String): ApiResult<RemoteTaskDetail>
    suspend fun list(cursor: String?, limit: Int = DEFAULT_PAGE_SIZE): ApiResult<TaskPage>
    suspend fun detail(taskId: String): ApiResult<RemoteTaskDetail>
    suspend fun events(taskId: String, afterSequence: Long, limit: Int = DEFAULT_EVENT_PAGE): ApiResult<TaskEventPage>

    companion object {
        const val DEFAULT_PAGE_SIZE = 25
        const val DEFAULT_EVENT_PAGE = 100
    }
}

/** [client] is the session-aware client; the bearer token is added by its interceptor. */
class HttpTaskRepository(
    private val client: OkHttpClient,
    private val baseUrl: HttpUrl,
    private val json: Json,
) : TaskRepository {
    override suspend fun create(
        idempotencyKey: String,
        title: String,
        prompt: String,
    ): ApiResult<RemoteTaskDetail> {
        val body = json.encodeToString(TaskCreateDto.serializer(), TaskCreateDto(title, prompt))
        val request = Request.Builder()
            .url(tasksUrl().build())
            .header("Idempotency-Key", idempotencyKey)
            .post(body.toRequestBody(JSON_MEDIA_TYPE))
            .build()
        return client.callApi(request) { json.decodeFromString(TaskReadDto.serializer(), it) }
            .map { it.toDomain() }
    }

    override suspend fun list(cursor: String?, limit: Int): ApiResult<TaskPage> {
        val url = tasksUrl().addQueryParameter("limit", limit.coerceIn(1, 100).toString()).apply {
            if (cursor != null) addQueryParameter("cursor", cursor)
        }.build()
        return client.callApi(Request.Builder().url(url).get().build()) {
            json.decodeFromString(TaskListDto.serializer(), it)
        }.map { page -> TaskPage(page.items.map { it.toDomain() }, page.nextCursor) }
    }

    override suspend fun detail(taskId: String): ApiResult<RemoteTaskDetail> {
        val url = tasksUrl().addPathSegment(taskId).build()
        return client.callApi(Request.Builder().url(url).get().build()) {
            json.decodeFromString(TaskReadDto.serializer(), it)
        }.map { it.toDomain() }
    }

    override suspend fun events(
        taskId: String,
        afterSequence: Long,
        limit: Int,
    ): ApiResult<TaskEventPage> {
        val url = tasksUrl().addPathSegment(taskId).addPathSegment("events")
            .addQueryParameter("after_sequence", afterSequence.coerceAtLeast(0).toString())
            .addQueryParameter("limit", limit.coerceIn(1, 200).toString())
            .build()
        return client.callApi(Request.Builder().url(url).get().build()) {
            json.decodeFromString(TaskEventsPageDto.serializer(), it)
        }.map { page -> TaskEventPage(page.items.map { it.toDomain() }, page.nextAfterSequence) }
    }

    private fun tasksUrl(): HttpUrl.Builder = baseUrl.newBuilder().addPathSegments("api/v1/tasks")

    private companion object {
        val JSON_MEDIA_TYPE = "application/json; charset=utf-8".toMediaType()
    }
}

package com.slg.agentdock.data.tasks

import com.slg.agentdock.data.net.ApiResult
import com.slg.agentdock.data.net.callApi
import com.slg.agentdock.data.net.map
import com.slg.agentdock.data.net.parseIsoInstantMillis
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import okhttp3.HttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody

@Serializable
data class ApprovalDto(
    val id: String,
    @SerialName("task_id") val taskId: String,
    val tool: String,
    val target: String,
    val risk: String,
    val summary: String,
    @SerialName("key_args") val keyArgs: JsonObject = JsonObject(emptyMap()),
    val digest: String,
    val status: String,
    @SerialName("expires_at") val expiresAt: String,
)

@Serializable
data class ApprovalDecisionDto(val decision: String, val digest: String)

enum class ApprovalStatus {
    PENDING, APPROVED, DENIED, REVOKED, CONSUMED, EXPIRED, UNKNOWN;

    companion object {
        fun fromWire(value: String): ApprovalStatus =
            entries.firstOrNull { it.name == value && it != UNKNOWN } ?: UNKNOWN
    }
}

enum class ApprovalRisk {
    READ_ONLY, REVERSIBLE, CONSEQUENTIAL, UNKNOWN;

    companion object {
        fun fromWire(value: String): ApprovalRisk = when (value) {
            "read_only" -> READ_ONLY
            "reversible" -> REVERSIBLE
            "consequential" -> CONSEQUENTIAL
            else -> UNKNOWN
        }
    }
}

/** The exact action an approver is asked to authorize. [digest] identifies it uniquely. */
data class Approval(
    val id: String,
    val taskId: String,
    val tool: String,
    val target: String,
    val risk: ApprovalRisk,
    val summary: String,
    val keyArgs: List<Pair<String, String>>,
    val digest: String,
    val status: ApprovalStatus,
    val expiresAtMs: Long,
) {
    /** Only a pending approval that has not expired may be decided. */
    fun isActionable(nowMs: Long): Boolean = status == ApprovalStatus.PENDING && expiresAtMs > nowMs
}

fun ApprovalDto.toDomain() = Approval(
    id = id,
    taskId = taskId,
    tool = tool,
    target = target,
    risk = ApprovalRisk.fromWire(risk),
    summary = summary,
    keyArgs = keyArgs.entries.map { (key, value) ->
        key to ((value as? JsonPrimitive)?.contentOrNull ?: value.toString())
    },
    digest = digest,
    status = ApprovalStatus.fromWire(status),
    expiresAtMs = parseIsoInstantMillis(expiresAt) ?: 0L,
)

interface ApprovalRepository {
    suspend fun list(taskId: String): ApiResult<List<Approval>>

    /** Echoes [digest] so the server refuses the decision if the action changed after display. */
    suspend fun decide(approvalId: String, digest: String, approve: Boolean): ApiResult<Approval>
}

class HttpApprovalRepository(
    private val client: OkHttpClient,
    private val baseUrl: HttpUrl,
    private val json: Json,
) : ApprovalRepository {
    override suspend fun list(taskId: String): ApiResult<List<Approval>> {
        val url = baseUrl.newBuilder().addPathSegments("api/v1/tasks").addPathSegment(taskId)
            .addPathSegment("approvals").build()
        return client.callApi(Request.Builder().url(url).get().build()) {
            json.decodeFromString(kotlinx.serialization.builtins.ListSerializer(ApprovalDto.serializer()), it)
        }.map { items -> items.map { it.toDomain() } }
    }

    override suspend fun decide(approvalId: String, digest: String, approve: Boolean): ApiResult<Approval> {
        val url = baseUrl.newBuilder().addPathSegments("api/v1/approvals").addPathSegment(approvalId)
            .addPathSegment("decision").build()
        val body = json.encodeToString(
            ApprovalDecisionDto.serializer(),
            ApprovalDecisionDto(if (approve) "approve" else "deny", digest),
        )
        return client.callApi(
            Request.Builder().url(url).post(body.toRequestBody(JSON_MEDIA_TYPE)).build(),
        ) { json.decodeFromString(ApprovalDto.serializer(), it) }.map { it.toDomain() }
    }

    private companion object {
        val JSON_MEDIA_TYPE = "application/json; charset=utf-8".toMediaType()
    }
}

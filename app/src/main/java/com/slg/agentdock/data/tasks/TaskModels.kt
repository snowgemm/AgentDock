package com.slg.agentdock.data.tasks

import com.slg.agentdock.data.net.parseIsoInstantMillis
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject

/** Wire formats from backend/app/tasks/schemas.py. Unknown fields are ignored. */
@Serializable
data class TaskSummaryDto(
    val id: String,
    val title: String,
    val status: String,
    @SerialName("created_at") val createdAt: String,
    @SerialName("updated_at") val updatedAt: String,
)

@Serializable
data class TaskReadDto(
    val id: String,
    val title: String,
    val status: String,
    @SerialName("created_at") val createdAt: String,
    @SerialName("updated_at") val updatedAt: String,
    val prompt: String,
    val attributes: JsonObject = JsonObject(emptyMap()),
)

@Serializable
data class TaskListDto(
    val items: List<TaskSummaryDto>,
    @SerialName("next_cursor") val nextCursor: String? = null,
)

@Serializable
data class TaskEventDto(
    val id: String,
    val sequence: Long,
    @SerialName("event_type") val eventType: String,
    val payload: JsonObject = JsonObject(emptyMap()),
    @SerialName("occurred_at") val occurredAt: String,
)

@Serializable
data class TaskEventsPageDto(
    val items: List<TaskEventDto>,
    @SerialName("next_after_sequence") val nextAfterSequence: Long? = null,
)

@Serializable
data class TaskCreateDto(val title: String, val prompt: String)

enum class TaskStatus(val wire: String) {
    QUEUED("QUEUED"),
    PLANNING("PLANNING"),
    RUNNING("RUNNING"),
    WAITING_APPROVAL("WAITING_APPROVAL"),
    VERIFYING("VERIFYING"),
    SUCCEEDED("SUCCEEDED"),
    FAILED("FAILED"),
    CANCELLED("CANCELLED"),
    PAUSED("PAUSED"),
    RETRYING("RETRYING"),
    RECOVERING("RECOVERING"),
    EXPIRED("EXPIRED"),

    /** A status added by a newer server; shown generically, never guessed. */
    UNKNOWN("UNKNOWN"),
    ;

    val isTerminal: Boolean
        get() = this == SUCCEEDED || this == FAILED || this == CANCELLED || this == EXPIRED

    companion object {
        fun fromWire(value: String): TaskStatus =
            entries.firstOrNull { it.wire == value && it != UNKNOWN } ?: UNKNOWN
    }
}

data class RemoteTask(
    val id: String,
    val title: String,
    val status: TaskStatus,
    val createdAtMs: Long,
    val updatedAtMs: Long,
)

data class RemoteTaskDetail(
    val task: RemoteTask,
    val prompt: String,
)

data class TaskEvent(
    val id: String,
    val sequence: Long,
    val type: String,
    val payload: JsonObject,
    val occurredAtMs: Long,
)

data class TaskPage(val items: List<RemoteTask>, val nextCursor: String?)

data class TaskEventPage(val items: List<TaskEvent>, val nextAfterSequence: Long?)

fun TaskSummaryDto.toDomain() = RemoteTask(
    id = id,
    title = title,
    status = TaskStatus.fromWire(status),
    createdAtMs = parseIsoInstantMillis(createdAt) ?: 0L,
    updatedAtMs = parseIsoInstantMillis(updatedAt) ?: 0L,
)

fun TaskReadDto.toDomain() = RemoteTaskDetail(
    task = RemoteTask(
        id = id,
        title = title,
        status = TaskStatus.fromWire(status),
        createdAtMs = parseIsoInstantMillis(createdAt) ?: 0L,
        updatedAtMs = parseIsoInstantMillis(updatedAt) ?: 0L,
    ),
    prompt = prompt,
)

fun TaskEventDto.toDomain() = TaskEvent(
    id = id,
    sequence = sequence,
    type = eventType,
    payload = payload,
    occurredAtMs = parseIsoInstantMillis(occurredAt) ?: 0L,
)

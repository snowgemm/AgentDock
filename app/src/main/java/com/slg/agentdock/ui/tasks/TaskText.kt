package com.slg.agentdock.ui.tasks

import androidx.annotation.StringRes
import com.slg.agentdock.R
import com.slg.agentdock.data.net.ApiError
import com.slg.agentdock.data.tasks.TaskStatus

@StringRes
fun TaskStatus.labelRes(): Int = when (this) {
    TaskStatus.QUEUED -> R.string.status_queued
    TaskStatus.PLANNING -> R.string.status_planning
    TaskStatus.RUNNING -> R.string.status_running
    TaskStatus.WAITING_APPROVAL -> R.string.status_waiting_approval
    TaskStatus.VERIFYING -> R.string.status_verifying
    TaskStatus.SUCCEEDED -> R.string.status_succeeded
    TaskStatus.FAILED -> R.string.status_failed
    TaskStatus.CANCELLED -> R.string.status_cancelled
    TaskStatus.PAUSED -> R.string.status_paused
    TaskStatus.RETRYING -> R.string.status_retrying
    TaskStatus.RECOVERING -> R.string.status_recovering
    TaskStatus.EXPIRED -> R.string.status_expired
    TaskStatus.UNKNOWN -> R.string.status_unknown
}

/** Extra honesty for states where the label alone could be misread. */
@StringRes
fun TaskStatus.explanationRes(): Int? = when (this) {
    TaskStatus.QUEUED -> R.string.status_queued_explanation
    else -> null
}

@StringRes
fun ApiError.messageRes(): Int = when (this) {
    ApiError.AuthRequired -> R.string.error_auth_required
    ApiError.Offline -> R.string.error_offline
    ApiError.Server -> R.string.error_server
    ApiError.NotFound -> R.string.error_not_found
    ApiError.Conflict -> R.string.error_conflict
    ApiError.Invalid -> R.string.error_invalid
    ApiError.Malformed -> R.string.error_malformed
}

/** Known event types get localized text; unknown ones are shown verbatim, never hidden. */
@StringRes
fun com.slg.agentdock.data.tasks.TaskEvent.eventLabelRes(): Int? = when (type) {
    "TASK_CREATED" -> R.string.event_task_created
    "TASK_STARTED" -> R.string.event_task_started
    "TASK_RECOVERING" -> R.string.event_task_recovering
    "TASK_RETRY_SCHEDULED" -> R.string.event_task_retry
    "TASK_VERIFYING" -> R.string.event_task_verifying
    "TASK_SUCCEEDED" -> R.string.event_task_succeeded
    "TASK_FAILED" -> R.string.event_task_failed
    "AGENT_STARTED" -> R.string.event_agent_started
    "AGENT_MODEL_CALL" -> R.string.event_agent_model_call
    "AGENT_TOOL_CALL" -> R.string.event_agent_tool_call
    "AGENT_TOOL_REJECTED" -> R.string.event_agent_tool_rejected
    "AGENT_RESULT" -> R.string.event_agent_result
    "AGENT_TOOL_DENIED" -> R.string.event_agent_tool_denied
    "APPROVAL_REQUESTED" -> R.string.event_approval_requested
    "TASK_WAITING_APPROVAL" -> R.string.event_waiting_approval
    "TASK_APPROVAL_RESOLVED" -> R.string.event_approval_resolved
    else -> null
}

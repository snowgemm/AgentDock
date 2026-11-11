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
    else -> null
}

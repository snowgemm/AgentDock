package com.slg.agentdock.ui.screens

import android.text.format.DateUtils
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.slg.agentdock.R
import com.slg.agentdock.data.tasks.AgentResult
import com.slg.agentdock.data.tasks.StreamState
import com.slg.agentdock.data.tasks.TaskEvent
import com.slg.agentdock.data.tasks.extractAgentResult
import com.slg.agentdock.ui.tasks.TaskDetailUiState
import com.slg.agentdock.ui.tasks.eventLabelRes
import com.slg.agentdock.ui.tasks.explanationRes
import com.slg.agentdock.ui.tasks.labelRes
import com.slg.agentdock.ui.tasks.messageRes

@Composable
fun TaskDetailScreen(
    state: TaskDetailUiState,
    onRefresh: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .fillMaxSize()
            .testTag("taskDetail.screen")
            .padding(horizontal = 20.dp)
            .padding(top = 18.dp, bottom = 24.dp)
            .verticalScroll(rememberScrollState()),
    ) {
        val detail = state.detail
        Text(
            text = detail?.task?.title ?: stringResource(R.string.tasks_loading),
            style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.SemiBold,
        )
        if (detail != null) {
            Spacer(Modifier.height(6.dp))
            Text(
                text = stringResource(detail.task.status.labelRes()),
                style = MaterialTheme.typography.titleSmall,
                color = MaterialTheme.colorScheme.primary,
                modifier = Modifier.testTag("taskDetail.status"),
            )
            detail.task.status.explanationRes()?.let {
                Spacer(Modifier.height(4.dp))
                Text(
                    text = stringResource(it),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.testTag("taskDetail.statusExplanation"),
                )
            }
            Spacer(Modifier.height(16.dp))
            Text(
                text = stringResource(R.string.task_request_heading),
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.Medium,
            )
            Spacer(Modifier.height(4.dp))
            Text(text = detail.prompt, style = MaterialTheme.typography.bodyMedium)
        }

        extractAgentResult(state.events)?.let { result ->
            Spacer(Modifier.height(16.dp))
            ResultCard(result)
        }

        state.error?.let {
            Spacer(Modifier.height(12.dp))
            ErrorWithRetry(message = stringResource(it.messageRes()), onRetry = onRefresh)
        }

        Spacer(Modifier.height(20.dp))
        HorizontalDivider(color = MaterialTheme.colorScheme.outline)
        Spacer(Modifier.height(14.dp))
        Row {
            Text(
                text = stringResource(R.string.timeline_heading),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
                modifier = Modifier.weight(1f),
            )
            OutlinedButton(
                onClick = onRefresh,
                enabled = !state.loading,
                modifier = Modifier.testTag("taskDetail.refresh"),
            ) {
                Text(stringResource(if (state.loading) R.string.tasks_loading else R.string.refresh))
            }
        }
        StreamStatusLine(state.stream)
        Spacer(Modifier.height(10.dp))
        if (state.events.isEmpty() && !state.loading) {
            Text(
                text = stringResource(R.string.timeline_empty),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        state.events.forEach { event ->
            TimelineRow(event, isNew = state.lastSeenAtOpen > 0 && event.sequence > state.lastSeenAtOpen)
        }
    }
}

@Composable
private fun TimelineRow(event: TaskEvent, isNew: Boolean) {
    Row(modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp).testTag("timeline.row")) {
        Text(
            text = "#${event.sequence}",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.width(36.dp),
        )
        Column {
            Text(
                text = (event.eventLabelRes()?.let { stringResource(it) } ?: event.type) +
                    if (isNew) " · " + stringResource(R.string.timeline_new) else "",
                style = MaterialTheme.typography.bodyMedium,
            )
            Text(
                text = DateUtils.getRelativeTimeSpanString(
                    event.occurredAtMs,
                    System.currentTimeMillis(),
                    DateUtils.SECOND_IN_MILLIS,
                ).toString(),
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

/** Honest connection state for the live timeline; never implies progress that is not happening. */
@Composable
fun StreamStatusLine(state: StreamState, modifier: Modifier = Modifier) {
    val label = when (state) {
        StreamState.Idle -> return
        StreamState.Connecting -> R.string.stream_connecting
        StreamState.Live -> R.string.stream_live
        StreamState.Reconnecting -> R.string.stream_reconnecting
        StreamState.Offline -> R.string.stream_offline
        StreamState.Ended -> R.string.stream_ended
        StreamState.AuthRequired -> R.string.stream_auth_required
        StreamState.Failed -> R.string.stream_failed
    }
    Text(
        text = stringResource(label),
        style = MaterialTheme.typography.labelMedium,
        color = if (state == StreamState.Live) MaterialTheme.colorScheme.primary
        else MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = modifier.padding(top = 6.dp).testTag("stream.status"),
    )
}

@Composable
private fun ResultCard(result: AgentResult) {
    Surface(
        color = MaterialTheme.colorScheme.surface,
        shape = RoundedCornerShape(12.dp),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline),
        modifier = Modifier.fillMaxWidth().testTag("taskDetail.result"),
    ) {
        Column(modifier = Modifier.padding(14.dp)) {
            Text(
                text = stringResource(R.string.result_heading),
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.Medium,
            )
            Text(
                text = stringResource(
                    if (result.verified) R.string.result_verified else R.string.result_not_verified,
                ),
                style = MaterialTheme.typography.labelMedium,
                color = if (result.verified) MaterialTheme.colorScheme.primary
                else MaterialTheme.colorScheme.error,
                modifier = Modifier.testTag("taskDetail.resultVerification"),
            )
            Spacer(Modifier.height(8.dp))
            Text(text = result.answer, style = MaterialTheme.typography.bodyMedium)
            Spacer(Modifier.height(8.dp))
            Text(
                text = stringResource(R.string.result_verification_note),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

package com.slg.agentdock.ui.screens

import android.text.format.DateUtils
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.slg.agentdock.R
import com.slg.agentdock.data.tasks.RemoteTask
import com.slg.agentdock.ui.components.EmptyState
import com.slg.agentdock.ui.tasks.TaskListUiState
import com.slg.agentdock.ui.tasks.labelRes
import com.slg.agentdock.ui.tasks.messageRes

/**
 * Server tasks. Rows show a server status label, which keeps them visibly distinct
 * from local drafts (those live in the workspace tabs and say "draft").
 */
@Composable
fun TaskListSection(
    state: TaskListUiState,
    signedIn: Boolean,
    onOpen: (String) -> Unit,
    onRefresh: () -> Unit,
    onLoadMore: () -> Unit,
    modifier: Modifier = Modifier,
    maxItems: Int = Int.MAX_VALUE,
) {
    Column(modifier = modifier.fillMaxWidth().testTag("tasks.list")) {
        when {
            !signedIn -> EmptyState(
                title = stringResource(R.string.tasks_signed_out_title),
                description = stringResource(R.string.tasks_signed_out_body),
            )
            state.loading && !state.loadedOnce -> Text(
                text = stringResource(R.string.tasks_loading),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.testTag("tasks.loading"),
            )
            state.error != null && state.items.isEmpty() -> ErrorWithRetry(
                message = stringResource(state.error.messageRes()),
                onRetry = onRefresh,
            )
            state.items.isEmpty() -> EmptyState(
                title = stringResource(R.string.no_tasks_title),
                description = stringResource(R.string.no_tasks_description),
            )
            else -> {
                if (state.error != null) {
                    ErrorWithRetry(message = stringResource(state.error.messageRes()), onRetry = onRefresh)
                    Spacer(Modifier.height(8.dp))
                }
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    state.items.take(maxItems).forEach { task ->
                        TaskRow(task = task, onOpen = { onOpen(task.id) })
                    }
                }
                if (state.nextCursor != null && maxItems == Int.MAX_VALUE) {
                    Spacer(Modifier.height(12.dp))
                    OutlinedButton(
                        onClick = onLoadMore,
                        enabled = !state.loadingMore,
                        modifier = Modifier.fillMaxWidth().testTag("tasks.loadMore"),
                    ) {
                        Text(
                            stringResource(
                                if (state.loadingMore) R.string.tasks_loading else R.string.tasks_load_more,
                            ),
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun TaskRow(task: RemoteTask, onOpen: () -> Unit) {
    Surface(
        color = MaterialTheme.colorScheme.surface,
        shape = RoundedCornerShape(12.dp),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline),
        modifier = Modifier.fillMaxWidth().clickable(onClick = onOpen).testTag("tasks.row"),
    ) {
        Column(modifier = Modifier.padding(14.dp)) {
            Text(
                text = task.title,
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.Medium,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
            Spacer(Modifier.height(4.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = stringResource(task.status.labelRes()),
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.primary,
                )
                Spacer(Modifier.padding(horizontal = 6.dp))
                Text(
                    text = DateUtils.getRelativeTimeSpanString(
                        task.createdAtMs,
                        System.currentTimeMillis(),
                        DateUtils.MINUTE_IN_MILLIS,
                    ).toString(),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
fun ErrorWithRetry(message: String, onRetry: () -> Unit, modifier: Modifier = Modifier) {
    Column(modifier = modifier.fillMaxWidth().testTag("tasks.error")) {
        Text(
            text = message,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.error,
        )
        Spacer(Modifier.height(8.dp))
        OutlinedButton(onClick = onRetry, modifier = Modifier.testTag("tasks.retry")) {
            Text(stringResource(R.string.retry))
        }
    }
}


package com.slg.agentdock.ui.screens

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.slg.agentdock.R
import com.slg.agentdock.data.model.WorkspaceTab
import com.slg.agentdock.ui.components.EmptyState
import com.slg.agentdock.ui.tasks.SubmitUiState
import com.slg.agentdock.ui.tasks.messageRes

@Composable
fun HomeScreen(
    tab: WorkspaceTab,
    onDraftChange: (String, String) -> Unit,
    onSaveDraft: () -> Unit,
    signedIn: Boolean = false,
    submitState: SubmitUiState = SubmitUiState(),
    onSubmit: () -> Unit = {},
    onDismissSubmitError: () -> Unit = {},
    recentTasks: @Composable () -> Unit = {
        EmptyState(
            title = stringResource(R.string.no_tasks_title),
            description = stringResource(R.string.no_tasks_description),
        )
    },
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .testTag("home.screen")
            .padding(horizontal = 20.dp)
            .padding(top = 24.dp, bottom = 20.dp)
            .verticalScroll(rememberScrollState()),
    ) {
        Text(
            text = stringResource(R.string.home_title),
            style = MaterialTheme.typography.headlineMedium,
            fontWeight = FontWeight.SemiBold,
        )
        Spacer(Modifier.height(7.dp))
        Text(
            text = stringResource(R.string.home_description),
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(22.dp))
        Surface(
            color = MaterialTheme.colorScheme.surface,
            shape = RoundedCornerShape(16.dp),
            border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline),
        ) {
            Column(modifier = Modifier.padding(16.dp)) {
                Text(
                    text = stringResource(R.string.task_prompt_label),
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.Medium,
                )
                Spacer(Modifier.height(12.dp))
                OutlinedTextField(
                    value = tab.draft,
                    onValueChange = { onDraftChange(tab.id, it) },
                    modifier = Modifier.fillMaxWidth().testTag("home.taskInput"),
                    placeholder = { Text(stringResource(R.string.task_prompt_hint)) },
                    minLines = 5,
                    maxLines = 8,
                    keyboardOptions = KeyboardOptions(
                        capitalization = KeyboardCapitalization.Sentences,
                        keyboardType = KeyboardType.Text,
                    ),
                    shape = RoundedCornerShape(12.dp),
                )
                Spacer(Modifier.height(12.dp))
                Button(
                    onClick = onSaveDraft,
                    enabled = tab.draft.isNotBlank(),
                    modifier = Modifier.fillMaxWidth().testTag("home.saveDraft"),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = MaterialTheme.colorScheme.primary,
                        contentColor = MaterialTheme.colorScheme.onPrimary,
                    ),
                    contentPadding = PaddingValues(vertical = 13.dp),
                ) {
                    Text(stringResource(R.string.save_draft), fontWeight = FontWeight.SemiBold)
                }
                Spacer(Modifier.height(10.dp))
                if (signedIn) {
                    Button(
                        onClick = onSubmit,
                        enabled = tab.draft.isNotBlank() && !submitState.submitting,
                        modifier = Modifier.fillMaxWidth().testTag("home.submitTask"),
                        contentPadding = PaddingValues(vertical = 13.dp),
                    ) {
                        Text(
                            stringResource(
                                if (submitState.submitting) R.string.submitting_task else R.string.submit_task,
                            ),
                            fontWeight = FontWeight.SemiBold,
                        )
                    }
                    submitState.error?.let { error ->
                        Spacer(Modifier.height(8.dp))
                        Text(
                            text = stringResource(error.messageRes()),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.error,
                            modifier = Modifier.testTag("home.submitError"),
                        )
                        TextButton(onClick = onDismissSubmitError) {
                            Text(stringResource(R.string.account_dismiss))
                        }
                    }
                    Spacer(Modifier.height(10.dp))
                }
                Text(
                    text = stringResource(
                        if (signedIn) R.string.draft_vs_server_notice else R.string.local_draft_notice,
                    ),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.testTag("home.draftNotice"),
                )
            }
        }
        Spacer(Modifier.height(28.dp))
        Text(
            text = stringResource(R.string.recent_tasks),
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
        )
        Spacer(Modifier.height(12.dp))
        recentTasks()
    }
}

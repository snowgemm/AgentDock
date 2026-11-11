package com.slg.agentdock.ui.screens

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.slg.agentdock.R
import com.slg.agentdock.ui.tasks.TaskListUiState

@Composable
fun ActivityScreen(
    state: TaskListUiState,
    signedIn: Boolean,
    onOpen: (String) -> Unit,
    onRefresh: () -> Unit,
    onLoadMore: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .testTag("activity.screen")
            .padding(horizontal = 20.dp)
            .padding(top = 18.dp, bottom = 24.dp)
            .verticalScroll(rememberScrollState()),
    ) {
        Text(
            text = stringResource(R.string.activity_title),
            style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.SemiBold,
        )
        Spacer(Modifier.height(4.dp))
        Text(
            text = stringResource(R.string.activity_description),
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(16.dp))
        TaskListSection(
            state = state,
            signedIn = signedIn,
            onOpen = onOpen,
            onRefresh = onRefresh,
            onLoadMore = onLoadMore,
        )
    }
}

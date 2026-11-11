package com.slg.agentdock

import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.slg.agentdock.data.net.ApiError
import com.slg.agentdock.data.tasks.RemoteTask
import com.slg.agentdock.data.tasks.TaskStatus
import com.slg.agentdock.ui.screens.TaskListSection
import com.slg.agentdock.ui.tasks.TaskListUiState
import com.slg.agentdock.ui.theme.AgentDockTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class TaskListSectionTest {
    @get:Rule
    val composeRule = createComposeRule()

    private val task = RemoteTask("task-1", "Review the release", TaskStatus.QUEUED, 1L, 1L)

    private fun show(
        state: TaskListUiState,
        signedIn: Boolean = true,
        onOpen: (String) -> Unit = {},
        onRefresh: () -> Unit = {},
    ) {
        composeRule.setContent {
            AgentDockTheme {
                TaskListSection(
                    state = state,
                    signedIn = signedIn,
                    onOpen = onOpen,
                    onRefresh = onRefresh,
                    onLoadMore = {},
                )
            }
        }
    }

    @Test
    fun serverTasksShowAServerStatusAndOpenTheirDetail() {
        var opened: String? = null
        show(TaskListUiState(items = listOf(task), loadedOnce = true), onOpen = { opened = it })

        composeRule.onAllNodesWithTag("tasks.row").assertCountEquals(1)
        composeRule.onNodeWithTag("tasks.row").performClick()
        assertEquals("task-1", opened)
    }

    @Test
    fun signedOutUsersAreToldToSignInInsteadOfSeeingAnEmptyServerList() {
        show(TaskListUiState(), signedIn = false)
        composeRule.onAllNodesWithTag("tasks.row").assertCountEquals(0)
        composeRule.onNodeWithTag("tasks.list").assertIsDisplayed()
    }

    @Test
    fun offlineFailureOffersARetryWithoutLosingTheScreen() {
        var retries = 0
        show(TaskListUiState(error = ApiError.Offline, loadedOnce = true), onRefresh = { retries++ })

        composeRule.onNodeWithTag("tasks.error").assertIsDisplayed()
        composeRule.onNodeWithTag("tasks.retry").performClick()
        assertEquals(1, retries)
    }
}

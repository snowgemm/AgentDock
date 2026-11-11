package com.slg.agentdock

import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onNodeWithTag
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.slg.agentdock.data.tasks.RemoteTask
import com.slg.agentdock.data.tasks.RemoteTaskDetail
import com.slg.agentdock.data.tasks.StreamState
import com.slg.agentdock.data.tasks.TaskEvent
import com.slg.agentdock.data.tasks.TaskStatus
import com.slg.agentdock.ui.screens.TaskDetailScreen
import com.slg.agentdock.ui.tasks.TaskDetailUiState
import com.slg.agentdock.ui.theme.AgentDockTheme
import kotlinx.serialization.json.JsonObject
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class TaskDetailScreenTest {
    @get:Rule
    val composeRule = createComposeRule()

    private fun event(sequence: Long, type: String) =
        TaskEvent("e$sequence", sequence, type, JsonObject(emptyMap()), 1L)

    private fun show(state: TaskDetailUiState) {
        composeRule.setContent {
            AgentDockTheme { TaskDetailScreen(state = state, onRefresh = {}) }
        }
    }

    private val queued = RemoteTaskDetail(
        RemoteTask("t1", "Review the release", TaskStatus.QUEUED, 1L, 1L),
        prompt = "Check the checklist",
    )

    @Test
    fun queuedTaskIsLabelledAcceptedNotExecutingAndShowsItsTimeline() {
        show(
            TaskDetailUiState(
                detail = queued,
                events = listOf(event(1, "TASK_CREATED"), event(2, "STEP")),
                stream = StreamState.Live,
            ),
        )

        composeRule.onNodeWithTag("taskDetail.statusExplanation").assertIsDisplayed()
        composeRule.onAllNodesWithTag("timeline.row").assertCountEquals(2)
        composeRule.onNodeWithTag("stream.status").assertIsDisplayed()
    }

    @Test
    fun agentResultIsShownWithItsVerificationStatusFromTheTimeline() {
        val payload = kotlinx.serialization.json.Json.parseToJsonElement(
            """{"answer":"2 + 2 = 4","verified":true}""",
        ) as JsonObject
        show(
            TaskDetailUiState(
                detail = queued,
                events = listOf(TaskEvent("e5", 5, "AGENT_RESULT", payload, 1L)),
                stream = StreamState.Ended,
            ),
        )
        composeRule.onNodeWithTag("taskDetail.result").assertIsDisplayed()
        composeRule.onNodeWithTag("taskDetail.resultVerification").assertIsDisplayed()
    }

    @Test
    fun reconnectingStateIsShownInsteadOfPretendingToBeLive() {
        show(TaskDetailUiState(detail = queued, stream = StreamState.Reconnecting))
        composeRule.onNodeWithTag("stream.status").assertIsDisplayed()
    }
}

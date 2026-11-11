package com.slg.agentdock

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.slg.agentdock.data.tasks.Approval
import com.slg.agentdock.data.tasks.ApprovalRisk
import com.slg.agentdock.data.tasks.ApprovalStatus
import com.slg.agentdock.ui.screens.ApprovalCard
import com.slg.agentdock.ui.theme.AgentDockTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ApprovalCardTest {
    @get:Rule
    val composeRule = createComposeRule()

    private val approval = Approval(
        id = "ap-1", taskId = "t-1", tool = "test_send_note", target = "sandbox/alice",
        risk = ApprovalRisk.CONSEQUENTIAL, summary = "Send a note to sandbox/alice",
        keyArgs = listOf("body" to "hello"), digest = "a".repeat(64),
        status = ApprovalStatus.PENDING, expiresAtMs = System.currentTimeMillis() + 600_000L,
    )

    @Test
    fun showsTheExactActionAndRoutesExplicitApproveAndDenyDecisions() {
        val decisions = mutableListOf<String>()
        composeRule.setContent {
            AgentDockTheme {
                ApprovalCard(
                    approval = approval,
                    deciding = false,
                    onApprove = { decisions += "approve" },
                    onDeny = { decisions += "deny" },
                )
            }
        }

        listOf(
            "approval.effect", "approval.tool", "approval.target", "approval.risk",
            "approval.arg.body", "approval.expires", "approval.digest",
        ).forEach { composeRule.onNodeWithTag(it).assertIsDisplayed() }
        composeRule.onNodeWithTag("approval.approve").assertIsEnabled().performClick()
        composeRule.onNodeWithTag("approval.deny").performClick()
        assertEquals(listOf("approve", "deny"), decisions)
    }

    @Test
    fun buttonsAreDisabledWhileADecisionIsBeingSent() {
        composeRule.setContent {
            AgentDockTheme {
                ApprovalCard(approval = approval, deciding = true, onApprove = {}, onDeny = {})
            }
        }
        composeRule.onNodeWithTag("approval.approve").assertIsNotEnabled()
        composeRule.onNodeWithTag("approval.deny").assertIsNotEnabled()
    }
}

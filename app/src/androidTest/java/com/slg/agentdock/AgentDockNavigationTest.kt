
package com.slg.agentdock

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class AgentDockNavigationTest {
    @get:Rule
    val composeRule = createAndroidComposeRule<MainActivity>()

    @Test
    fun bottomNavigationOpensTabsAndSettings() {
        composeRule.onNodeWithTag("navigation.tabs").performClick()
        composeRule.onNodeWithTag("tabs.screen").assertIsDisplayed()

        composeRule.onNodeWithTag("navigation.settings").performClick()
        composeRule.onNodeWithTag("settings.screen").assertIsDisplayed()

        composeRule.onNodeWithTag("navigation.home").performClick()
        composeRule.onNodeWithTag("home.screen").assertIsDisplayed()
    }

    @Test
    fun settingsShowsSignInNotConfiguredWhenBuildHasNoProvider() {
        composeRule.onNodeWithTag("navigation.settings").performClick()
        composeRule.onNodeWithTag("account.notConfigured").assertIsDisplayed()
    }

    @Test
    fun settingsCanChangeThemeAccentTextSizeAndFeedback() {
        composeRule.onNodeWithTag("navigation.settings").performClick()
        composeRule.onNodeWithTag("settings.screen").assertIsDisplayed()

        composeRule.onNodeWithTag("settings.theme.light").performClick()
        composeRule.onNodeWithTag("settings.theme.light").assertIsSelected()

        composeRule.onNodeWithTag("settings.accent.blue").performClick()
        composeRule.onNodeWithTag("settings.accent.blue").assertIsSelected()

        composeRule.onNodeWithTag("settings.fontSize.1.15").performClick()
        composeRule.onNodeWithTag("settings.fontSize.1.15").assertIsSelected()

        composeRule.onNodeWithTag("settings.haptics").performScrollTo().performClick()
        composeRule.onNodeWithTag("settings.sound").performScrollTo().performClick()
    }

    @Test
    fun savingDraftOpensWorkspaceWithLocalStatus() {
        composeRule.onNodeWithTag("home.taskInput").performTextInput("Prepare a small project plan")
        composeRule.onNodeWithTag("home.saveDraft").assertIsEnabled().performClick()

        composeRule.onNodeWithTag("workspace.screen").assertIsDisplayed()
        composeRule.onNodeWithTag("workspace.taskInput").assertIsDisplayed()
        composeRule.onNodeWithTag("workspace.localDraftStatus").assertIsDisplayed()
    }
}

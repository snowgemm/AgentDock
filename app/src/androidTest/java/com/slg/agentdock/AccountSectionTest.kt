package com.slg.agentdock

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.slg.agentdock.ui.auth.AuthError
import com.slg.agentdock.ui.auth.AuthStatus
import com.slg.agentdock.ui.auth.AuthUiState
import com.slg.agentdock.ui.screens.AccountSection
import com.slg.agentdock.ui.theme.AgentDockTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class AccountSectionTest {
    @get:Rule
    val composeRule = createComposeRule()

    private fun show(state: AuthUiState, onSignIn: () -> Unit = {}, onSignOut: () -> Unit = {}) {
        composeRule.setContent {
            AgentDockTheme {
                AccountSection(
                    state = state,
                    onSignIn = onSignIn,
                    onSignOut = onSignOut,
                    onDismissError = {},
                )
            }
        }
    }

    @Test
    fun notConfiguredBuildExplainsWhySignInIsUnavailable() {
        show(AuthUiState(AuthStatus.NOT_CONFIGURED))

        composeRule.onNodeWithTag("account.notConfigured").assertIsDisplayed()
        composeRule.onNodeWithTag("account.signIn").assertDoesNotExist()
    }

    @Test
    fun signedOutStateOffersBrowserSignIn() {
        var signInRequests = 0
        show(AuthUiState(AuthStatus.SIGNED_OUT), onSignIn = { signInRequests++ })

        composeRule.onNodeWithTag("account.signIn").assertIsEnabled().performClick()
        assertEquals(1, signInRequests)
    }

    @Test
    fun signInIsDisabledWhileBrowserFlowIsPendingAndErrorsAreShown() {
        show(AuthUiState(AuthStatus.SIGNED_OUT, busy = true, error = AuthError.CALLBACK_REJECTED))

        composeRule.onNodeWithTag("account.signIn").assertIsNotEnabled()
        composeRule.onNodeWithTag("account.error").assertIsDisplayed()
    }

    @Test
    fun signedInStateOffersSignOut() {
        var signOutRequests = 0
        show(AuthUiState(AuthStatus.SIGNED_IN), onSignOut = { signOutRequests++ })

        composeRule.onNodeWithTag("account.signedIn").assertIsDisplayed()
        composeRule.onNodeWithTag("account.signOut").performClick()
        assertEquals(1, signOutRequests)
    }
}

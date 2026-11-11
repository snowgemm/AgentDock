package com.slg.agentdock.ui.screens

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.slg.agentdock.R
import com.slg.agentdock.ui.auth.AuthError
import com.slg.agentdock.ui.auth.AuthStatus
import com.slg.agentdock.ui.auth.AuthUiState

@Composable
fun AccountSection(
    state: AuthUiState,
    onSignIn: () -> Unit,
    onSignOut: () -> Unit,
    onDismissError: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(modifier = modifier.fillMaxWidth().testTag("account.section")) {
        Spacer(Modifier.height(22.dp))
        HorizontalDivider(color = MaterialTheme.colorScheme.outline)
        Spacer(Modifier.height(16.dp))
        Text(
            text = stringResource(R.string.account_title),
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
        )
        Spacer(Modifier.height(12.dp))

        when (state.status) {
            AuthStatus.NOT_CONFIGURED -> AccountMessage(
                title = stringResource(R.string.account_not_configured_title),
                body = stringResource(R.string.account_not_configured_body),
                tag = "account.notConfigured",
            )
            AuthStatus.RESTORING -> Text(
                text = stringResource(R.string.account_restoring),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.testTag("account.restoring"),
            )
            AuthStatus.SIGNED_OUT -> {
                AccountMessage(
                    title = stringResource(R.string.account_signed_out_title),
                    body = stringResource(R.string.account_signed_out_body),
                    tag = "account.signedOut",
                )
                Spacer(Modifier.height(12.dp))
                Button(
                    onClick = onSignIn,
                    enabled = !state.busy,
                    modifier = Modifier.fillMaxWidth().testTag("account.signIn"),
                ) {
                    Text(
                        stringResource(
                            if (state.busy) R.string.account_signing_in else R.string.account_sign_in,
                        ),
                    )
                }
            }
            AuthStatus.SIGNED_IN -> {
                AccountMessage(
                    title = stringResource(R.string.account_signed_in_title),
                    body = stringResource(R.string.account_signed_in_body),
                    tag = "account.signedIn",
                )
                Spacer(Modifier.height(12.dp))
                OutlinedButton(
                    onClick = onSignOut,
                    modifier = Modifier.fillMaxWidth().testTag("account.signOut"),
                ) {
                    Text(stringResource(R.string.account_sign_out))
                }
            }
        }

        state.error?.let { error ->
            Spacer(Modifier.height(12.dp))
            Row(
                modifier = Modifier.fillMaxWidth().testTag("account.error"),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = stringResource(error.messageRes()),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                    modifier = Modifier.weight(1f),
                )
                TextButton(onClick = onDismissError) {
                    Text(stringResource(R.string.account_dismiss))
                }
            }
        }
    }
}

@Composable
private fun AccountMessage(title: String, body: String, tag: String) {
    Column(modifier = Modifier.testTag(tag)) {
        Text(title, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Medium)
        Spacer(Modifier.height(4.dp))
        Text(
            text = body,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

private fun AuthError.messageRes(): Int = when (this) {
    AuthError.CALLBACK_REJECTED -> R.string.account_error_callback_rejected
    AuthError.PROVIDER_UNAVAILABLE -> R.string.account_error_provider_unavailable
    AuthError.TOKEN_REJECTED -> R.string.account_error_token_rejected
    AuthError.BACKEND_UNAVAILABLE -> R.string.account_error_backend_unavailable
    AuthError.ACCOUNT_UNAVAILABLE -> R.string.account_error_account_unavailable
    AuthError.SESSION_EXPIRED -> R.string.account_error_session_expired
    AuthError.UNEXPECTED -> R.string.account_error_unexpected
}

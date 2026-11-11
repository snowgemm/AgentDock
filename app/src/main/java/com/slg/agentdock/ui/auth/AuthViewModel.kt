package com.slg.agentdock.ui.auth

import android.content.Intent
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.slg.agentdock.data.auth.AuthApiException
import com.slg.agentdock.data.auth.AuthState
import com.slg.agentdock.data.auth.OidcException
import com.slg.agentdock.data.auth.OidcFailure
import com.slg.agentdock.data.auth.SessionManager
import com.slg.agentdock.data.auth.SignedOutReason
import com.slg.agentdock.data.auth.android.OidcClient
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

enum class AuthStatus { NOT_CONFIGURED, RESTORING, SIGNED_OUT, SIGNED_IN }

enum class AuthError {
    CALLBACK_REJECTED,
    PROVIDER_UNAVAILABLE,
    TOKEN_REJECTED,
    BACKEND_UNAVAILABLE,
    ACCOUNT_UNAVAILABLE,
    SESSION_EXPIRED,
    UNEXPECTED,
}

data class AuthUiState(
    val status: AuthStatus,
    val busy: Boolean = false,
    val error: AuthError? = null,
)

sealed interface AuthEvent {
    data class LaunchBrowser(val intent: Intent) : AuthEvent
}

/** Sign-in dependencies exist only when the build is configured for sign-in. */
class AuthViewModel(
    private val sessions: SessionManager?,
    private val oidc: OidcClient?,
) : ViewModel() {
    private data class Local(val busy: Boolean = false, val error: AuthError? = null)

    private val local = MutableStateFlow(Local())
    private val mutableEvents = MutableSharedFlow<AuthEvent>(extraBufferCapacity = 1)
    val events: SharedFlow<AuthEvent> = mutableEvents.asSharedFlow()

    val uiState: StateFlow<AuthUiState> =
        if (sessions == null || oidc == null) {
            MutableStateFlow(AuthUiState(AuthStatus.NOT_CONFIGURED)).asStateFlow()
        } else {
            combine(sessions.state, local) { auth, extra ->
                when (auth) {
                    AuthState.Restoring -> AuthUiState(AuthStatus.RESTORING)
                    is AuthState.SignedIn -> AuthUiState(AuthStatus.SIGNED_IN, extra.busy, extra.error)
                    is AuthState.SignedOut -> AuthUiState(
                        status = AuthStatus.SIGNED_OUT,
                        busy = extra.busy,
                        error = extra.error
                            ?: AuthError.SESSION_EXPIRED.takeIf { auth.reason == SignedOutReason.SessionExpired },
                    )
                }
            }.stateIn(viewModelScope, SharingStarted.Eagerly, AuthUiState(AuthStatus.RESTORING))
        }

    init {
        if (sessions != null) viewModelScope.launch { sessions.restore() }
    }

    fun startSignIn() {
        val client = oidc ?: return
        if (local.value.busy) return
        local.value = Local(busy = true)
        viewModelScope.launch {
            try {
                mutableEvents.emit(AuthEvent.LaunchBrowser(client.createAuthorizationIntent()))
            } catch (error: CancellationException) {
                throw error
            } catch (error: Exception) {
                fail(error)
            }
        }
    }

    fun onBrowserResult(data: Intent?) {
        val client = oidc ?: return
        val manager = sessions ?: return
        viewModelScope.launch {
            try {
                val externalToken = client.completeAuthorization(data)
                manager.signIn(externalToken)
                local.value = Local()
            } catch (error: CancellationException) {
                throw error
            } catch (error: Exception) {
                fail(error)
            }
        }
    }

    fun signOut() {
        val manager = sessions ?: return
        viewModelScope.launch { manager.signOut() }
    }

    fun dismissError() {
        local.update { it.copy(error = null) }
    }

    private fun fail(error: Exception) {
        val mapped = when (error) {
            is OidcException -> when (error.failure) {
                OidcFailure.Cancelled -> null
                OidcFailure.CallbackRejected -> AuthError.CALLBACK_REJECTED
                OidcFailure.ProviderUnavailable -> AuthError.PROVIDER_UNAVAILABLE
                OidcFailure.Unexpected -> AuthError.UNEXPECTED
            }
            is AuthApiException.Forbidden -> AuthError.ACCOUNT_UNAVAILABLE
            is AuthApiException.Unauthorized -> AuthError.TOKEN_REJECTED
            is AuthApiException.Unavailable -> AuthError.BACKEND_UNAVAILABLE
            is AuthApiException.Protocol -> AuthError.BACKEND_UNAVAILABLE
            else -> AuthError.UNEXPECTED
        }
        local.value = Local(busy = false, error = mapped)
    }

    class Factory(
        private val sessions: SessionManager?,
        private val oidc: OidcClient?,
    ) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T {
            require(modelClass.isAssignableFrom(AuthViewModel::class.java)) {
                "Unknown ViewModel class: ${modelClass.name}"
            }
            return AuthViewModel(sessions, oidc) as T
        }
    }
}

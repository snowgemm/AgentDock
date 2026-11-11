package com.slg.agentdock.data.auth

enum class SignedOutReason { Initial, UserRequested, SessionExpired }

sealed interface AuthState {
    data object Restoring : AuthState

    data class SignedOut(val reason: SignedOutReason) : AuthState

    data class SignedIn(
        val userId: String,
        val tenantId: String,
        val sessionExpiresAtMs: Long,
    ) : AuthState
}

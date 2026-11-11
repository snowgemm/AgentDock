package com.slg.agentdock.data.auth

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** Wire format of POST /api/v1/auth/session and /session/refresh. */
@Serializable
data class SessionResponseDto(
    @SerialName("access_token") val accessToken: String,
    @SerialName("token_type") val tokenType: String = "Bearer",
    @SerialName("expires_in") val expiresIn: Long,
    @SerialName("refresh_token") val refreshToken: String,
    @SerialName("session_expires_at") val sessionExpiresAt: String,
    @SerialName("session_id") val sessionId: String,
    @SerialName("user_id") val userId: String,
    @SerialName("tenant_id") val tenantId: String,
) {
    override fun toString(): String = "SessionResponseDto(session=$sessionId)"
}

@Serializable
data class RefreshRequestDto(@SerialName("refresh_token") val refreshToken: String) {
    override fun toString(): String = "RefreshRequestDto()"
}

sealed class AuthApiException(message: String, cause: Throwable? = null) : Exception(message, cause) {
    /** 401: the supplied credential is invalid, expired or was already used. */
    class Unauthorized : AuthApiException("Credential rejected by the server.")

    /** 403: the account is unavailable for sign-in. */
    class Forbidden : AuthApiException("Account unavailable.")

    /** Network failure, 429 or a 5xx response. Retrying later may succeed. */
    class Unavailable(val statusCode: Int?, cause: Throwable? = null) :
        AuthApiException("Server unavailable (status=$statusCode).", cause)

    /** The server answered successfully with something this client cannot use. */
    class Protocol(cause: Throwable? = null) : AuthApiException("Unexpected server response.", cause)
}

interface AuthApi {
    /** Exchanges a verified external OIDC access token for an AgentDock session. */
    suspend fun createSession(externalAccessToken: String): SessionResponseDto

    suspend fun refresh(refreshToken: String): SessionResponseDto

    suspend fun logout(accessToken: String)
}

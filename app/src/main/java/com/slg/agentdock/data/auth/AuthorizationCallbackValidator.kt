package com.slg.agentdock.data.auth

/** Plain facts extracted from the AppAuth request that started the flow. */
data class CallbackRequestFacts(
    val state: String?,
    val clientId: String,
    val redirectUri: String,
    val codeChallengeMethod: String?,
)

/** Plain facts extracted from the browser redirect. */
data class CallbackResponseFacts(
    val state: String?,
    val authorizationCode: String?,
    val error: String?,
)

enum class CallbackRejection {
    ProviderError,
    MissingCode,
    MissingState,
    StateMismatch,
    RedirectMismatch,
    ClientMismatch,
    PkceNotUsed,
}

/**
 * Defence in depth on top of AppAuth's own state check: the redirect must answer the
 * exact request this app made (state, client, redirect URI) and PKCE S256 must be on.
 * Returns null when the callback is acceptable.
 */
fun validateAuthorizationCallback(
    config: AuthConfig,
    request: CallbackRequestFacts,
    response: CallbackResponseFacts,
): CallbackRejection? {
    if (!response.error.isNullOrEmpty()) return CallbackRejection.ProviderError
    if (request.redirectUri != config.redirectUri) return CallbackRejection.RedirectMismatch
    if (request.clientId != config.clientId) return CallbackRejection.ClientMismatch
    if (request.codeChallengeMethod != "S256") return CallbackRejection.PkceNotUsed
    if (request.state.isNullOrEmpty() || response.state.isNullOrEmpty()) return CallbackRejection.MissingState
    if (!constantTimeEquals(request.state, response.state)) return CallbackRejection.StateMismatch
    if (response.authorizationCode.isNullOrBlank()) return CallbackRejection.MissingCode
    return null
}

private fun constantTimeEquals(a: String, b: String): Boolean =
    java.security.MessageDigest.isEqual(a.toByteArray(Charsets.UTF_8), b.toByteArray(Charsets.UTF_8))

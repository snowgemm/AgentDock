package com.slg.agentdock.data.auth

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class AuthorizationCallbackValidatorTest {
    private val config = (
        AuthConfig.parse(
            issuer = "https://id.example.test",
            clientId = "agentdock-android",
            redirectUri = "com.slg.agentdock:/oauth2redirect",
            scope = "openid",
            audience = "",
            apiBaseUrl = "https://api.example.test",
        ) as AuthConfigResult.Configured
        ).config

    private val request = CallbackRequestFacts(
        state = "state-123",
        clientId = "agentdock-android",
        redirectUri = "com.slg.agentdock:/oauth2redirect",
        codeChallengeMethod = "S256",
    )
    private val response = CallbackResponseFacts(state = "state-123", authorizationCode = "code", error = null)

    @Test
    fun acceptsMatchingCallback() {
        assertNull(validateAuthorizationCallback(config, request, response))
    }

    @Test
    fun rejectsStateMismatchAndMissingState() {
        assertEquals(
            CallbackRejection.StateMismatch,
            validateAuthorizationCallback(config, request, response.copy(state = "attacker")),
        )
        assertEquals(
            CallbackRejection.MissingState,
            validateAuthorizationCallback(config, request, response.copy(state = null)),
        )
        assertEquals(
            CallbackRejection.MissingState,
            validateAuthorizationCallback(config, request.copy(state = ""), response.copy(state = "")),
        )
    }

    @Test
    fun rejectsProviderErrorAndMissingCode() {
        assertEquals(
            CallbackRejection.ProviderError,
            validateAuthorizationCallback(config, request, response.copy(error = "access_denied")),
        )
        assertEquals(
            CallbackRejection.MissingCode,
            validateAuthorizationCallback(config, request, response.copy(authorizationCode = " ")),
        )
    }

    @Test
    fun rejectsForeignRedirectClientAndMissingPkce() {
        assertEquals(
            CallbackRejection.RedirectMismatch,
            validateAuthorizationCallback(config, request.copy(redirectUri = "evil.app:/cb"), response),
        )
        assertEquals(
            CallbackRejection.ClientMismatch,
            validateAuthorizationCallback(config, request.copy(clientId = "other"), response),
        )
        assertEquals(
            CallbackRejection.PkceNotUsed,
            validateAuthorizationCallback(config, request.copy(codeChallengeMethod = "plain"), response),
        )
        assertEquals(
            CallbackRejection.PkceNotUsed,
            validateAuthorizationCallback(config, request.copy(codeChallengeMethod = null), response),
        )
    }
}

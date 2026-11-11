package com.slg.agentdock.data.auth.android

import android.content.Context
import android.content.Intent
import android.net.Uri
import com.slg.agentdock.data.auth.AuthConfig
import com.slg.agentdock.data.auth.CallbackRequestFacts
import com.slg.agentdock.data.auth.CallbackResponseFacts
import com.slg.agentdock.data.auth.OidcException
import com.slg.agentdock.data.auth.OidcFailure
import com.slg.agentdock.data.auth.validateAuthorizationCallback
import kotlinx.coroutines.suspendCancellableCoroutine
import net.openid.appauth.AuthorizationException
import net.openid.appauth.AuthorizationRequest
import net.openid.appauth.AuthorizationResponse
import net.openid.appauth.AuthorizationService
import net.openid.appauth.AuthorizationServiceConfiguration
import net.openid.appauth.ResponseTypeValues
import kotlin.coroutines.resume

/**
 * AppAuth-Android implementation (RFC 8252 native app flow, PKCE S256, system browser).
 * AppAuth generates `state`, `nonce` and the PKCE verifier and rejects a redirect whose
 * state differs from the request; [validateAuthorizationCallback] re-checks that and the
 * redirect/client binding. Public client: no client secret exists anywhere.
 */
class AppAuthOidcClient(
    context: Context,
    private val config: AuthConfig,
) : OidcClient {
    private val appContext = context.applicationContext
    private var service: AuthorizationService? = null

    override suspend fun createAuthorizationIntent(): Intent {
        val serviceConfiguration = fetchConfiguration()
        val builder = AuthorizationRequest.Builder(
            serviceConfiguration,
            config.clientId,
            ResponseTypeValues.CODE,
            Uri.parse(config.redirectUri),
        ).setScope(config.scope)
        config.audience?.let { builder.setAdditionalParameters(mapOf("audience" to it)) }
        val request = builder.build()

        disposeService()
        val newService = AuthorizationService(appContext)
        service = newService
        return try {
            newService.getAuthorizationRequestIntent(request)
        } catch (error: RuntimeException) {
            disposeService()
            throw OidcException(OidcFailure.Unexpected, error)
        }
    }

    override suspend fun completeAuthorization(result: Intent?): String {
        try {
            if (result == null) throw OidcException(OidcFailure.Cancelled)
            val response = AuthorizationResponse.fromIntent(result)
            val failure = AuthorizationException.fromIntent(result)
            if (response == null) {
                throw OidcException(
                    if (failure?.type == AuthorizationException.TYPE_GENERAL_ERROR &&
                        failure.code == AuthorizationException.GeneralErrors.USER_CANCELED_AUTH_FLOW.code
                    ) {
                        OidcFailure.Cancelled
                    } else {
                        OidcFailure.CallbackRejected
                    },
                    failure,
                )
            }
            val rejection = validateAuthorizationCallback(
                config,
                CallbackRequestFacts(
                    state = response.request.state,
                    clientId = response.request.clientId,
                    redirectUri = response.request.redirectUri.toString(),
                    codeChallengeMethod = response.request.codeVerifierChallengeMethod,
                ),
                CallbackResponseFacts(
                    state = response.state,
                    authorizationCode = response.authorizationCode,
                    error = failure?.error,
                ),
            )
            if (rejection != null) throw OidcException(OidcFailure.CallbackRejected)
            return exchangeCode(response)
        } finally {
            disposeService()
        }
    }

    private suspend fun fetchConfiguration(): AuthorizationServiceConfiguration =
        suspendCancellableCoroutine { continuation ->
            AuthorizationServiceConfiguration.fetchFromIssuer(Uri.parse(config.issuer)) { fetched, error ->
                val failure = when {
                    fetched == null -> OidcException(OidcFailure.ProviderUnavailable, error)
                    // Mix-up defence: the discovery document must name exactly this issuer.
                    fetched.discoveryDoc?.issuer != config.issuer ->
                        OidcException(OidcFailure.ProviderUnavailable)
                    else -> null
                }
                if (!continuation.isActive) return@fetchFromIssuer
                if (failure != null || fetched == null) {
                    continuation.resumeWith(Result.failure(failure ?: OidcException(OidcFailure.Unexpected)))
                } else {
                    continuation.resume(fetched)
                }
            }
        }

    private suspend fun exchangeCode(response: AuthorizationResponse): String {
        val activeService = service ?: throw OidcException(OidcFailure.Unexpected)
        val tokenRequest = response.createTokenExchangeRequest()
        return suspendCancellableCoroutine { continuation ->
            activeService.performTokenRequest(tokenRequest) { tokenResponse, error ->
                if (!continuation.isActive) return@performTokenRequest
                val accessToken = tokenResponse?.accessToken
                val isBearer = tokenResponse?.tokenType?.equals("Bearer", ignoreCase = true) ?: true
                if (accessToken.isNullOrBlank() || !isBearer) {
                    continuation.resumeWith(
                        Result.failure(OidcException(OidcFailure.ProviderUnavailable, error)),
                    )
                } else {
                    continuation.resume(accessToken)
                }
            }
        }
    }

    private fun disposeService() {
        service?.dispose()
        service = null
    }
}

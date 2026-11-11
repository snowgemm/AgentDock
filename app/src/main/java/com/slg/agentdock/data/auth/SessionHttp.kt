package com.slg.agentdock.data.auth

import kotlinx.coroutines.runBlocking
import okhttp3.Authenticator
import okhttp3.Interceptor
import okhttp3.Request
import okhttp3.Response
import okhttp3.Route

/**
 * The only place a session access token is attached to API requests. OkHttp runs
 * interceptors on its own worker threads, so blocking here never touches the UI thread.
 * Refresh coordination lives in [SessionManager].
 */
class BearerInterceptor(private val sessions: SessionManager) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val token = runBlocking { sessions.accessToken() } ?: throw SignedOutException()
        return chain.proceed(
            chain.request().newBuilder().header("Authorization", "Bearer $token").build(),
        )
    }
}

/**
 * Handles a 401 from the API: refreshes (single-flight) and retries the request at
 * most once. A second 401 for the same call is returned to the caller unchanged.
 */
class SessionAuthenticator(private val sessions: SessionManager) : Authenticator {
    override fun authenticate(route: Route?, response: Response): Request? {
        if (response.priorResponse != null) return null
        val rejected = response.request.header("Authorization")
            ?.removePrefix("Bearer ")
            ?.takeIf { it.isNotBlank() }
            ?: return null
        val fresh = runBlocking { sessions.accessTokenAfterRejection(rejected) } ?: return null
        if (fresh == rejected) return null
        return response.request.newBuilder().header("Authorization", "Bearer $fresh").build()
    }
}

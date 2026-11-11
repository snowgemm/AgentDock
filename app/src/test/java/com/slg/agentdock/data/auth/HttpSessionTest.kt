package com.slg.agentdock.data.auth

import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.Json
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import okhttp3.OkHttpClient
import okhttp3.Request
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.IOException

class HttpSessionTest {
    private val json = Json { ignoreUnknownKeys = true }
    private lateinit var server: MockWebServer
    private lateinit var authApi: HttpAuthApi

    private fun sessionJson(access: String, refresh: String) = """
        {"access_token":"$access","token_type":"Bearer","expires_in":900,"refresh_token":"$refresh",
         "session_expires_at":"2030-01-01T00:00:00.000000Z","session_id":"s1","user_id":"u1","tenant_id":"t1",
         "unknown_future_field":true}
    """.trimIndent()

    @Before
    fun setUp() {
        server = MockWebServer().also { it.start() }
        authApi = HttpAuthApi(OkHttpClient(), server.url("/"), json)
    }

    @After
    fun tearDown() {
        server.close()
    }

    @Test
    fun createSessionSendsTheExternalTokenOnlyAsBearerHeader() = runTest {
        server.enqueue(MockResponse.Builder().code(201).body(sessionJson("a1", "r1")).build())

        val session = authApi.createSession("external-jwt")

        val recorded = server.takeRequest()
        assertEquals("POST", recorded.method)
        assertEquals("/api/v1/auth/session", recorded.url.encodedPath)
        assertEquals("Bearer external-jwt", recorded.headers["Authorization"])
        assertEquals("", recorded.url.query ?: "")
        assertEquals("a1", session.accessToken)
    }

    @Test
    fun refreshPostsTheTokenInTheBodyNotTheUrl() = runTest {
        server.enqueue(MockResponse.Builder().code(200).body(sessionJson("a2", "r2")).build())

        authApi.refresh("refresh-token-0123456789012345678901234567")

        val recorded = server.takeRequest()
        assertEquals("/api/v1/auth/session/refresh", recorded.url.encodedPath)
        assertNull(recorded.headers["Authorization"])
        assertTrue(recorded.body!!.utf8().contains("\"refresh_token\":\"refresh-token-0123"))
        assertTrue(recorded.url.toString().none { false } && !recorded.url.toString().contains("refresh-token"))
    }

    @Test
    fun mapsStatusCodesToTypedFailures() = runTest {
        server.enqueue(MockResponse.Builder().code(401).build())
        server.enqueue(MockResponse.Builder().code(403).build())
        server.enqueue(MockResponse.Builder().code(503).build())
        server.enqueue(MockResponse.Builder().code(200).body("{not json").build())

        assertTrue(runCatching { authApi.refresh("x".repeat(40)) }.exceptionOrNull() is AuthApiException.Unauthorized)
        assertTrue(runCatching { authApi.createSession("t") }.exceptionOrNull() is AuthApiException.Forbidden)
        assertTrue(runCatching { authApi.createSession("t") }.exceptionOrNull() is AuthApiException.Unavailable)
        assertTrue(runCatching { authApi.createSession("t") }.exceptionOrNull() is AuthApiException.Protocol)
    }

    @Test
    fun logoutUsesTheProvidedAccessToken() = runTest {
        server.enqueue(MockResponse.Builder().code(204).build())
        authApi.logout("access-xyz")
        val recorded = server.takeRequest()
        assertEquals("/api/v1/auth/session/logout", recorded.url.encodedPath)
        assertEquals("Bearer access-xyz", recorded.headers["Authorization"])
    }

    // --- interceptor + authenticator against a protected endpoint ---

    private fun apiClient(manager: SessionManager) = OkHttpClient.Builder()
        .addInterceptor(BearerInterceptor(manager))
        .authenticator(SessionAuthenticator(manager))
        .build()

    private suspend fun signedIn(api: FakeAuthApi): SessionManager {
        val manager = SessionManager(FakeSessionStore(), api)
        manager.signIn("external")
        return manager
    }

    private fun protectedRequest() = Request.Builder().url(server.url("/api/v1/tasks")).build()

    @Test
    fun unauthorizedResponseIsRetriedExactlyOnceWithTheRefreshedToken() = runTest {
        val fake = FakeAuthApi()
        val client = apiClient(signedIn(fake))
        server.enqueue(MockResponse.Builder().code(401).build())
        server.enqueue(MockResponse.Builder().code(200).body("ok").build())

        val response = client.newCall(protectedRequest()).execute()

        assertEquals(200, response.code)
        assertEquals(1, fake.refreshCalls)
        assertEquals("Bearer access-1", server.takeRequest().headers["Authorization"])
        assertEquals("Bearer access-2", server.takeRequest().headers["Authorization"])
        assertEquals(2, server.requestCount)
    }

    @Test
    fun secondUnauthorizedIsReturnedWithoutLooping() = runTest {
        val fake = FakeAuthApi()
        val client = apiClient(signedIn(fake))
        server.enqueue(MockResponse.Builder().code(401).build())
        server.enqueue(MockResponse.Builder().code(401).build())

        val response = client.newCall(protectedRequest()).execute()

        assertEquals(401, response.code)
        assertEquals(1, fake.refreshCalls)
        assertEquals(2, server.requestCount)
    }

    @Test
    fun refreshRejectionStopsTheRetryAndEndsTheSession() = runTest {
        val fake = FakeAuthApi()
        val manager = signedIn(fake)
        fake.refreshResult = { throw AuthApiException.Unauthorized() }
        val client = apiClient(manager)
        server.enqueue(MockResponse.Builder().code(401).build())

        val response = client.newCall(protectedRequest()).execute()

        assertEquals(401, response.code)
        assertEquals(1, server.requestCount)
        assertEquals(AuthState.SignedOut(SignedOutReason.SessionExpired), manager.state.value)
    }

    @Test
    fun signedOutRequestsFailBeforeReachingTheNetwork() = runTest {
        val manager = SessionManager(FakeSessionStore(), FakeAuthApi())
        manager.restore()
        val client = apiClient(manager)

        val failure = runCatching { client.newCall(protectedRequest()).execute() }.exceptionOrNull()

        assertTrue(failure is SignedOutException || failure is IOException)
        assertEquals(0, server.requestCount)
    }
}

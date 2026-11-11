package com.slg.agentdock.data.auth

import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.yield
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class FakeSessionStore(var stored: StoredSession? = null) : SessionStore {
    var clears = 0
    override suspend fun load() = stored
    override suspend fun save(session: StoredSession) {
        stored = session
    }

    override suspend fun clear() {
        stored = null
        clears++
    }
}

class FakeAuthApi : AuthApi {
    var createCalls = 0
    var refreshCalls = 0
    var logoutTokens = mutableListOf<String>()
    var createResult: () -> SessionResponseDto = { dto("access-1", "refresh-1") }
    var refreshResult: (String) -> SessionResponseDto = { dto("access-${refreshCalls + 1}", "refresh-${refreshCalls + 1}") }
    var logoutResult: (String) -> Unit = { }

    override suspend fun createSession(externalAccessToken: String): SessionResponseDto {
        createCalls++
        return createResult()
    }

    override suspend fun refresh(refreshToken: String): SessionResponseDto {
        refreshCalls++
        yield() // let concurrent callers pile up behind the manager's mutex
        return refreshResult(refreshToken)
    }

    override suspend fun logout(accessToken: String) {
        logoutTokens += accessToken
        logoutResult(accessToken)
    }

    companion object {
        fun dto(access: String, refresh: String, expiresIn: Long = 900) = SessionResponseDto(
            accessToken = access,
            expiresIn = expiresIn,
            refreshToken = refresh,
            sessionExpiresAt = "2030-01-01T00:00:00Z",
            sessionId = "session",
            userId = "user",
            tenantId = "tenant",
        )
    }
}

class SessionManagerTest {
    private var now = 1_000_000_000_000L
    private val api = FakeAuthApi()
    private val store = FakeSessionStore()
    private fun manager() = SessionManager(store, api, clock = { now }, refreshSkewMs = 30_000)

    private suspend fun signedInManager(): SessionManager = manager().also { it.signIn("external-token") }

    @Test
    fun signInPersistsSessionAndPublishesState() = runTest {
        val manager = signedInManager()
        assertEquals("access-1", manager.accessToken())
        assertEquals("access-1", store.stored?.accessToken)
        assertTrue(manager.state.value is AuthState.SignedIn)
    }

    @Test
    fun restoreWithNoSessionIsSignedOut() = runTest {
        val manager = manager()
        manager.restore()
        assertEquals(AuthState.SignedOut(SignedOutReason.Initial), manager.state.value)
        assertNull(manager.accessToken())
    }

    @Test
    fun restoreDropsAnExpiredSessionWithoutNetwork() = runTest {
        store.stored = StoredSession("a", "r", now + 1000, now - 1, "u", "t", "s")
        val manager = manager()
        manager.restore()
        assertEquals(AuthState.SignedOut(SignedOutReason.SessionExpired), manager.state.value)
        assertNull(store.stored)
        assertEquals(0, api.refreshCalls)
    }

    @Test
    fun concurrentExpiredRequestsShareOneRefresh() = runTest(StandardTestDispatcher()) {
        val manager = signedInManager()
        now += 900_000L // access token expired, session still valid

        val tokens = (1..8).map { async { manager.accessToken() } }.awaitAll()

        assertEquals(1, api.refreshCalls)
        assertEquals(setOf("access-2"), tokens.toSet())
        assertEquals("refresh-2", store.stored?.refreshToken)
    }

    @Test
    fun rejectedTokenAlreadyRotatedByAnotherCallerDoesNotRefreshAgain() = runTest {
        val manager = signedInManager()
        now += 900_000L
        val first = manager.accessTokenAfterRejection("access-1")
        val second = manager.accessTokenAfterRejection("access-1")

        assertEquals("access-2", first)
        assertEquals("access-2", second)
        assertEquals(1, api.refreshCalls)
    }

    @Test
    fun refreshRejectionEndsTheSessionAndClearsCredentials() = runTest {
        val manager = signedInManager()
        now += 900_000L
        api.refreshResult = { throw AuthApiException.Unauthorized() }

        assertNull(manager.accessToken())
        assertEquals(AuthState.SignedOut(SignedOutReason.SessionExpired), manager.state.value)
        assertNull(store.stored)
        assertNull(manager.accessToken())
        assertEquals(1, api.refreshCalls)
    }

    @Test
    fun transientRefreshFailureKeepsTheSession() = runTest {
        val manager = signedInManager()
        now += 900_000L
        api.refreshResult = { throw AuthApiException.Unavailable(503) }

        val failure = runCatching { manager.accessToken() }.exceptionOrNull()
        assertTrue(failure is SessionUnavailableException)
        assertTrue(manager.state.value is AuthState.SignedIn)
        assertEquals("refresh-1", store.stored?.refreshToken)

        api.refreshResult = { FakeAuthApi.dto("access-9", "refresh-9") }
        assertEquals("access-9", manager.accessToken())
    }

    @Test
    fun freshTokenIsNotRefreshedUnlessRejected() = runTest {
        val manager = signedInManager()
        assertEquals("access-1", manager.accessToken())
        assertEquals(0, api.refreshCalls)
    }

    @Test
    fun malformedSessionResponseIsAProtocolError() = runTest {
        api.createResult = { FakeAuthApi.dto("a", "r").copy(sessionExpiresAt = "not-a-date") }
        val manager = manager()
        val failure = runCatching { manager.signIn("x") }.exceptionOrNull()
        assertTrue(failure is AuthApiException.Protocol)
        assertNull(store.stored)
    }

    @Test
    fun signOutClearsLocallyBeforeRevokingRemotely() = runTest {
        val manager = signedInManager()
        var storedWhenRevoking: StoredSession? = store.stored
        api.logoutResult = { storedWhenRevoking = store.stored }

        val result = manager.signOut()

        assertEquals(RevocationResult.Revoked, result)
        assertNull(storedWhenRevoking)
        assertNull(manager.accessToken())
        assertEquals(AuthState.SignedOut(SignedOutReason.UserRequested), manager.state.value)
        assertEquals(listOf("access-1"), api.logoutTokens)
    }

    @Test
    fun signOutSucceedsLocallyWhenRevocationFails() = runTest {
        val manager = signedInManager()
        api.logoutResult = { throw AuthApiException.Unavailable(null) }

        assertEquals(RevocationResult.Failed, manager.signOut())
        assertNull(store.stored)
        assertEquals(AuthState.SignedOut(SignedOutReason.UserRequested), manager.state.value)
    }

    @Test
    fun signOutRetriesRevocationOnceWithARenewedToken() = runTest {
        val manager = signedInManager()
        api.logoutResult = { token -> if (token == "access-1") throw AuthApiException.Unauthorized() }

        assertEquals(RevocationResult.Revoked, manager.signOut())
        assertEquals(listOf("access-1", "access-2"), api.logoutTokens)
    }

    @Test
    fun signOutWithoutSessionHasNothingToRevoke() = runTest {
        val manager = manager()
        manager.restore()
        assertEquals(RevocationResult.NothingToRevoke, manager.signOut())
        assertEquals(0, api.logoutTokens.size)
    }
}

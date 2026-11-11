package com.slg.agentdock.data.auth

import com.slg.agentdock.data.net.parseIsoInstantMillis
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.io.IOException

/** Refreshing the session failed for a reason that is not a credential rejection. */
class SessionUnavailableException(cause: Throwable?) : IOException("Session refresh unavailable.", cause)

/** No credentials are available; the user must sign in. */
class SignedOutException : IOException("Not signed in.")

enum class RevocationResult { NothingToRevoke, Revoked, Failed }

/**
 * Owns the AgentDock session. All credential changes happen under one mutex so a
 * burst of expired-token requests produces exactly one refresh (refresh tokens are
 * single-use server-side and a concurrent second use would be treated as replay).
 */
class SessionManager(
    private val store: SessionStore,
    private val api: AuthApi,
    private val clock: () -> Long = System::currentTimeMillis,
    private val refreshSkewMs: Long = DEFAULT_REFRESH_SKEW_MS,
) {
    private val mutex = Mutex()

    @Volatile
    private var cached: StoredSession? = null
    private val mutableState = MutableStateFlow<AuthState>(AuthState.Restoring)
    val state: StateFlow<AuthState> = mutableState.asStateFlow()

    suspend fun restore() {
        mutex.withLock {
            val loaded = store.load()
            when {
                loaded == null -> {
                    cached = null
                    mutableState.value = AuthState.SignedOut(SignedOutReason.Initial)
                }
                clock() >= loaded.sessionExpiresAtMs -> expireLocked()
                else -> adoptLocked(loaded)
            }
        }
    }

    /** @throws AuthApiException when the backend rejects or cannot serve the exchange. */
    suspend fun signIn(externalAccessToken: String) {
        mutex.withLock {
            val next = api.createSession(externalAccessToken).toStored()
            store.save(next)
            adoptLocked(next)
        }
    }

    /**
     * Returns a usable access token, refreshing first when it is close to expiry.
     * Returns null when signed out or when the session just ended.
     * @throws SessionUnavailableException when a refresh could not be attempted or completed.
     */
    suspend fun accessToken(): String? {
        val snapshot = cached ?: return null
        if (!needsRefresh(snapshot)) return snapshot.accessToken
        return refreshIfStillCurrent(snapshot.accessToken, force = false)
    }

    /**
     * Called after the server rejected [rejectedToken]. If another caller already
     * rotated the credentials the new token is returned without another refresh.
     */
    suspend fun accessTokenAfterRejection(rejectedToken: String): String? =
        refreshIfStillCurrent(rejectedToken, force = true)

    /**
     * Clears local credentials immediately, then revokes the session remotely on a
     * best-effort basis. Local sign-out never depends on the network.
     */
    suspend fun signOut(): RevocationResult {
        val previous = mutex.withLock {
            val current = cached
            cached = null
            runCatching { store.clear() }
            mutableState.value = AuthState.SignedOut(SignedOutReason.UserRequested)
            current
        } ?: return RevocationResult.NothingToRevoke
        return revokeRemotely(previous)
    }

    private suspend fun revokeRemotely(session: StoredSession): RevocationResult {
        try {
            api.logout(session.accessToken)
            return RevocationResult.Revoked
        } catch (_: AuthApiException.Unauthorized) {
            // The access token may simply have expired; try once with a fresh one.
        } catch (_: AuthApiException) {
            return RevocationResult.Failed
        }
        return try {
            val renewed = api.refresh(session.refreshToken)
            api.logout(renewed.accessToken)
            RevocationResult.Revoked
        } catch (_: AuthApiException) {
            RevocationResult.Failed
        }
    }

    private suspend fun refreshIfStillCurrent(observedToken: String, force: Boolean): String? {
        return mutex.withLock {
            val current = cached ?: return@withLock null
            if (clock() >= current.sessionExpiresAtMs) {
                expireLocked()
                return@withLock null
            }
            if (current.accessToken != observedToken) return@withLock current.accessToken
            if (!force && !needsRefresh(current)) return@withLock current.accessToken

            val renewed = try {
                api.refresh(current.refreshToken).toStored()
            } catch (_: AuthApiException.Unauthorized) {
                expireLocked()
                return@withLock null
            } catch (_: AuthApiException.Forbidden) {
                expireLocked()
                return@withLock null
            } catch (error: AuthApiException) {
                throw SessionUnavailableException(error)
            }
            // Hold the rotated credentials in memory first: the old refresh token is
            // already spent, so a failed disk write must not lose the session.
            adoptLocked(renewed)
            runCatching { store.save(renewed) }
            renewed.accessToken
        }
    }

    private fun needsRefresh(session: StoredSession): Boolean =
        session.accessExpiresAtMs - clock() <= refreshSkewMs

    private suspend fun expireLocked() {
        cached = null
        runCatching { store.clear() }
        mutableState.value = AuthState.SignedOut(SignedOutReason.SessionExpired)
    }

    private fun adoptLocked(session: StoredSession) {
        cached = session
        mutableState.value = AuthState.SignedIn(session.userId, session.tenantId, session.sessionExpiresAtMs)
    }

    private fun SessionResponseDto.toStored(): StoredSession {
        val now = clock()
        val sessionExpiry = parseIsoInstantMillis(sessionExpiresAt)
            ?: throw AuthApiException.Protocol()
        if (expiresIn <= 0 || accessToken.isBlank() || refreshToken.isBlank()) {
            throw AuthApiException.Protocol()
        }
        return StoredSession(
            accessToken = accessToken,
            refreshToken = refreshToken,
            accessExpiresAtMs = now + expiresIn * 1_000L,
            sessionExpiresAtMs = sessionExpiry,
            userId = userId,
            tenantId = tenantId,
            sessionId = sessionId,
        )
    }

    private companion object {
        const val DEFAULT_REFRESH_SKEW_MS = 30_000L
    }
}

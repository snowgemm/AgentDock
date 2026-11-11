package com.slg.agentdock.data.auth

import kotlinx.serialization.Serializable

/** AgentDock's own opaque session credentials (never the external OIDC tokens). */
@Serializable
data class StoredSession(
    val accessToken: String,
    val refreshToken: String,
    val accessExpiresAtMs: Long,
    val sessionExpiresAtMs: Long,
    val userId: String,
    val tenantId: String,
    val sessionId: String,
) {
    // Keep credentials out of logs and crash reports even if an instance is printed.
    override fun toString(): String = "StoredSession(session=$sessionId)"
}

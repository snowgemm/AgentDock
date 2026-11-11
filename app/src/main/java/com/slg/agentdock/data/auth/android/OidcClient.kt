package com.slg.agentdock.data.auth.android

import android.content.Intent

/** Browser-based Authorization Code + PKCE sign-in against the configured provider. */
interface OidcClient {
    /**
     * Discovers the provider and returns the intent that opens the system browser
     * (Custom Tabs). Never a WebView.
     * @throws com.slg.agentdock.data.auth.OidcException
     */
    suspend fun createAuthorizationIntent(): Intent

    /**
     * Validates the redirect result, exchanges the code (PKCE) and returns the external
     * OIDC access token. That token is only forwarded once to AgentDock's session
     * endpoint and is never stored.
     * @throws com.slg.agentdock.data.auth.OidcException
     */
    suspend fun completeAuthorization(result: Intent?): String
}

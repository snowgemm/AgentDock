package com.slg.agentdock.data.auth

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AuthConfigTest {
    private fun parse(
        issuer: String = "https://id.example.test/realm",
        clientId: String = "agentdock-android",
        redirectUri: String = "com.slg.agentdock:/oauth2redirect",
        scope: String = "openid agentdock.api",
        audience: String = "",
        apiBaseUrl: String = "https://api.example.test",
    ) = AuthConfig.parse(issuer, clientId, redirectUri, scope, audience, apiBaseUrl)

    @Test
    fun emptyBuildConfigIsNotConfigured() {
        val result = AuthConfig.parse("", "", "", "", "", "")
        assertTrue(result is AuthConfigResult.NotConfigured)
        assertEquals(5, (result as AuthConfigResult.NotConfigured).problems.size)
    }

    @Test
    fun validConfigurationIsNormalized() {
        val result = parse(scope = "openid   agentdock.api", audience = " https://api.example.test ")
        val config = (result as AuthConfigResult.Configured).config
        assertEquals("openid agentdock.api", config.scope)
        assertEquals("https://api.example.test/", config.apiBaseUrl)
        assertEquals("https://api.example.test", config.audience)
        assertNull((parse() as AuthConfigResult.Configured).config.audience)
    }

    @Test
    fun rejectsInsecureOrAmbiguousUrls() {
        assertTrue(parse(issuer = "http://id.example.test") is AuthConfigResult.NotConfigured)
        assertTrue(parse(issuer = "https://id.example.test/?a=b") is AuthConfigResult.NotConfigured)
        assertTrue(parse(issuer = "https://user:pw@id.example.test") is AuthConfigResult.NotConfigured)
        assertTrue(parse(apiBaseUrl = "http://api.example.test") is AuthConfigResult.NotConfigured)
        assertTrue(parse(apiBaseUrl = "https://api.example.test/#frag") is AuthConfigResult.NotConfigured)
    }

    @Test
    fun rejectsUnsafeRedirectUris() {
        listOf(
            "https://app.example.test/callback",
            "http://localhost/callback",
            "agentdock:/callback",
            "COM.SLG.AGENTDOCK:/callback",
            "com.slg.agentdock:/callback#frag",
            "javascript:alert(1)",
        ).forEach { redirect ->
            assertTrue(redirect, parse(redirectUri = redirect) is AuthConfigResult.NotConfigured)
        }
    }

    @Test
    fun problemsNeverEchoConfiguredValues() {
        val problems = (parse(clientId = "secret client", issuer = "http://leak.example.test")
            as AuthConfigResult.NotConfigured).problems
        assertTrue(problems.none { it.contains("leak.example") || it.contains("secret") })
    }
}

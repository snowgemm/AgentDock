package com.slg.agentdock.data.auth

import java.net.URI
import java.net.URISyntaxException

/**
 * Explicit sign-in configuration supplied at build time. There are intentionally no
 * defaults: a missing or invalid value leaves sign-in disabled ("not configured").
 */
data class AuthConfig(
    val issuer: String,
    val clientId: String,
    val redirectUri: String,
    val scope: String,
    /** Optional audience request parameter for providers that require one. */
    val audience: String?,
    /** HTTPS API origin, always ending in "/". */
    val apiBaseUrl: String,
) {
    companion object {
        fun parse(
            issuer: String,
            clientId: String,
            redirectUri: String,
            scope: String,
            audience: String,
            apiBaseUrl: String,
        ): AuthConfigResult = parseTrimmed(
            issuer.trim(),
            clientId.trim(),
            redirectUri.trim(),
            scope.trim(),
            audience.trim(),
            apiBaseUrl.trim(),
        )

        private fun parseTrimmed(
            issuer: String,
            clientId: String,
            redirectUri: String,
            scope: String,
            audience: String,
            apiBaseUrl: String,
        ): AuthConfigResult {
            val problems = buildList {
                if (issuer.isBlank()) add("issuer is missing") else httpsProblem("issuer", issuer, allowPath = true)?.let(::add)
                if (clientId.isBlank()) add("client ID is missing")
                else if (clientId.length > 255 || clientId.any(Char::isWhitespace)) add("client ID is invalid")
                if (redirectUri.isBlank()) add("redirect URI is missing") else redirectProblem(redirectUri)?.let(::add)
                if (scope.isBlank()) add("scope is missing")
                else if (scope.any { it.code < 0x21 && it != ' ' || it.code > 0x7E }) add("scope is invalid")
                if (audience.isNotBlank() && audience.any(Char::isWhitespace)) add("audience is invalid")
                if (apiBaseUrl.isBlank()) add("API base URL is missing") else httpsProblem("API base URL", apiBaseUrl, allowPath = true)?.let(::add)
            }
            if (problems.isNotEmpty()) return AuthConfigResult.NotConfigured(problems)
            return AuthConfigResult.Configured(
                AuthConfig(
                    issuer = issuer.trim(),
                    clientId = clientId.trim(),
                    redirectUri = redirectUri.trim(),
                    scope = scope.trim().replace(Regex("\\s+"), " "),
                    audience = audience.trim().ifEmpty { null },
                    apiBaseUrl = apiBaseUrl.trim().let { if (it.endsWith("/")) it else "$it/" },
                ),
            )
        }

        private fun parseUri(value: String): URI? = try {
            URI(value.trim())
        } catch (_: URISyntaxException) {
            null
        }

        private fun httpsProblem(label: String, value: String, allowPath: Boolean): String? {
            val uri = parseUri(value) ?: return "$label is not a valid URL"
            if (uri.scheme != "https" || uri.host.isNullOrEmpty()) return "$label must be an absolute HTTPS URL"
            if (uri.userInfo != null || uri.rawQuery != null || uri.rawFragment != null) {
                return "$label must not contain credentials, a query or a fragment"
            }
            if (!allowPath && !uri.rawPath.isNullOrEmpty()) return "$label must not contain a path"
            return null
        }

        /**
         * RFC 8252 section 7.1: a private-use scheme must be a reverse-domain name that
         * the app controls. Plain http(s) and dotless schemes are rejected.
         */
        private fun redirectProblem(value: String): String? {
            val uri = parseUri(value) ?: return "redirect URI is not valid"
            val scheme = uri.scheme ?: return "redirect URI needs a scheme"
            if (scheme == "http" || scheme == "https" || scheme == "javascript" || scheme == "data") {
                return "redirect URI must use a private-use reverse-domain scheme"
            }
            if (!scheme.contains('.') || scheme != scheme.lowercase()) {
                return "redirect URI scheme must be a lowercase reverse-domain name"
            }
            if (uri.rawFragment != null || uri.rawQuery != null || uri.rawUserInfo != null) {
                return "redirect URI must not contain credentials, a query or a fragment"
            }
            return null
        }
    }
}

sealed interface AuthConfigResult {
    data class Configured(val config: AuthConfig) : AuthConfigResult

    /** [problems] never contain configuration values, only which field is wrong. */
    data class NotConfigured(val problems: List<String>) : AuthConfigResult
}

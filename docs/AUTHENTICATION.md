# AgentDock authentication and session contract

**Status on `test`:** The backend RFC 9068 access-token verifier, internal session endpoints, and Android AppAuth Authorization Code + PKCE client are present. Auth0 has been selected as the provider, but the tenant/API/client configuration and real-device end-to-end flow have not yet been verified. Supabase role provisioning and migrations are separate prerequisites.

## Security boundary

Android is a public OAuth client. It uses Authorization Code + PKCE (S256) through the system browser. Never embed an Auth0 client secret in the APK.

The backend accepts only signed RFC 9068-style JWT access tokens with JOSE `typ` equal to `at+jwt` or `application/at+jwt`. It verifies the configured HTTPS JWKS, asymmetric algorithm allowlist, exact issuer, AgentDock API audience, expiry, issued-at, `client_id` and `jti`; `azp` is checked only when explicitly configured. ID tokens are rejected. Do not weaken this verifier to accept another provider's token format.

## Auth0 configuration

Auth0 supports the RFC 9068 access-token profile. Configure it on the **AgentDock API resource server**, not by changing the Android app to send an ID token:

1. Create/select a custom API in Auth0 and choose a unique API Identifier. This exact string is the AgentDock API audience.
2. Set the API's JWT access-token profile to **RFC 9068** and signing algorithm to **RS256**.
3. Register the Android application as a **Native** public client using Authorization Code + PKCE. Do not create or embed a client secret for the Android app.
4. Add the exact private-use reverse-domain redirect URI configured in the Android build to the Auth0 Allowed Callback URLs.
5. Use one Auth0 issuer domain consistently for discovery, token acquisition, issuer validation and JWKS lookup. Do not obtain tokens from a custom domain and validate against a different domain.

Configure the backend together:

- `AGENTDOCK_OIDC_ISSUER`: exact `iss` value from the Auth0 discovery document (commonly ends with `/`).
- `AGENTDOCK_OIDC_AUDIENCE`: exact API Identifier.
- `AGENTDOCK_OIDC_JWKS_URL`: `https://YOUR_AUTH0_DOMAIN/.well-known/jwks.json` for the same issuer domain.
- `AGENTDOCK_OIDC_ALLOWED_CLIENT_IDS`: JSON array containing the Android Native application's client ID, for example `["YOUR_ANDROID_CLIENT_ID"]`.
- `AGENTDOCK_OIDC_ALLOWED_ALGORITHMS`: keep `["RS256"]` unless another asymmetric algorithm has been separately reviewed.

The backend verifier requires RFC 9068 claims including `client_id` and `jti`. Confirm the issued access token's JOSE header contains `typ: at+jwt` or `application/at+jwt`; do not infer compliance merely because the token is a JWT.

## Endpoints

| Endpoint | Credential | Behavior |
|---|---|---|
| GET /api/v1/auth/identity | External OIDC access token | Verification probe; returns minimal issuer/subject/expiry |
| POST /api/v1/auth/session | External OIDC access token | Maps identity, provisions a minimal account/workspace on first sign-in, issues AgentDock token pair |
| POST /api/v1/auth/session/refresh | Refresh token in request body | Rotates refresh token and issues a new access token |
| GET /api/v1/auth/me | AgentDock access token | Returns current user, workspace and session identifiers |
| POST /api/v1/auth/session/logout | AgentDock access token | Revokes the current session and its tokens |

The mapping key is the exact `(issuer, subject)` pair. Email is not used for account matching or linking. First sign-in creates one personal workspace and an owner membership. Provisioning is serialized by a PostgreSQL transaction advisory lock and protected by a unique database constraint.

## AgentDock session tokens

- Access and refresh tokens are cryptographically random opaque bearer strings.
- Only SHA-256 hashes are persisted; plaintext tokens are returned only in the session response.
- Access token lifetime defaults to 15 minutes; session lifetime defaults to 30 days.
- Refresh tokens rotate on every successful refresh; replay revokes the session family.
- Logout revokes the session in PostgreSQL; subsequent access-token checks fail immediately.
- Refresh requests from one client must be serialized. Concurrent refresh calls with the same token can be detected as replay.
- The server checks the session-token hash in PostgreSQL on authenticated requests. This enables immediate revocation but adds a database read per request and must be load-tested.

The refresh-token rotation design follows [RFC 9700, Section 4.14](https://www.rfc-editor.org/rfc/rfc9700.html).

## Database permissions

The migration creates `auth_identities`, `user_sessions` and `session_tokens`, and makes `users.email` nullable. The runtime role receives only the identity/session and required tenant-task grants. It does not receive schema ownership, migration-history access, superuser or `BYPASSRLS` privileges.

Use the dedicated Supabase setup instructions in [../backend/SUPABASE_SETUP.md](../backend/SUPABASE_SETUP.md). The Android app must call the AgentDock API; it must never connect directly to Supabase Postgres or contain database credentials.

## Android client configuration

The app uses AppAuth-Android with Authorization Code + PKCE (S256). AppAuth handles state/nonce and PKCE validation; the app additionally validates that the redirect belongs to its authorization request and that discovery's issuer matches the configured issuer. The external access token is exchanged once at `POST /api/v1/auth/session` and is not persisted. AgentDock's opaque access/refresh tokens are stored encrypted using Android Keystore AES-256-GCM in a dedicated DataStore file.

Build-time Gradle properties have **no defaults**. Provide these using local `~/.gradle/gradle.properties` or protected build configuration; do not commit private deployment values:

| Property | Meaning |
|---|---|
| `agentdockOidcIssuer` | Auth0 issuer URL, absolute HTTPS URL |
| `agentdockOidcClientId` | Auth0 Native application client ID |
| `agentdockOidcRedirectUri` | Private-use reverse-domain redirect URI; must match Auth0 Allowed Callback URLs |
| `agentdockOidcScope` | Space-separated scopes, normally including `openid` |
| `agentdockOidcAudience` | Exact AgentDock API Identifier |
| `agentdockApiBaseUrl` | AgentDock API origin, HTTPS |

Pass them as `-PagentdockOidcIssuer=...`, `-PagentdockOidcClientId=...`, `-PagentdockOidcRedirectUri=...`, `-PagentdockOidcScope=...`, `-PagentdockOidcAudience=...` and `-PagentdockApiBaseUrl=...`. The client ID and API Identifier are not client secrets. Never add a client secret or database password to Gradle properties included in the APK.

Refresh is single-flight behind a mutex. A request that receives 401 is retried at most once with the refreshed AgentDock token. Sign-out clears local credentials immediately and then revokes the session remotely on a best-effort basis.

## Not yet verified or implemented

- Auth0 tenant/API settings and an actual RFC 9068 token have not been verified against the deployed backend.
- Android sign-in and task flows have not been exercised end-to-end against a live API and Supabase database.
- Account profile/email verification, account linking, multiple workspaces and tenant switching remain separate work.
- Per-device session listing/revocation, expiry cleanup, retention and rate limiting remain separate work.
- Production deployment and secure secret provisioning remain pending.

Do not describe AgentDock as having end-to-end login until Auth0 is configured and the Android flow has been exercised against the deployed API.

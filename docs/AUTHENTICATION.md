# AgentDock authentication and session contract

**Status:** Backend session contract and Android sign-in client are implemented. No identity provider has been selected or configured, and the Android flow has not been exercised against a real provider.

## Security boundary

The Android app is a public OAuth client. When the client login flow is implemented, it must use Authorization Code + PKCE with S256 through the system browser or a browser-backed authentication tab. Never embed an OAuth client secret in the APK.

The current backend verifier accepts only signed RFC 9068-style JWT access tokens whose JOSE typ is at+jwt or application/at+jwt. It validates the configured HTTPS JWKS, asymmetric algorithm allowlist, issuer, AgentDock API audience, expiry, issued-at, client_id and jti; azp is checked when configured. Do not send an OIDC ID token. A provider that does not issue this access-token profile for the AgentDock API requires a separately reviewed adapter; do not weaken the verifier to make a provider fit.

Configure AGENTDOCK_OIDC_ISSUER, AGENTDOCK_OIDC_AUDIENCE, AGENTDOCK_OIDC_JWKS_URL and AGENTDOCK_OIDC_ALLOWED_CLIENT_IDS together. The allowed client IDs must be a JSON array containing only registered OAuth clients. The issuer and JWKS URL must be HTTPS and operator-provisioned, never request-controlled.

## Endpoints

| Endpoint | Credential | Behavior |
|---|---|---|
| GET /api/v1/auth/identity | External OIDC access token | Verification probe; returns minimal issuer/subject/expiry |
| POST /api/v1/auth/session | External OIDC access token | Maps identity, provisions a minimal account/workspace on first sign-in, issues AgentDock token pair |
| POST /api/v1/auth/session/refresh | Refresh token in request body | Rotates the refresh token and issues a new access token |
| GET /api/v1/auth/me | AgentDock access token | Returns current user, workspace and session identifiers |
| POST /api/v1/auth/session/logout | AgentDock access token | Revokes the current session and all its tokens |

The mapping key is the exact (issuer, subject) pair. Email is not used for account matching or linking; accounts provisioned through this flow may have a null email until a separately verified profile flow exists. First sign-in creates one personal workspace and an owner membership. Provisioning is serialized by a PostgreSQL transaction advisory lock and protected by a unique database constraint.

## AgentDock session tokens

- Access and refresh tokens are cryptographically random opaque bearer strings.
- Only SHA-256 hashes are persisted; plaintext tokens are returned only in the session response.
- Access token lifetime defaults to 15 minutes.
- Session lifetime defaults to a fixed 30 days.
- Refresh tokens rotate on every successful refresh; the previous access token is invalidated.
- A previously used refresh token indicates replay and revokes the entire session family.
- Logout revokes the session in PostgreSQL; subsequent access-token checks fail immediately.
- Refresh requests from one client must be serialized. Concurrent refresh calls using the same token are treated as replay and revoke the session.
- The server checks the session-token hash in PostgreSQL on each authenticated request. This enables immediate revocation but adds a database read per request and must be load-tested.

The refresh-token rotation and replay-detection design follows the public-client guidance in [RFC 9700, Section 4.14](https://www.rfc-editor.org/rfc/rfc9700.html).

## Database permissions

The migration creates auth_identities, user_sessions and session_tokens, and makes users.email nullable. The runtime role receives only SELECT/INSERT/UPDATE on identity/session tables and users/tenants, plus the existing tenant-scoped DML permissions. It does not receive schema ownership, migration-history access, superuser or BYPASSRLS privileges.

Identity/session registry tables are not tenant-owned application data; they are accessed only through the backend service. Tenant membership writes still require the transaction-local app.current_tenant_id context. Before building task routes, the backend must resolve the session workspace membership on the server, set RLS context in the same transaction, and deny requests with no active membership.

## Android client

The app signs in with AppAuth-Android: Authorization Code + PKCE (S256) in the system browser (Custom Tabs), per RFC 8252. It is a public client; no client secret exists anywhere. AppAuth generates and verifies `state`/`nonce`; the app additionally checks that the redirect answers its own request (state, client ID, redirect URI, PKCE method) and that the discovery document's `issuer` equals the configured issuer. The external access token is sent once to `POST /api/v1/auth/session` and is never stored; only AgentDock's opaque access/refresh tokens are kept, encrypted with an Android Keystore AES-256-GCM key in a dedicated DataStore file.

Build-time configuration has **no defaults**. Pass Gradle properties (`-P…` or `~/.gradle/gradle.properties`); when any is missing or invalid the UI shows "sign-in not configured":

| Property | Meaning |
|---|---|
| `agentdockOidcIssuer` | Provider issuer, absolute HTTPS URL; discovery is fetched from it |
| `agentdockOidcClientId` | Registered public client ID (must also be in `AGENTDOCK_OIDC_ALLOWED_CLIENT_IDS`) |
| `agentdockOidcRedirectUri` | Private-use reverse-domain redirect, e.g. `com.example.app:/oauth2redirect` (RFC 8252 §7.1); its scheme becomes the manifest placeholder |
| `agentdockOidcScope` | Space-separated scopes requested |
| `agentdockOidcAudience` | Optional; sent as the `audience` authorization parameter for providers that need it |
| `agentdockApiBaseUrl` | AgentDock API origin, HTTPS |

Refresh is single-flight behind a mutex (refresh tokens are single-use, so concurrent use would be treated as replay). A request that receives 401 is retried at most once with the refreshed token. Sign-out clears local credentials immediately and then revokes the session remotely on a best-effort basis.

## Not yet implemented

- Choosing and configuring the actual OIDC provider and verifying its real access-token contract.
- Verifying the Android flow against a real provider (the client is covered by unit tests and a fake-backed UI smoke test only).
- Account profile/email verification, account linking, multiple workspaces and tenant switching.
- Per-device session listing and remote revocation.
- Expired session/token cleanup, retention schedule and rate limiting/abuse controls.
- Task routes and membership enforcement on every tenant data operation.
- Production deployment migration and secret provisioning.

Do not describe AgentDock as having end-to-end login until the Android flow has been integrated and tested against the chosen provider.
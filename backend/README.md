# AgentDock Backend

FastAPI control-plane bootstrap with the first PostgreSQL persistence boundary.

## Implemented

- Versioned API prefix: `/api/v1`.
- `GET /api/v1/health/live` is a process liveness check and never requires a database connection.
- `GET /api/v1/health/ready` executes `SELECT 1` against the configured runtime database and returns 503 when the database is not configured or unavailable. It is a database readiness probe, not a migration-version or worker-readiness check.
- The API creates the async engine during application lifespan and disposes it during shutdown. Connection establishment and pool acquisition are bounded.
- Runtime configuration uses the `AGENTDOCK_` prefix; database URLs use `SecretStr` in application settings.
- SQLAlchemy async engine/session helpers and Alembic migrations.
- Initial records: tenants, users, tenant memberships, tasks, ordered task events and idempotency records.
- Verified external identities are mapped by the exact `(issuer, subject)` pair. First sign-in provisions a minimal account and personal workspace without trusting or linking by email.
- AgentDock sessions use opaque random access/refresh tokens. Only SHA-256 token hashes are stored; refresh tokens rotate and replay revokes the full session family. Access tokens are short-lived and checked against PostgreSQL so logout revocation takes effect immediately.
- PostgreSQL row-level security (RLS) is enabled and forced on every tenant-owned table.
- Docker runs as UID/GID 10001, not root.

The API now has an optional OIDC JWT access-token verification boundary. When configured, `GET /api/v1/auth/identity` checks the RFC 9068 access-token type (`at+jwt` or `application/at+jwt`), signature against the configured HTTPS JWKS endpoint, a fixed allowlist of asymmetric algorithms, issuer, API audience and the RFC 9068 required claims (`iss`, `sub`, `aud`, `exp`, `iat`, `client_id`, `jti`); it returns only issuer, subject and expiry. Missing or non-access-token `typ` values are rejected; do not send OIDC ID tokens. A provider-specific non-RFC 9068 token format requires a separately reviewed adapter. JWKS retrieval runs off the event loop, is cached, and has a bounded timeout. Invalid tokens return 401; temporary JWKS connection failures return a generic 503.

This is a backend identity/session and initial task API foundation, not a complete product workflow. The task API implements create, list, detail and ordered event reads with idempotency and active-workspace membership checks; it does not implement task lifecycle commands, SSE, worker execution or Agent orchestration. Android Authorization Code + PKCE, provider-specific setup and token-contract verification remain separate work. The internal session endpoints require a trusted, configured OIDC issuer and the database migrations/runtime grants before use. Every tenant task request verifies active membership after setting transaction-local RLS context. The API creates a bounded async engine during application lifespan and disposes it on shutdown.

## Database roles and tenant isolation

Use different database principals for migrations and normal API/worker traffic:

- The migration role owns the schema objects and is used only by Alembic deployments.
- The runtime role must be `NOSUPERUSER NOBYPASSRLS`, must not own tenant tables, and receives only the required table DML grants.
- Never run the API as the PostgreSQL superuser or migration owner.

The migration applies `ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY` to `tenant_memberships`, `tasks`, `task_events` and `idempotency_records`. Policies fail closed when the transaction has no `app.current_tenant_id`.

Every tenant query must run in an explicit transaction and set its scope with `set_tenant_context(session, tenant_id)`. Resolve and authorize the user's membership on the server before setting this value; never trust a tenant ID supplied by the client. RLS is a database isolation boundary, not a replacement for authentication or authorization. PostgreSQL superusers and roles with `BYPASSRLS` can bypass policies.

Example role setup (execute as a database administrator after creating the database):

```sql
CREATE ROLE agentdock_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
CREATE ROLE agentdock_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
ALTER SCHEMA public OWNER TO agentdock_migrator;
GRANT CONNECT ON DATABASE agentdock TO agentdock_migrator, agentdock_runtime;
GRANT USAGE ON SCHEMA public TO agentdock_runtime;
```

Set `AGENTDOCK_MIGRATION_DATABASE_URL` to the migration role URL and run migrations:

```bash
python -m alembic upgrade head
```

Then, as the migration role or database administrator, grant only the required runtime access:

```sql
GRANT SELECT, INSERT ON TABLE tenants, users TO agentdock_runtime;
GRANT SELECT, INSERT, UPDATE
  ON TABLE auth_identities, user_sessions, session_tokens
  TO agentdock_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE
  ON TABLE tenant_memberships, tasks, task_events, idempotency_records
  TO agentdock_runtime;
```

Do not grant the runtime role access to `alembic_version`, schema ownership, role creation or `BYPASSRLS`. Future migrations must explicitly grant only the access needed for each new table. Use `AGENTDOCK_DATABASE_URL` for the restricted runtime role. Never copy production credentials into the repository or CI logs.

## Local development

Use Python 3.14 and a virtual environment. From this directory:

1. Create and activate a virtual environment.
2. Install dependencies with `pip install -r requirements-dev.txt`.
3. Copy `.env.example` to `.env` and configure the two database URLs with your locally provisioned roles.
4. Apply migrations with `python -m alembic upgrade head`.
5. Start the API with `uvicorn app.main:app --reload`.

API liveness: http://127.0.0.1:8000/api/v1/health/live. Database readiness: http://127.0.0.1:8000/api/v1/health/ready. The readiness route requires a configured and reachable runtime PostgreSQL database. Interactive docs are available at http://127.0.0.1:8000/docs outside production mode.

## Tests

Run `python -m compileall -q app migrations tests`, then `python -m pytest -q`. The PostgreSQL integration suite covers migration/schema permissions, forced tenant RLS, identity-to-account provisioning, workspace ownership, opaque token hashing, session refresh rotation, replay revocation and logout. PostgreSQL tests require `AGENTDOCK_TEST_ADMIN_DATABASE_URL` and `AGENTDOCK_TEST_DATABASE_URL`; they are always configured in GitHub Actions. Run the suite with the restricted runtime role for application operations and the admin role only for test setup/assertions.

Copy `.env.example` for local configuration. Never commit real `.env` files, credentials or signing material.

## Optional OIDC access-token verification

Set `AGENTDOCK_OIDC_ISSUER`, `AGENTDOCK_OIDC_AUDIENCE`, `AGENTDOCK_OIDC_JWKS_URL` and `AGENTDOCK_OIDC_ALLOWED_CLIENT_IDS` together. The allowed client IDs are a JSON array of explicitly registered OAuth clients; tokens from other clients are rejected even when their audience matches. The issuer and JWKS URLs must use HTTPS and must be provisioned by the operator, never supplied by a request. The audience identifies the AgentDock API/resource server. The default algorithm allowlist is RS256; optional algorithms must remain asymmetric and explicitly allowlisted. The configured JWKS client caches keys and uses a bounded network timeout.

The `GET /api/v1/auth/identity` endpoint remains a verification probe. `POST /api/v1/auth/session` exchanges a verified external access token for an AgentDock session: the backend maps `(issuer, subject)` to an internal account, provisions a personal workspace on first sign-in, and issues short-lived opaque access tokens plus rotating refresh tokens. Only SHA-256 token hashes are stored; replay of a rotated refresh token revokes the session family. `GET /api/v1/auth/me` reads the current internal session and `POST /api/v1/auth/session/logout` revokes it. Never send an ID token; configure and validate the identity provider's access-token contract for the AgentDock API audience.

The initial task API is documented in `docs/TASK_API.md`. Task creation atomically persists the `QUEUED` task, its `TASK_CREATED` event and its idempotency response. List/detail/event reads run only after session and active-workspace membership checks. `QUEUED` means accepted and persisted; no worker is present to execute it yet.

## Worker process and role

The durable worker runs from the same image: `python -m app.worker` (see `docs/WORKER.md`). It uses its own least-privilege role and URL (`AGENTDOCK_WORKER_DATABASE_URL`); never reuse the runtime or migrator role, and never give it `BYPASSRLS`:

```sql
CREATE ROLE agentdock_worker LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
GRANT CONNECT ON DATABASE agentdock TO agentdock_worker;
GRANT USAGE ON SCHEMA public TO agentdock_worker;
-- after `alembic upgrade head`, as the migration role:
GRANT SELECT, UPDATE ON TABLE task_dispatch TO agentdock_worker;
GRANT SELECT ON TABLE tasks TO agentdock_worker;
GRANT UPDATE (status, updated_at) ON TABLE tasks TO agentdock_worker;
GRANT SELECT, INSERT ON TABLE task_events TO agentdock_worker;
GRANT SELECT, INSERT, UPDATE ON TABLE task_receipts TO agentdock_worker;
GRANT SELECT, INSERT, UPDATE ON TABLE task_checkpoints TO agentdock_worker;
```

The API runtime role needs no privileges on `task_dispatch` or `task_receipts`: a `SECURITY DEFINER` trigger on `tasks` enqueues new tasks.

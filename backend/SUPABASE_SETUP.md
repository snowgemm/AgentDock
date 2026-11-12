# Supabase PostgreSQL setup for AgentDock

This guide deploys the existing Alembic schema from the `test` branch to the Supabase project **AgentDock**.

## Verified target

- Supabase project ref: `mdsnvjtymmcfpseoinhc`
- PostgreSQL version: 17.11
- Region: `ap-southeast-1`
- Database name: **`postgres`**
- At inspection time, `public` contained no AgentDock tables, no Alembic migration history existed, and the four AgentDock roles below did not exist.
- The Supabase project is on the Free plan. This guide creates no Supabase/Render resources and changes no plan.

The local CI database is named `agentdock`; Supabase's default database is named `postgres`. **Do not copy the local CI database name into a Supabase connection string or GRANT statement.**

## 1. Select the correct connection mode

In the Supabase Dashboard, open **AgentDock → Connect → Session pooler** and copy the exact host and connection details shown there.

Use **Session pooler**, port `5432`, for this backend when connecting from an IPv4-only host. It preserves session behavior required by the current backend's database event listener (`LISTEN/NOTIFY`) and is available over IPv4 on the Free plan. Do not use Transaction pooler (port `6543`) for this backend. Direct connection is also suitable when the host supports IPv6.

Do not guess the pooler hostname. Supabase's pooler cluster index can vary; copy it from the Dashboard.

References:
- https://supabase.com/docs/guides/database/connecting-to-postgres
- https://supabase.com/docs/guides/database/postgres/roles

## 2. Provision least-privilege PostgreSQL roles

Open **Supabase Dashboard → SQL Editor** and run this once while connected as the project administrator. The current target was checked and these four roles were absent.

```sql
CREATE ROLE agentdock_migrator
  LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;

CREATE ROLE agentdock_runtime
  LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;

CREATE ROLE agentdock_worker
  LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;

CREATE ROLE agentdock_dispatcher
  NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;

GRANT agentdock_dispatcher TO agentdock_migrator;

GRANT CONNECT ON DATABASE postgres
  TO agentdock_migrator, agentdock_runtime, agentdock_worker;
GRANT CREATE ON DATABASE postgres TO agentdock_migrator;

GRANT USAGE, CREATE ON SCHEMA public TO agentdock_migrator;
GRANT USAGE ON SCHEMA public TO agentdock_runtime, agentdock_worker;
```

Next, assign a different randomly generated password to each login role using your password manager. Execute the following statements after replacing each placeholder; do not reuse the same password:

```sql
ALTER ROLE agentdock_migrator PASSWORD 'REPLACE_WITH_UNIQUE_RANDOM_PASSWORD';
ALTER ROLE agentdock_runtime PASSWORD 'REPLACE_WITH_UNIQUE_RANDOM_PASSWORD';
ALTER ROLE agentdock_worker PASSWORD 'REPLACE_WITH_UNIQUE_RANDOM_PASSWORD';
```

The `agentdock_dispatcher` role must remain `NOLOGIN`. It is only the isolated owner of the task-dispatch trigger function. Do not grant `BYPASSRLS`, superuser, role-creation or schema-ownership privileges to the API or worker roles.

## 3. Build the three connection URLs

Use the exact **Session pooler host** copied from the Dashboard. The Shared Session Pooler username includes the project ref:

- `agentdock_migrator.mdsnvjtymmcfpseoinhc`
- `agentdock_runtime.mdsnvjtymmcfpseoinhc`
- `agentdock_worker.mdsnvjtymmcfpseoinhc`

Use port `5432` and database `postgres`. The SQLAlchemy/asyncpg URL format is:

```text
postgresql+asyncpg://ROLE.mdsnvjtymmcfpseoinhc:PASSWORD@SESSION_POOLER_HOST:5432/postgres
```

Create one URL per role and keep the passwords private. If a password contains URL-reserved characters, percent-encode it before putting it in the URL.

- `AGENTDOCK_MIGRATION_DATABASE_URL`: migrator URL; use only for Alembic.
- `AGENTDOCK_DATABASE_URL`: runtime URL; use only for FastAPI.
- `AGENTDOCK_WORKER_DATABASE_URL`: worker URL; use only for the worker process.

Never put any of these URLs in the APK, a committed `.env` file, an issue, or a chat message.

## 4. Apply the Alembic migrations

The repository's Alembic migrations are the schema source of truth. Apply them with Alembic, **not** by manually creating tables and not by using Supabase's separate migration-history API.

From the repository root, with Python 3.14 available:

```bash
cd backend
python -m venv .venv
# Activate the virtual environment for your operating system.
python -m pip install -r requirements-dev.txt

# Set AGENTDOCK_MIGRATION_DATABASE_URL in the shell/secret store first.
python -m alembic upgrade head
python -m alembic current
python -m alembic check
```

The current migration head is `20261113_0007`. It creates the tenant, identity/session, task, dispatch, event, checkpoint, approval and audit schema. The worker-dispatch migration requires the role membership and database/schema grants from step 2.

Do not run `alembic downgrade base` against the Supabase project. That rollback is only part of the disposable PostgreSQL CI test.

## 5. Grant runtime and worker table access

After `alembic upgrade head` succeeds, connect as `agentdock_migrator` or the database administrator and run:

```sql
-- FastAPI runtime: no access to task_dispatch or task_receipts.
GRANT SELECT, INSERT ON TABLE tenants, users TO agentdock_runtime;
GRANT SELECT, INSERT, UPDATE
  ON TABLE auth_identities, user_sessions, session_tokens
  TO agentdock_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE
  ON TABLE tenant_memberships, tasks, task_events, idempotency_records
  TO agentdock_runtime;
GRANT SELECT, UPDATE ON TABLE approvals TO agentdock_runtime;
GRANT SELECT, INSERT ON TABLE audit_events TO agentdock_runtime;

-- Worker: narrowly scoped task execution and routing access.
GRANT SELECT, UPDATE ON TABLE task_dispatch TO agentdock_worker;
GRANT SELECT ON TABLE tasks TO agentdock_worker;
GRANT UPDATE (status, updated_at) ON TABLE tasks TO agentdock_worker;
GRANT SELECT, INSERT ON TABLE task_events TO agentdock_worker;
GRANT SELECT, INSERT, UPDATE ON TABLE task_receipts TO agentdock_worker;
GRANT SELECT, INSERT, UPDATE ON TABLE task_checkpoints TO agentdock_worker;
GRANT SELECT, INSERT, UPDATE ON TABLE approvals TO agentdock_worker;
GRANT SELECT, INSERT ON TABLE audit_events TO agentdock_worker;
GRANT SELECT ON TABLE tenant_memberships TO agentdock_worker;
GRANT SELECT (id, is_active) ON TABLE users TO agentdock_worker;
```

Do not grant `anon` or `authenticated` access to these tables. AgentDock's FastAPI backend talks directly to PostgreSQL; the Android application must talk to the AgentDock API, not directly to these tables.

Every tenant-owned table is protected by enabled and forced RLS. The API/worker roles must not own these tables and must remain `NOBYPASSRLS`. The dispatcher trigger function is owned by the non-login `agentdock_dispatcher` role; the API runtime must not receive direct access to `task_dispatch`.

## 6. Verify the real Supabase database

Run the following query in SQL Editor after migration and grants:

```sql
SELECT version_num FROM alembic_version;

SELECT tablename
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY tablename;

SELECT rolname, rolcanlogin, rolsuper, rolbypassrls
FROM pg_roles
WHERE rolname IN (
  'agentdock_migrator', 'agentdock_runtime',
  'agentdock_worker', 'agentdock_dispatcher'
)
ORDER BY rolname;

SELECT
  has_table_privilege('agentdock_runtime', 'task_dispatch', 'SELECT') AS runtime_can_read_dispatch,
  has_table_privilege('agentdock_worker', 'task_dispatch', 'SELECT') AS worker_can_read_dispatch;
```

Expected results:
- `alembic_version` contains `20261113_0007`.
- The public schema contains the 14 AgentDock tables documented in `backend/README.md`.
- `agentdock_dispatcher` has `rolcanlogin = false`; all four custom roles have `rolsuper = false` and `rolbypassrls = false`.
- `runtime_can_read_dispatch = false`; `worker_can_read_dispatch = true`.

The Supabase dashboard's own migration list is not the Alembic history. Verify this deployment through `alembic_version`.

## 7. Configure the API and worker hosts

Set the three connection URLs as secrets in the runtime host. Configure the API with `AGENTDOCK_DATABASE_URL`; configure the Worker with `AGENTDOCK_WORKER_DATABASE_URL`. Keep the migration URL only in a protected migration environment and remove it after deployment where possible.

API container command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Worker command:

```bash
python -m app.worker
```

The API readiness endpoint is `/api/v1/health/ready`; it checks the runtime database connection with `SELECT 1`. The liveness endpoint `/api/v1/health/live` only checks the process. Worker health is separate and can be exposed with `AGENTDOCK_WORKER_HEALTH_PORT` when the host supports it.

The worker will **not** execute model tasks until an approved handler/provider is configured. The current optional single-agent handler requires `AGENTDOCK_WORKER_HANDLER=agent`, `AGENTDOCK_OPENAI_MODEL` and `OPENAI_API_KEY`. Without these, tasks are intentionally left in `QUEUED`; database connectivity alone does not mean AI execution is configured.

## Deployment boundaries

- `.github/workflows/backend-ci.yml` tests migrations and permissions against a disposable PostgreSQL 17 service. It does not deploy to Supabase.
- Never point backend CI's rollback/re-apply test at the Supabase project.
- No Supabase schema or role was changed when this guide was written. Run each database-changing step deliberately and verify it before configuring services.
- A free Render Web Service is suitable for API testing but sleeps after 15 minutes without inbound traffic. Free Render does not offer a free always-on Background Worker. Use a local worker for development/testing or choose an always-on worker host only after reviewing its cost and availability. Do not assume an always-on worker can be run continuously on Render Free.

Render free-tier limits: https://render.com/docs/free

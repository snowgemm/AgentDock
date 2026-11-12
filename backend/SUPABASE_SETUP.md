# Supabase PostgreSQL setup for AgentDock

This guide deploys the existing Alembic schema from the `test` branch to the Supabase project **AgentDock**.

## Verified target

- Supabase project ref: `mdsnvjtymmcfpseoinhc`
- PostgreSQL version: 17.11
- Region: `ap-southeast-1`
- Database name: **`postgres`**
- Verified on 2026-11-12: `public` contains no AgentDock tables and has no Alembic migration history. The four AgentDock roles have now been created with `NOLOGIN`; their database/schema grants and dispatcher membership have been verified. They cannot authenticate until the three login roles receive unique passwords.
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

The four roles and base privileges were provisioned on the project on 2026-11-12 and verified. The SQL below documents the exact intended state; do not rerun `CREATE ROLE` on this already-provisioned project. For a fresh project, run it once as the project administrator.

```sql
CREATE ROLE agentdock_migrator
  NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;

CREATE ROLE agentdock_runtime
  NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;

CREATE ROLE agentdock_worker
  NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;

CREATE ROLE agentdock_dispatcher
  NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;

GRANT agentdock_dispatcher TO agentdock_migrator;

GRANT CONNECT ON DATABASE postgres
  TO agentdock_migrator, agentdock_runtime, agentdock_worker;
GRANT CREATE ON DATABASE postgres TO agentdock_migrator;

GRANT USAGE, CREATE ON SCHEMA public TO agentdock_migrator;
GRANT USAGE ON SCHEMA public TO agentdock_runtime, agentdock_worker;
```

After generating three different random passwords with your password manager, enable only the three service login roles and set each password. Run these statements in Supabase SQL Editor. The dispatcher role must remain `NOLOGIN`:

```sql
ALTER ROLE agentdock_migrator LOGIN PASSWORD 'UNIQUE_PASSWORD_FOR_MIGRATOR';
ALTER ROLE agentdock_runtime LOGIN PASSWORD 'UNIQUE_PASSWORD_FOR_RUNTIME';
ALTER ROLE agentdock_worker LOGIN PASSWORD 'UNIQUE_PASSWORD_FOR_WORKER';
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

The current migration head is `20261112_0008`. It creates the tenant, identity/session, task, dispatch, event, checkpoint, approval and audit schema. The worker-dispatch migration requires the role membership and database/schema grants from step 2.

Do not run `alembic downgrade base` against the Supabase project. That rollback is only part of the disposable PostgreSQL CI test.

### Deploy from GitHub Actions (no local PostgreSQL tools needed)

The `Backend CI` workflow on branch `test` has a separate, guarded migration job. It runs only when all of these conditions are true:

1. You manually run **Actions → Backend CI → Run workflow** and select branch `test`.
2. The normal Backend CI test job completes successfully.
3. Repository variable `AGENTDOCK_DEPLOY_SUPABASE_TEST` is set to the exact value `enabled`.
4. Repository secret `AGENTDOCK_TEST_MIGRATION_DATABASE_URL` contains the dedicated migrator URL from step 3.

Set these in **GitHub → AgentDock → Settings → Secrets and variables → Actions**:
- Under **Secrets**, add `AGENTDOCK_TEST_MIGRATION_DATABASE_URL`.
- Under **Variables**, add `AGENTDOCK_DEPLOY_SUPABASE_TEST` = `enabled`.

The job checks that the connection really reaches database `postgres` as `agentdock_migrator`, verifies PostgreSQL 17, all four restricted roles and required privileges, then runs only `alembic upgrade head` and `alembic check`. It never runs a downgrade. Normal pushes and pull requests do not deploy to Supabase.

Do not enable the variable until the three login role passwords and the migrator connection URL are safely configured. If the manual workflow does not show the `test` branch, use the local Alembic commands above; never add the secret to the repository or paste it into chat.

## 5. Apply least-privilege runtime and worker grants

Alembic revision `20261112_0008` applies the table grants automatically after the schema migrations. This keeps PostgreSQL CI and Supabase deployments on the same permission source of truth. Do not run a second, separate grant script.

The resulting permissions are intentionally split:

- `agentdock_runtime`: API identity/session and tenant task CRUD needed by FastAPI; approval decisions and append-only audit writes. No access to `task_dispatch`, `task_receipts`, or `agentdock_private`.
- `agentdock_worker`: queue lease access, task status updates, task events, receipts/checkpoints, approval processing, audit inserts, membership reads and only `users.id/is_active` column reads.
- `agentdock_dispatcher`: non-login owner of the trigger function, with `INSERT` plus `SELECT(task_id)` only on `task_dispatch`. The latter is the minimum column-level read permission required by `ON CONFLICT(task_id) DO NOTHING`; it cannot read the whole queue row.
- `agentdock_migrator`: owns the schema objects it creates and applies Alembic revisions; never use it for API or worker traffic.

Every tenant-owned table is protected by enabled and forced RLS. API/worker roles must not own tenant tables and must remain `NOBYPASSRLS`. The runtime role cannot access the worker queue directly. Do not grant `anon` or `authenticated` access to these application tables. Android must call the AgentDock API and never connect directly to Supabase Postgres.


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
  has_table_privilege('agentdock_worker', 'task_dispatch', 'SELECT') AS worker_can_read_dispatch,
  has_table_privilege('agentdock_runtime', 'tasks', 'INSERT') AS runtime_can_create_tasks,
  has_table_privilege('agentdock_worker', 'tasks', 'UPDATE') AS worker_can_update_tasks;
```

Expected results:
- `alembic_version` contains `20261112_0008`.
- The public schema contains the 14 AgentDock application tables plus Alembic's `alembic_version` table.
- `agentdock_dispatcher` has `rolcanlogin = false`; all four custom roles have `rolsuper = false` and `rolbypassrls = false`.
- `runtime_can_read_dispatch = false`; `worker_can_read_dispatch = true`; API can create tasks and worker can update task status.

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

- `.github/workflows/backend-ci.yml` tests migrations and permissions against disposable PostgreSQL 17. A separate manual job can apply forward-only Alembic upgrades to Supabase `test` only when the explicit repository variable and migration secret are configured.
- Never point backend CI's rollback/re-apply test at the Supabase project.
- The four `NOLOGIN` AgentDock roles and base database/schema grants were provisioned and verified on 2026-11-12. No application tables or Alembic migrations have yet been applied. Keep the three service roles unable to login until you have set unique passwords and stored their connection URLs in the protected secret store.
- A free Render Web Service is suitable for API testing but sleeps after 15 minutes without inbound traffic. Free Render does not offer a free always-on Background Worker. Use a local worker for development/testing or choose an always-on worker host only after reviewing its cost and availability. Do not assume an always-on worker can be run continuously on Render Free.

Render free-tier limits: https://render.com/docs/free

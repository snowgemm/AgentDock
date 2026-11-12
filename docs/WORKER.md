# AgentDock durable worker

**Status on `test`:** The durable worker implementation and PostgreSQL integration tests are present. It uses a dedicated least-privilege database role. With no handler configured, it claims no tasks; tasks remain `QUEUED` without fabricated progress or results. Live Supabase deployment and a real provider run are still pending.

## Run

Local development uses a local PostgreSQL database named `agentdock`. For the Supabase target, use the worker connection URL from [../backend/SUPABASE_SETUP.md](../backend/SUPABASE_SETUP.md): Session Pooler, port 5432, database `postgres`, and the custom role username format `agentdock_worker.PROJECT_REF`.

```bash
AGENTDOCK_WORKER_DATABASE_URL='postgresql+asyncpg://agentdock_worker.PROJECT_REF:PASSWORD@SESSION_POOLER_HOST:5432/postgres' \
AGENTDOCK_WORKER_HANDLER=agent \
AGENTDOCK_OPENAI_MODEL=YOUR_APPROVED_MODEL \
OPENAI_API_KEY=SET_AS_A_SECRET \
python -m app.worker
```

Do not paste real credentials into a shell command that will be saved in shell history or process listings. Use a protected environment/secret store instead. Do not put any provider key in the APK or repository.

`GET /healthz` reports that the poll loop is alive; `GET /readyz` additionally requires a recent successful database round trip and that the worker is not shutting down. `SIGTERM`/`SIGINT` stop claiming, let in-flight tasks finish within `AGENTDOCK_WORKER_SHUTDOWN_GRACE_SECONDS`, then release remaining leases so another worker can reclaim them.

## Why a dispatch table

Tenant tables use forced RLS keyed on `app.current_tenant_id`, so a worker cannot scan them for work. `task_dispatch` holds only routing/lease metadata (task and tenant IDs, availability, lease owner/token/expiry and attempts) and is not RLS protected. Workers claim from it with `FOR UPDATE SKIP LOCKED`, then set tenant context per transaction and touch tenant data only under RLS. A `SECURITY DEFINER` trigger on `tasks` enqueues each new task, so the API role has no access to this table.

## Leases and fencing

- Claim atomically sets a fresh `lease_token`, expiry and increments attempts. It can take over an expired lease.
- A heartbeat extends the lease while the handler runs. If renewal affects no row, the lease is lost and the handler is cancelled.
- Every later write locks the dispatch row by lease token first (the fence). A worker whose lease was reclaimed gets `LeaseLost` and writes nothing.
- Tasks that exceed `max_attempts` (default 3) become `FAILED` with `attempts_exhausted`; retryable handler errors move `RUNNING → RETRYING` with capped exponential backoff and jitter.
- `PAUSED` tasks are not run; terminal/cancelled tasks are dropped from dispatch.

## Transitions

`app/worker/transitions.py` is the worker transition table. Each transition and `task_events` row commit in one transaction under the task row lock with the next per-task sequence. Pause/cancel of a `RUNNING` task is not yet exposed as a complete API workflow.

## Handlers and side effects

A handler implements `TaskHandler.run(context) -> HandlerOutcome` and registers by name. `context.run_step(key, effect)` commits a `STARTED` receipt before the effect, then marks it `COMPLETED`. After a crash, a completed step returns its stored result; a step left `STARTED` raises `UncertainSideEffect` unless declared idempotent. Unknown handler exceptions are not retried; event payloads contain error codes, not exception text.

The currently shipped optional `agent` handler is a single-agent OpenAI path. It does not yet implement the complete multi-agent product roadmap.

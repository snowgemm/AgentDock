# AgentDock durable worker

**Status:** implemented and covered by PostgreSQL integration tests. With no handler configured the worker claims nothing, so tasks stay `QUEUED`; it never fabricates progress or results.

## Run

```bash
AGENTDOCK_WORKER_DATABASE_URL=postgresql+asyncpg://agentdock_worker:...@db/agentdock \
AGENTDOCK_WORKER_HANDLER=<registered handler name> \
AGENTDOCK_WORKER_HEALTH_PORT=8081 \
python -m app.worker
```

`GET /healthz` reports that the poll loop is alive; `GET /readyz` additionally requires a recent successful database round trip and that the worker is not shutting down. `SIGTERM`/`SIGINT` stop claiming, let in-flight tasks finish within `AGENTDOCK_WORKER_SHUTDOWN_GRACE_SECONDS`, then release the remaining leases so another worker can reclaim them immediately.

## Why a dispatch table

Tenant tables use forced RLS keyed on `app.current_tenant_id`, so a worker cannot scan them for work. `task_dispatch` holds only routing data (task and tenant IDs, availability, lease owner/token/expiry, attempts) and is not RLS protected. Workers claim from it with `FOR UPDATE SKIP LOCKED`, then set the tenant context per transaction and touch tenant data only under RLS. A `SECURITY DEFINER` trigger on `tasks` enqueues each new task, so the API role needs no access to the table.

## Leases and fencing

* Claim is one atomic statement that sets a fresh `lease_token`, expiry and increments `attempts`. A claim also takes over a `LEASED` row whose lease expired.
* A heartbeat extends the lease while the handler runs. If the renewal affects no row, the lease is lost and the handler is cancelled.
* Every later write locks the dispatch row **by lease token** first (the fence). A worker whose lease expired and was reclaimed gets `LeaseLost` and writes nothing.
* A task whose attempts exceed `max_attempts` (default 3) becomes `FAILED` with code `attempts_exhausted` instead of running again. Retryable handler errors move `RUNNING → RETRYING` and reschedule with capped exponential backoff and jitter.
* `PAUSED` tasks are not run and do not consume an attempt; terminal/cancelled tasks are dropped from dispatch. Only `QUEUED`/`RETRYING` (and expired-lease `RUNNING`/`RECOVERING`) tasks are claimed.

## Transitions

`app/worker/transitions.py` is the only table of worker transitions; each transition and its `task_events` row commit in one transaction under the task row lock, with the next per-task sequence. Pause/cancel of a `RUNNING` task is **not** supported: the API does not offer it, and `checkpoint()` only lets a handler notice that the task left `RUNNING`.

## Handlers and side effects

A handler implements `TaskHandler.run(context) -> HandlerOutcome` (`app/worker/handlers.py`) and registers by name. `context.run_step(key, effect)` commits a `STARTED` receipt **before** the effect, then marks it `COMPLETED` with the result. After a crash, a completed step returns its stored result; a step left `STARTED` raises `UncertainSideEffect` (the task fails) unless the caller declared the step `idempotent`. Unknown handler exceptions are never retried and event payloads carry error codes only, not exception text.

"""PostgreSQL integration tests for the durable worker (leases, fencing, receipts)."""
from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import Settings
from app.db.session import create_session_factory, set_tenant_context
from app.worker.handlers import (
    HandlerOutcome,
    LeaseLost,
    PermanentError,
    RetryableError,
    TaskCancelled,
    TaskContext,
    UncertainSideEffect,
)
from app.worker.runner import Worker, retry_delay
from app.worker.store import Lease, WorkerStore
from app.worker.transitions import IllegalTransition

ADMIN_URL = os.getenv("AGENTDOCK_TEST_ADMIN_DATABASE_URL")
RUNTIME_URL = os.getenv("AGENTDOCK_TEST_DATABASE_URL")
WORKER_URL = os.getenv("AGENTDOCK_TEST_WORKER_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not (ADMIN_URL and RUNTIME_URL and WORKER_URL),
    reason="PostgreSQL worker integration URLs are not configured; CI always configures them.",
)


@dataclass
class Tenant:
    id: UUID
    user_id: UUID


@dataclass
class Env:
    admin: AsyncEngine
    worker: AsyncEngine
    store: WorkerStore
    tenant: Tenant
    created: list[Tenant] = field(default_factory=list)

    async def make_task(self, tenant: Tenant | None = None, *, max_attempts: int | None = None) -> UUID:
        owner = tenant or self.tenant
        task_id = uuid4()
        async with self.admin.begin() as c:
            await c.execute(
                text(
                    "INSERT INTO tasks (id, tenant_id, created_by_user_id, title, prompt) "
                    "VALUES (:id, :t, :u, 'Title', 'Prompt')"
                ),
                {"id": task_id, "t": owner.id, "u": owner.user_id},
            )
            await c.execute(
                text(
                    "INSERT INTO task_events (id, tenant_id, task_id, sequence, event_type, payload) "
                    "VALUES (gen_random_uuid(), :t, :id, 1, 'TASK_CREATED', '{\"status\": \"QUEUED\"}')"
                ),
                {"id": task_id, "t": owner.id},
            )
            if max_attempts is not None:
                await c.execute(
                    text("UPDATE task_dispatch SET max_attempts = :m WHERE task_id = :id"),
                    {"m": max_attempts, "id": task_id},
                )
        return task_id

    async def new_tenant(self) -> Tenant:
        tenant = Tenant(uuid4(), uuid4())
        async with self.admin.begin() as c:
            await c.execute(
                text("INSERT INTO tenants (id, slug, name) VALUES (:id, :slug, 'T')"),
                {"id": tenant.id, "slug": f"w-{tenant.id.hex[:20]}"},
            )
            await c.execute(text("INSERT INTO users (id) VALUES (:id)"), {"id": tenant.user_id})
            await c.execute(
                text("INSERT INTO tenant_memberships (id, tenant_id, user_id, role) VALUES (gen_random_uuid(), :t, :u, 'owner')"),
                {"t": tenant.id, "u": tenant.user_id},
            )
        self.created.append(tenant)
        return tenant

    async def scalar(self, sql: str, **params: Any) -> Any:
        async with self.admin.begin() as c:
            return (await c.execute(text(sql), params)).scalar()

    async def status(self, task_id: UUID) -> str:
        return await self.scalar("SELECT status FROM tasks WHERE id = :id", id=task_id)

    async def events(self, task_id: UUID) -> list[tuple[int, str]]:
        async with self.admin.begin() as c:
            rows = await c.execute(
                text("SELECT sequence, event_type FROM task_events WHERE task_id = :id ORDER BY sequence"),
                {"id": task_id},
            )
            return [(r.sequence, r.event_type) for r in rows]

    async def expire_lease(self, task_id: UUID) -> None:
        await self.scalar(
            "UPDATE task_dispatch SET lease_expires_at = now() - interval '1 second' "
            "WHERE task_id = :id RETURNING 1", id=task_id,
        )

    async def make_due(self, task_id: UUID) -> None:
        await self.scalar(
            "UPDATE task_dispatch SET available_at = now() - interval '1 second' "
            "WHERE task_id = :id RETURNING 1", id=task_id,
        )


@asynccontextmanager
async def environment() -> AsyncIterator[Env]:
    admin = create_async_engine(ADMIN_URL)
    worker = create_async_engine(WORKER_URL)
    env = Env(admin, worker, WorkerStore(create_session_factory(worker)), Tenant(uuid4(), uuid4()))
    try:
        async with admin.begin() as c:
            # Leftovers from other test modules must not be claimable here.
            await c.execute(text("UPDATE task_dispatch SET state = 'DONE'"))
        env.tenant = await env.new_tenant()
        yield env
    finally:
        async with admin.begin() as c:
            for tenant in env.created:
                for table in ("idempotency_records", "tasks", "tenant_memberships"):
                    await c.execute(text(f"DELETE FROM {table} WHERE tenant_id = :t"), {"t": tenant.id})
                await c.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant.id})
                await c.execute(text("DELETE FROM users WHERE id = :u"), {"u": tenant.user_id})
        await worker.dispose()
        await admin.dispose()


def run(scenario: Callable[[Env], Awaitable[None]]) -> None:
    async def main() -> None:
        async with environment() as env:
            await scenario(env)

    asyncio.run(main())


def settings(**overrides: Any) -> Settings:
    base = dict(
        environment="test", worker_lease_seconds=5, worker_heartbeat_seconds=1,
        worker_poll_seconds=0.1, worker_concurrency=2, worker_task_timeout_seconds=10,
        worker_retry_base_seconds=0.1, worker_retry_max_seconds=0.5, worker_shutdown_grace_seconds=2,
    )
    base.update(overrides)
    return Settings(**base)


async def claim(env: Env, owner: str = "w1", ttl: float = 30) -> Lease | None:
    return await env.store.claim_next(owner, ttl)


# --------------------------------------------------------------------------- claims

def test_new_tasks_are_enqueued_by_trigger_and_claims_are_exclusive() -> None:
    async def scenario(env: Env) -> None:
        ids = {await env.make_task() for _ in range(6)}
        leases = await asyncio.gather(*(claim(env, f"w{i}") for i in range(10)))
        claimed = [lease for lease in leases if lease is not None]
        assert len(claimed) == 6
        assert {lease.task_id for lease in claimed} == ids  # no task claimed twice
        assert len({lease.token for lease in claimed}) == 6
        assert await claim(env) is None

    run(scenario)


def test_expired_lease_is_reclaimed_and_the_old_holder_is_fenced_out() -> None:
    async def scenario(env: Env) -> None:
        task_id = await env.make_task()
        old = await claim(env, "w-old")
        assert old is not None and old.attempt == 1
        assert await claim(env, "w-other") is None  # lease still valid
        assert await env.store.begin_execution(old) is not None
        assert await env.status(task_id) == "RUNNING"

        await env.expire_lease(task_id)
        new = await claim(env, "w-new")
        assert new is not None and new.task_id == task_id
        assert new.attempt == 2 and new.token != old.token

        # The stale holder can no longer write, renew, or finish.
        with pytest.raises(LeaseLost):
            await env.store.append_event(old, "STALE_WRITE", {})
        with pytest.raises(LeaseLost):
            await env.store.finish_success(old, {})
        assert not await env.store.renew(old, 30)

        # The new holder recovers the task: RUNNING -> RECOVERING -> RUNNING.
        assert await env.store.begin_execution(new) is not None
        types = [t for _, t in await env.events(task_id)]
        assert types == ["TASK_CREATED", "TASK_STARTED", "TASK_RECOVERING", "TASK_STARTED"]
        assert "STALE_WRITE" not in types

    run(scenario)


def test_heartbeat_extends_only_a_live_current_lease() -> None:
    async def scenario(env: Env) -> None:
        task_id = await env.make_task()
        lease = await claim(env, ttl=2)
        assert lease is not None
        assert await env.store.renew(lease, 60)
        remaining = await env.scalar(
            "SELECT extract(epoch FROM lease_expires_at - now()) FROM task_dispatch WHERE task_id = :id",
            id=task_id,
        )
        assert remaining > 30
        await env.expire_lease(task_id)
        assert not await env.store.renew(lease, 60)  # expired leases cannot be revived

    run(scenario)


def test_paused_tasks_are_not_executed_and_do_not_burn_attempts() -> None:
    async def scenario(env: Env) -> None:
        task_id = await env.make_task()
        await env.scalar("UPDATE tasks SET status = 'PAUSED' WHERE id = :id RETURNING 1", id=task_id)
        lease = await claim(env)
        assert lease is not None
        assert await env.store.begin_execution(lease) is None
        assert await env.status(task_id) == "PAUSED"
        assert await env.scalar("SELECT attempts FROM task_dispatch WHERE task_id = :id", id=task_id) == 0
        assert await claim(env) is None  # deferred, not hot-looping

    run(scenario)


def test_cancelled_tasks_are_dropped_from_dispatch() -> None:
    async def scenario(env: Env) -> None:
        task_id = await env.make_task()
        await env.scalar("UPDATE tasks SET status = 'CANCELLED' WHERE id = :id RETURNING 1", id=task_id)
        lease = await claim(env)
        assert lease is not None and await env.store.begin_execution(lease) is None
        assert await env.scalar("SELECT state FROM task_dispatch WHERE task_id = :id", id=task_id) == "DONE"

    run(scenario)


# ---------------------------------------------------------------------- transitions

def test_illegal_transition_rolls_back_status_and_event_together() -> None:
    async def scenario(env: Env) -> None:
        task_id = await env.make_task()
        lease = await claim(env)
        assert lease is not None and await env.store.begin_execution(lease) is not None
        before = await env.events(task_id)
        with pytest.raises(IllegalTransition):
            await env.store.transition(lease, "QUEUED", "TASK_BAD", {})
        assert await env.status(task_id) == "RUNNING"
        assert await env.events(task_id) == before

    run(scenario)


def test_events_stay_contiguous_and_ordered_through_a_full_lifecycle() -> None:
    async def scenario(env: Env) -> None:
        task_id = await env.make_task()
        lease = await claim(env)
        assert lease is not None and await env.store.begin_execution(lease) is not None
        await env.store.append_event(lease, "STEP", {"n": 1})
        await env.store.finish_success(lease, {"ok": True})
        events = await env.events(task_id)
        assert [s for s, _ in events] == [1, 2, 3, 4]
        assert [t for _, t in events] == ["TASK_CREATED", "TASK_STARTED", "STEP", "TASK_SUCCEEDED"]
        assert await env.status(task_id) == "SUCCEEDED"
        assert await env.scalar("SELECT state FROM task_dispatch WHERE task_id = :id", id=task_id) == "DONE"

    run(scenario)


# -------------------------------------------------------------------------- receipts

def test_side_effects_run_once_and_uncertain_ones_are_never_blindly_replayed() -> None:
    async def scenario(env: Env) -> None:
        task_id = await env.make_task()
        lease = await claim(env)
        assert lease is not None and await env.store.begin_execution(lease) is not None
        calls = {"n": 0}

        async def effect() -> dict[str, Any]:
            calls["n"] += 1
            return {"receipt": "r-1"}

        assert await env.store.run_step(lease, "send", effect, idempotent=False) == {"receipt": "r-1"}
        # Replaying a completed step returns the stored receipt without running it again.
        assert await env.store.run_step(lease, "send", effect, idempotent=False) == {"receipt": "r-1"}
        assert calls["n"] == 1

        async def crashing() -> dict[str, Any]:
            calls["n"] += 1
            raise RuntimeError("process died after the call may have been sent")

        with pytest.raises(RuntimeError):
            await env.store.run_step(lease, "charge", crashing, idempotent=False)
        assert calls["n"] == 2
        # STARTED receipt persisted: completion is uncertain, so no second attempt.
        with pytest.raises(UncertainSideEffect):
            await env.store.run_step(lease, "charge", effect, idempotent=False)
        assert calls["n"] == 2
        # Explicitly idempotent steps may be retried.
        assert await env.store.run_step(lease, "charge", effect, idempotent=True) == {"receipt": "r-1"}
        assert calls["n"] == 3
        assert await env.scalar("SELECT count(*) FROM task_receipts WHERE task_id = :id", id=task_id) == 2

    run(scenario)


# ----------------------------------------------------------------- tenant isolation

def test_worker_role_sees_tenant_data_only_through_a_tenant_context() -> None:
    async def scenario(env: Env) -> None:
        other = await env.new_tenant()
        mine = await env.make_task()
        theirs = await env.make_task(other)
        factory = create_session_factory(env.worker)

        async with factory() as db, db.begin():  # no tenant context: fail closed
            assert (await db.execute(text("SELECT count(*) FROM tasks"))).scalar() == 0
            assert (await db.execute(text("SELECT count(*) FROM task_events"))).scalar() == 0
        async with factory() as db, db.begin():
            await set_tenant_context(db, env.tenant.id)
            ids = {r[0] for r in await db.execute(text("SELECT id FROM tasks"))}
            assert ids == {mine} and theirs not in ids
        async with factory() as db, db.begin():
            await set_tenant_context(db, env.tenant.id)
            with pytest.raises(DBAPIError):  # cannot write another tenant's rows
                await db.execute(
                    text("INSERT INTO task_events (id, tenant_id, task_id, sequence, event_type) "
                         "VALUES (gen_random_uuid(), :t, :id, 99, 'X')"),
                    {"t": other.id, "id": theirs},
                )

    run(scenario)


def test_runtime_and_worker_roles_keep_least_privilege() -> None:
    async def scenario(env: Env) -> None:
        runtime = create_async_engine(RUNTIME_URL)
        try:
            async with runtime.connect() as c:
                with pytest.raises(DBAPIError):
                    await c.execute(text("SELECT * FROM task_dispatch"))
            async with runtime.connect() as c:
                with pytest.raises(DBAPIError):
                    await c.execute(text("SELECT * FROM task_receipts"))
        finally:
            await runtime.dispose()
        async with env.worker.connect() as c:
            with pytest.raises(DBAPIError):
                await c.execute(text("INSERT INTO tasks (tenant_id, created_by_user_id, title, prompt) "
                                     "VALUES (gen_random_uuid(), gen_random_uuid(), 't', 'p')"))
        async with env.admin.connect() as c:
            result = (await c.execute(
                text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'agentdock_worker'")
            )).one()
        assert result.rolsuper is False and result.rolbypassrls is False

    run(scenario)


# --------------------------------------------------------------------------- runner

class _Handler:
    name = "test"

    def __init__(self, behavior: Callable[[TaskContext], Awaitable[HandlerOutcome]]) -> None:
        self._behavior = behavior

    async def run(self, context: TaskContext) -> HandlerOutcome:
        return await self._behavior(context)


async def _run_worker_until(env: Env, handler: _Handler | None, done: Callable[[], Awaitable[bool]],
                            **overrides: Any) -> Worker:
    worker = Worker(settings(**overrides), env.store, handler)
    runner = asyncio.create_task(worker.run())
    try:
        for _ in range(100):
            if await done():
                break
            await asyncio.sleep(0.1)
    finally:
        worker.request_stop()
        await asyncio.wait_for(runner, timeout=10)
    return worker


def test_worker_runs_a_deterministic_handler_to_success() -> None:
    async def scenario(env: Env) -> None:
        task_id = await env.make_task()

        async def behavior(ctx: TaskContext) -> HandlerOutcome:
            await ctx.emit("NOTE", {"title": ctx.title})
            await ctx.checkpoint()
            return HandlerOutcome({"echo": ctx.prompt})

        await _run_worker_until(env, _Handler(behavior), lambda: _is(env, task_id, "SUCCEEDED"))
        assert await env.status(task_id) == "SUCCEEDED"
        assert [t for _, t in await env.events(task_id)] == [
            "TASK_CREATED", "TASK_STARTED", "NOTE", "TASK_SUCCEEDED"]

    run(scenario)


async def _is(env: Env, task_id: UUID, status: str) -> bool:
    return await env.status(task_id) == status


def test_worker_without_a_handler_leaves_tasks_queued() -> None:
    async def scenario(env: Env) -> None:
        task_id = await env.make_task()
        worker = await _run_worker_until(env, None, lambda: _never(), worker_poll_seconds=0.1)
        await asyncio.sleep(0)
        assert await env.status(task_id) == "QUEUED"
        assert worker.health.claiming is False
        assert [t for _, t in await env.events(task_id)] == ["TASK_CREATED"]

    run(scenario)


async def _never() -> bool:
    await asyncio.sleep(0.5)
    return True


def test_retryable_failures_back_off_and_stop_at_max_attempts() -> None:
    async def scenario(env: Env) -> None:
        task_id = await env.make_task(max_attempts=2)

        async def behavior(ctx: TaskContext) -> HandlerOutcome:
            raise RetryableError("upstream_busy")

        await _run_worker_until(env, _Handler(behavior), lambda: _is(env, task_id, "FAILED"))
        types = [t for _, t in await env.events(task_id)]
        assert types == ["TASK_CREATED", "TASK_STARTED", "TASK_RETRY_SCHEDULED",
                         "TASK_STARTED", "TASK_FAILED"]
        assert await env.scalar("SELECT attempts FROM task_dispatch WHERE task_id = :id", id=task_id) == 2

    run(scenario)


def test_permanent_and_unexpected_errors_fail_without_retry_or_leaking_details() -> None:
    async def scenario(env: Env) -> None:
        permanent = await env.make_task()
        unexpected = await env.make_task()

        async def behavior(ctx: TaskContext) -> HandlerOutcome:
            if ctx.task_id == permanent:
                raise PermanentError("bad_input")
            raise RuntimeError("secret-token-abc123 leaked in message")

        async def both_failed() -> bool:
            return await _is(env, permanent, "FAILED") and await _is(env, unexpected, "FAILED")

        await _run_worker_until(env, _Handler(behavior), both_failed)
        for task_id, code in ((permanent, "bad_input"), (unexpected, "handler_error")):
            attempts = await env.scalar("SELECT attempts FROM task_dispatch WHERE task_id = :id", id=task_id)
            assert attempts == 1
            payload = await env.scalar(
                "SELECT payload::text FROM task_events WHERE task_id = :id AND event_type = 'TASK_FAILED'",
                id=task_id)
            assert code in payload and "secret-token" not in payload

    run(scenario)


def test_worker_crash_mid_run_is_recovered_by_another_worker_without_double_effect() -> None:
    async def scenario(env: Env) -> None:
        task_id = await env.make_task()
        effects = {"n": 0}

        # Worker A claims, starts, completes a side-effect step, then "crashes" (no finish).
        lease_a = await claim(env, "worker-a")
        assert lease_a is not None and await env.store.begin_execution(lease_a) is not None

        async def effect() -> dict[str, Any]:
            effects["n"] += 1
            return {"id": "ext-1"}

        await env.store.run_step(lease_a, "external", effect, idempotent=False)
        await env.expire_lease(task_id)

        async def behavior(ctx: TaskContext) -> HandlerOutcome:
            result = await ctx.run_step("external", effect, idempotent=False)
            return HandlerOutcome(result)

        await _run_worker_until(env, _Handler(behavior), lambda: _is(env, task_id, "SUCCEEDED"))
        assert effects["n"] == 1  # the recovered run reused the receipt
        types = [t for _, t in await env.events(task_id)]
        assert types.count("TASK_RECOVERING") == 1 and types[-1] == "TASK_SUCCEEDED"
        with pytest.raises(LeaseLost):
            await env.store.finish_success(lease_a, {})

    run(scenario)


def test_cooperative_checkpoint_stops_a_task_that_left_running() -> None:
    async def scenario(env: Env) -> None:
        task_id = await env.make_task()
        lease = await claim(env)
        assert lease is not None and await env.store.begin_execution(lease) is not None
        await env.store.checkpoint(lease)  # still RUNNING: fine
        await env.scalar("UPDATE tasks SET status = 'CANCELLED' WHERE id = :id RETURNING 1", id=task_id)
        with pytest.raises(TaskCancelled):
            await env.store.checkpoint(lease)

    run(scenario)


def test_graceful_shutdown_waits_for_in_flight_work() -> None:
    async def scenario(env: Env) -> None:
        task_id = await env.make_task()
        started = asyncio.Event()

        async def behavior(ctx: TaskContext) -> HandlerOutcome:
            started.set()
            await asyncio.sleep(0.5)
            return HandlerOutcome({})

        worker = Worker(settings(), env.store, _Handler(behavior))
        runner = asyncio.create_task(worker.run())
        await asyncio.wait_for(started.wait(), timeout=5)
        worker.request_stop()  # SIGTERM equivalent while a task is running
        await asyncio.wait_for(runner, timeout=10)
        assert await env.status(task_id) == "SUCCEEDED"
        assert worker.health.in_flight == 0

    run(scenario)


def test_retry_delay_is_bounded_exponential_backoff() -> None:
    cfg = settings(worker_retry_base_seconds=2, worker_retry_max_seconds=10)
    assert retry_delay(cfg, 1, jitter=lambda: 0.5) == pytest.approx(2.0)
    assert retry_delay(cfg, 2, jitter=lambda: 0.5) == pytest.approx(4.0)
    assert retry_delay(cfg, 10, jitter=lambda: 1.0) == pytest.approx(12.0)  # cap 10 * 1.2 jitter


def test_worker_stops_its_handler_when_the_lease_is_taken_over() -> None:
    async def scenario(env: Env) -> None:
        task_id = await env.make_task()
        cancelled = asyncio.Event()
        started = asyncio.Event()

        async def behavior(ctx: TaskContext) -> HandlerOutcome:
            started.set()
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                cancelled.set()
                raise
            return HandlerOutcome({})

        worker = Worker(settings(), env.store, _Handler(behavior))
        runner = asyncio.create_task(worker.run())
        await asyncio.wait_for(started.wait(), timeout=5)
        # Simulate another worker reclaiming the task: the lease token changes.
        await env.scalar(
            "UPDATE task_dispatch SET lease_token = gen_random_uuid() WHERE task_id = :id RETURNING 1",
            id=task_id,
        )
        await asyncio.wait_for(cancelled.wait(), timeout=5)  # next heartbeat fails the fence
        worker.request_stop()
        await asyncio.wait_for(runner, timeout=10)
        assert await env.status(task_id) == "RUNNING"  # the stale worker wrote nothing
        assert [t for _, t in await env.events(task_id)] == ["TASK_CREATED", "TASK_STARTED"]

    run(scenario)

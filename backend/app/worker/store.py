"""PostgreSQL persistence for the worker: lease claims and fenced transitions.

Rules enforced here:
* Claiming reads only task_dispatch (routing data, no tenant content).
* Every later write first locks the dispatch row *by lease token* (the fence), so a
  worker whose lease expired and was reclaimed cannot write anything.
* Tenant data is touched only after set_tenant_context, under forced RLS.
* A status change and its event are written in the same transaction.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Task, TaskDispatch, TaskEvent, TaskReceipt
from app.db.session import set_tenant_context
from app.worker.handlers import LeaseLost, TaskCancelled, UncertainSideEffect
from app.worker.transitions import (
    CLAIMABLE_STATUSES,
    LEGAL_TRANSITIONS,
    TERMINAL_STATUSES,
    assert_legal,
)

_CLAIM_SQL = text(
    """
    WITH candidate AS (
        SELECT task_id FROM task_dispatch
        WHERE (state = 'PENDING' AND available_at <= now())
           OR (state = 'LEASED' AND lease_expires_at <= now())
        ORDER BY available_at
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    )
    UPDATE task_dispatch AS d
    SET state = 'LEASED',
        lease_owner = :owner,
        lease_token = gen_random_uuid(),
        lease_expires_at = now() + make_interval(secs => CAST(:ttl AS double precision)),
        attempts = d.attempts + 1,
        updated_at = now()
    FROM candidate
    WHERE d.task_id = candidate.task_id
    RETURNING d.task_id, d.tenant_id, d.lease_token, d.attempts, d.max_attempts
    """
)

_RENEW_SQL = text(
    """
    UPDATE task_dispatch
    SET lease_expires_at = now() + make_interval(secs => CAST(:ttl AS double precision)),
        updated_at = now()
    WHERE task_id = :task_id AND lease_token = :token
      AND state = 'LEASED' AND lease_expires_at > now()
    """
)


@dataclass(frozen=True, slots=True)
class Lease:
    task_id: UUID
    tenant_id: UUID
    token: UUID
    attempt: int
    max_attempts: int


@dataclass(frozen=True, slots=True)
class Execution:
    title: str
    prompt: str


class WorkerStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session_factory

    # ------------------------------------------------------------------ dispatch

    async def claim_next(self, owner: str, lease_seconds: float) -> Lease | None:
        async with self._factory() as db, db.begin():
            row = (
                await db.execute(_CLAIM_SQL, {"owner": owner[:128], "ttl": lease_seconds})
            ).first()
        if row is None:
            return None
        return Lease(row.task_id, row.tenant_id, row.lease_token, row.attempts, row.max_attempts)

    async def renew(self, lease: Lease, lease_seconds: float) -> bool:
        async with self._factory() as db, db.begin():
            result = await db.execute(
                _RENEW_SQL,
                {"ttl": lease_seconds, "task_id": lease.task_id, "token": lease.token},
            )
            return result.rowcount == 1

    async def abandon(self, lease: Lease) -> None:
        """Best-effort early release (shutdown): make the lease immediately reclaimable."""
        async with self._factory() as db, db.begin():
            await db.execute(
                text(
                    "UPDATE task_dispatch SET lease_expires_at = now(), updated_at = now() "
                    "WHERE task_id = :task_id AND lease_token = :token AND state = 'LEASED'"
                ),
                {"task_id": lease.task_id, "token": lease.token},
            )

    async def _lock_lease(self, db: AsyncSession, lease: Lease) -> TaskDispatch:
        """The fence: lock the dispatch row only if this lease token is still current."""
        dispatch = await db.scalar(
            select(TaskDispatch)
            .where(
                TaskDispatch.task_id == lease.task_id,
                TaskDispatch.lease_token == lease.token,
                TaskDispatch.state == "LEASED",
                TaskDispatch.lease_expires_at > func.now(),
            )
            .with_for_update()
        )
        if dispatch is None:
            raise LeaseLost
        return dispatch

    @staticmethod
    def _release(dispatch: TaskDispatch, *, state: str, delay_seconds: float = 0.0,
                 error: str | None = None) -> None:
        dispatch.state = state
        dispatch.lease_token = None
        dispatch.lease_owner = None
        dispatch.lease_expires_at = None
        dispatch.last_error = error
        if state == "PENDING":
            dispatch.available_at = func.now() + timedelta(seconds=delay_seconds)
        dispatch.updated_at = func.now()

    # -------------------------------------------------------------------- events

    @staticmethod
    async def _append_event(
        db: AsyncSession, lease: Lease, event_type: str, payload: dict[str, Any]
    ) -> int:
        """Caller must hold the task row lock so the max+1 allocation is serialized."""
        latest = await db.scalar(
            select(func.coalesce(func.max(TaskEvent.sequence), 0)).where(
                TaskEvent.tenant_id == lease.tenant_id, TaskEvent.task_id == lease.task_id
            )
        )
        sequence = int(latest or 0) + 1
        db.add(
            TaskEvent(
                tenant_id=lease.tenant_id,
                task_id=lease.task_id,
                sequence=sequence,
                event_type=event_type,
                payload=payload,
            )
        )
        await db.flush()
        return sequence

    async def _locked_task(self, db: AsyncSession, lease: Lease) -> Task | None:
        await set_tenant_context(db, lease.tenant_id)
        return await db.scalar(
            select(Task)
            .where(Task.id == lease.task_id, Task.tenant_id == lease.tenant_id)
            .with_for_update()
        )

    async def _move(
        self, db: AsyncSession, lease: Lease, task: Task, target: str,
        event_type: str, payload: dict[str, Any],
    ) -> None:
        assert_legal(task.status, target)
        previous = task.status
        task.status = target
        await db.flush()
        await self._append_event(
            db, lease, event_type, {**payload, "from_status": previous, "to_status": target}
        )

    # ----------------------------------------------------------------- lifecycle

    async def begin_execution(self, lease: Lease) -> Execution | None:
        """Move a claimed task to RUNNING. Returns None when there is nothing to run.

        Raises LeaseLost if the fence no longer holds.
        """
        async with self._factory() as db, db.begin():
            dispatch = await self._lock_lease(db, lease)
            task = await self._locked_task(db, lease)
            if task is None or task.status in TERMINAL_STATUSES:
                self._release(dispatch, state="DONE")
                return None
            if task.status == "PAUSED":
                # Paused (PR #13 semantics): do not burn an attempt; look again later.
                dispatch.attempts = max(0, dispatch.attempts - 1)
                self._release(dispatch, state="PENDING", delay_seconds=30.0)
                return None
            if task.status not in CLAIMABLE_STATUSES:
                self._release(dispatch, state="DONE", error="unclaimable_status")
                return None

            if lease.attempt > lease.max_attempts:
                if task.status == "RUNNING":  # worker died mid-run with no attempts left
                    await self._move(db, lease, task, "RECOVERING", "TASK_RECOVERING",
                                     {"attempt": lease.attempt})
                await self._move(db, lease, task, "FAILED", "TASK_FAILED",
                                 {"code": "attempts_exhausted", "attempt": lease.attempt})
                self._release(dispatch, state="DONE", error="attempts_exhausted")
                return None

            if task.status == "RUNNING":
                await self._move(db, lease, task, "RECOVERING", "TASK_RECOVERING",
                                 {"attempt": lease.attempt})
            await self._move(db, lease, task, "RUNNING", "TASK_STARTED",
                             {"attempt": lease.attempt})
            return Execution(title=task.title, prompt=task.prompt)

    async def append_event(self, lease: Lease, event_type: str, payload: dict[str, Any]) -> int:
        async with self._factory() as db, db.begin():
            await self._lock_lease(db, lease)
            task = await self._locked_task(db, lease)
            if task is None:
                raise LeaseLost
            return await self._append_event(db, lease, event_type, payload)

    async def transition(
        self, lease: Lease, target: str, event_type: str, payload: dict[str, Any]
    ) -> None:
        async with self._factory() as db, db.begin():
            await self._lock_lease(db, lease)
            task = await self._locked_task(db, lease)
            if task is None:
                raise LeaseLost
            await self._move(db, lease, task, target, event_type, payload)

    async def checkpoint(self, lease: Lease) -> None:
        async with self._factory() as db, db.begin():
            await self._lock_lease(db, lease)
            task = await self._locked_task(db, lease)
            if task is None or task.status not in ("RUNNING", "VERIFYING", "WAITING_APPROVAL"):
                raise TaskCancelled

    async def finish_success(self, lease: Lease, summary: dict[str, Any]) -> None:
        async with self._factory() as db, db.begin():
            dispatch = await self._lock_lease(db, lease)
            task = await self._locked_task(db, lease)
            if task is None:
                raise LeaseLost
            await self._move(db, lease, task, "SUCCEEDED", "TASK_SUCCEEDED",
                             {"attempt": lease.attempt, "summary": summary})
            self._release(dispatch, state="DONE")

    async def finish_failure(self, lease: Lease, code: str) -> None:
        async with self._factory() as db, db.begin():
            dispatch = await self._lock_lease(db, lease)
            task = await self._locked_task(db, lease)
            if task is None:
                raise LeaseLost
            if task.status in TERMINAL_STATUSES:
                self._release(dispatch, state="DONE", error=code)
                return
            if "FAILED" in LEGAL_TRANSITIONS.get(task.status, frozenset()):
                await self._move(db, lease, task, "FAILED", "TASK_FAILED",
                                 {"code": code, "attempt": lease.attempt})
            self._release(dispatch, state="DONE", error=code)

    async def schedule_retry(self, lease: Lease, code: str, delay_seconds: float) -> None:
        async with self._factory() as db, db.begin():
            dispatch = await self._lock_lease(db, lease)
            task = await self._locked_task(db, lease)
            if task is None:
                raise LeaseLost
            await self._move(db, lease, task, "RETRYING", "TASK_RETRY_SCHEDULED",
                             {"code": code, "attempt": lease.attempt,
                              "retry_in_seconds": round(delay_seconds, 1)})
            self._release(dispatch, state="PENDING", delay_seconds=delay_seconds, error=code)

    async def release_done(self, lease: Lease, code: str | None = None) -> None:
        async with self._factory() as db, db.begin():
            dispatch = await self._lock_lease(db, lease)
            self._release(dispatch, state="DONE", error=code)

    # ------------------------------------------------------------------ receipts

    async def run_step(
        self, lease: Lease, step_key: str, effect, *, idempotent: bool
    ) -> dict[str, Any]:
        if not step_key or len(step_key) > 128:
            raise ValueError("step_key must be 1-128 characters.")
        async with self._factory() as db, db.begin():
            await self._lock_lease(db, lease)
            await set_tenant_context(db, lease.tenant_id)
            inserted = await db.scalar(
                pg_insert(TaskReceipt)
                .values(
                    tenant_id=lease.tenant_id, task_id=lease.task_id, step_key=step_key,
                    attempt=lease.attempt, state="STARTED",
                )
                .on_conflict_do_nothing(constraint="uq_task_receipts_step")
                .returning(TaskReceipt.id)
            )
            if inserted is None:
                existing = await db.scalar(
                    select(TaskReceipt).where(
                        TaskReceipt.tenant_id == lease.tenant_id,
                        TaskReceipt.task_id == lease.task_id,
                        TaskReceipt.step_key == step_key,
                    )
                )
                if existing is not None and existing.state == "COMPLETED":
                    return dict(existing.result or {})
                if not idempotent:
                    raise UncertainSideEffect
                existing.attempt = lease.attempt  # type: ignore[union-attr]
        # The STARTED receipt is committed above, before the effect runs.
        result = await effect()
        async with self._factory() as db, db.begin():
            await self._lock_lease(db, lease)
            await set_tenant_context(db, lease.tenant_id)
            await db.execute(
                text(
                    "UPDATE task_receipts SET state = 'COMPLETED', result = CAST(:result AS jsonb), "
                    "completed_at = now() WHERE tenant_id = :tenant_id AND task_id = :task_id "
                    "AND step_key = :step_key"
                ),
                {
                    "result": json.dumps(result),
                    "tenant_id": lease.tenant_id,
                    "task_id": lease.task_id,
                    "step_key": step_key,
                },
            )
        return result

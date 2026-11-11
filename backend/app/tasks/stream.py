"""Server-sent events for a task timeline.

Authentication, workspace membership and task visibility are re-checked when the
stream opens (so on every reconnect) and again periodically while it stays open.
No database transaction is held between events: each poll uses a short transaction
with the tenant context set, so RLS applies to every read.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import Enum
from time import monotonic
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.sessions import authenticate_access_token_in_transaction
from app.db.models import Task, TaskEvent, TenantMembership
from app.db.session import set_tenant_context
from app.tasks.notify import TaskEventHub
from app.tasks.schemas import TaskEventRead

TERMINAL = frozenset({"SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED"})
PAGE = 100


class Access(Enum):
    OK = "ok"
    UNAUTHENTICATED = "unauthenticated"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"


@dataclass(frozen=True, slots=True)
class StreamConfig:
    heartbeat_seconds: float
    poll_seconds: float
    max_lifetime_seconds: float
    revalidate_seconds: float


async def check_access(
    factory: async_sessionmaker[AsyncSession], token: str, task_id: UUID
) -> tuple[Access, UUID | None, str | None]:
    """Returns (verdict, tenant_id, task_status)."""
    async with factory() as db, db.begin():
        principal = await authenticate_access_token_in_transaction(db, token)
        if principal is None:
            return Access.UNAUTHENTICATED, None, None
        await set_tenant_context(db, principal.tenant_id)
        membership = await db.scalar(
            select(TenantMembership.id).where(
                TenantMembership.tenant_id == principal.tenant_id,
                TenantMembership.user_id == principal.user_id,
            )
        )
        if membership is None:
            return Access.FORBIDDEN, principal.tenant_id, None
        status = await db.scalar(
            select(Task.status).where(Task.id == task_id, Task.tenant_id == principal.tenant_id)
        )
        if status is None:
            return Access.NOT_FOUND, principal.tenant_id, None
        return Access.OK, principal.tenant_id, status


async def read_events_after(
    factory: async_sessionmaker[AsyncSession], tenant_id: UUID, task_id: UUID, after: int
) -> tuple[list[TaskEventRead], str | None]:
    async with factory() as db, db.begin():
        await set_tenant_context(db, tenant_id)
        rows = (
            await db.scalars(
                select(TaskEvent)
                .where(TaskEvent.tenant_id == tenant_id, TaskEvent.task_id == task_id,
                       TaskEvent.sequence > after)
                .order_by(TaskEvent.sequence.asc())
                .limit(PAGE)
            )
        ).all()
        status = await db.scalar(
            select(Task.status).where(Task.id == task_id, Task.tenant_id == tenant_id)
        )
        return [TaskEventRead.model_validate(row) for row in rows], status


def frame(event: str, data: object, event_id: int | None = None) -> str:
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data, separators=(',', ':'))}")
    return "\n".join(lines) + "\n\n"


async def event_stream(
    *,
    factory: async_sessionmaker[AsyncSession],
    hub: TaskEventHub | None,
    config: StreamConfig,
    token: str,
    tenant_id: UUID,
    task_id: UUID,
    after_sequence: int,
) -> AsyncIterator[str]:
    wake = hub.subscribe(task_id) if hub is not None else asyncio.Event()
    started = monotonic()
    last_validated = started
    last_sent = started
    last_sequence = after_sequence
    try:
        yield "retry: 3000\n\n"
        while True:
            now = monotonic()
            if now - started >= config.max_lifetime_seconds:
                yield frame("reconnect", {"last_sequence": last_sequence})
                return
            if now - last_validated >= config.revalidate_seconds:
                verdict, _, _ = await check_access(factory, token, task_id)
                if verdict is not Access.OK:
                    yield frame("error", {"code": "access_revoked"})
                    return
                last_validated = monotonic()

            wake.clear()  # clear before reading so a commit during the read re-wakes us
            events, status = await read_events_after(factory, tenant_id, task_id, last_sequence)
            for item in events:
                yield frame("task_event", item.model_dump(mode="json"), item.sequence)
                last_sequence = item.sequence
                last_sent = monotonic()
            if len(events) == PAGE:
                continue  # more history is waiting; keep draining without sleeping
            if status in TERMINAL and not events:
                yield frame("end", {"status": status, "last_sequence": last_sequence})
                return
            if status is None:
                yield frame("error", {"code": "task_not_found"})
                return

            remaining = config.max_lifetime_seconds - (monotonic() - started)
            wait_for = min(config.poll_seconds, config.heartbeat_seconds, max(0.01, remaining))
            try:
                await asyncio.wait_for(wake.wait(), timeout=wait_for)
            except asyncio.TimeoutError:
                pass
            if monotonic() - last_sent >= config.heartbeat_seconds:
                yield ": heartbeat\n\n"
                last_sent = monotonic()
    finally:
        if hub is not None:
            hub.unsubscribe(task_id, wake)

"""Approval and audit persistence shared by the API and the worker.

Every function expects an AsyncSession that is inside a transaction with the tenant
context already set; forced RLS is the isolation boundary and each query also filters
on tenant_id explicitly.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Approval, AuditEvent
from app.policy.action import ActionRecord
from app.policy.redact import redact


class ApprovalError(Exception):
    """A client-facing approval problem; ``code`` is stable and safe to return."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ApprovalRejected(Exception):
    """The executor may not run the action; ``code`` names why."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ApprovalRef:
    id: UUID
    digest: str
    status: str  # effective status: PENDING/APPROVED/DENIED/REVOKED/CONSUMED/EXPIRED
    expires_at: datetime


def effective_status(approval: Approval, now: datetime) -> str:
    if approval.status in ("PENDING", "APPROVED") and approval.expires_at <= now:
        return "EXPIRED"
    return approval.status


async def db_now(db: AsyncSession) -> datetime:
    return await db.scalar(select(func.now()))  # type: ignore[return-value]


def to_ref(approval: Approval, now: datetime) -> ApprovalRef:
    return ApprovalRef(approval.id, approval.action_digest, effective_status(approval, now),
                       approval.expires_at)


async def write_audit(
    db: AsyncSession, *, tenant_id: UUID, task_id: UUID | None, actor_type: str,
    actor_user_id: UUID | None, action: str, target: str, outcome: str,
    policy_version: str | None, details: dict[str, Any],
) -> None:
    db.add(
        AuditEvent(
            tenant_id=tenant_id, task_id=task_id, actor_type=actor_type,
            actor_user_id=actor_user_id, action=action[:64], target=target[:256],
            outcome=outcome[:32], policy_version=policy_version, details=redact(details),
        )
    )
    await db.flush()


async def create_or_get_pending(
    db: AsyncSession, *, tenant_id: UUID, task_id: UUID, requested_for: UUID,
    action: ActionRecord, ttl_seconds: float,
) -> ApprovalRef:
    """Idempotent per (task, digest): a crashed worker re-requesting gets the same row."""
    now = await db_now(db)
    await db.execute(
        update(Approval)
        .where(Approval.tenant_id == tenant_id, Approval.task_id == task_id,
               Approval.action_digest == action.digest,
               Approval.status.in_(("PENDING", "APPROVED")), Approval.expires_at <= now)
        .values(status="EXPIRED")
    )
    inserted = await db.scalar(
        pg_insert(Approval)
        .values(
            tenant_id=tenant_id, task_id=task_id, requested_for_user_id=requested_for,
            tool_name=action.tool[:64], action_digest=action.digest,
            action=action.display_json(), policy_version=action.policy_version,
            status="PENDING", expires_at=now + timedelta(seconds=ttl_seconds),
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "task_id", "action_digest"],
                                index_where=Approval.status.in_(("PENDING", "APPROVED")))
        .returning(Approval.id)
    )
    row = await db.scalar(
        select(Approval).where(
            Approval.tenant_id == tenant_id, Approval.task_id == task_id,
            Approval.action_digest == action.digest,
            Approval.status.in_(("PENDING", "APPROVED")),
        )
    )
    assert row is not None and (inserted is None or inserted == row.id)
    return to_ref(row, now)


async def get_ref(db: AsyncSession, tenant_id: UUID, approval_id: UUID) -> ApprovalRef | None:
    now = await db_now(db)
    row = await db.scalar(
        select(Approval).where(Approval.id == approval_id, Approval.tenant_id == tenant_id)
    )
    return to_ref(row, now) if row is not None else None


async def decide(
    db: AsyncSession, *, tenant_id: UUID, approval_id: UUID, decider_user_id: UUID,
    approve: bool, digest: str,
) -> Approval:
    """Record a human decision. The caller echoes the digest of what it displayed."""
    now = await db_now(db)
    row = await db.scalar(
        select(Approval)
        .where(Approval.id == approval_id, Approval.tenant_id == tenant_id)
        .with_for_update()
    )
    if row is None:
        raise ApprovalError("not_found")
    if row.action_digest != digest:
        raise ApprovalError("digest_mismatch")
    status = effective_status(row, now)
    if status == "EXPIRED":
        row.status = "EXPIRED"
        await db.flush()
        raise ApprovalError("expired")
    if status != "PENDING":
        raise ApprovalError("not_pending")
    row.status = "APPROVED" if approve else "DENIED"
    row.decided_at = now
    row.decided_by_user_id = decider_user_id
    await db.flush()
    return row


async def revoke(db: AsyncSession, *, tenant_id: UUID, approval_id: UUID, user_id: UUID) -> Approval:
    now = await db_now(db)
    row = await db.scalar(
        select(Approval)
        .where(Approval.id == approval_id, Approval.tenant_id == tenant_id)
        .with_for_update()
    )
    if row is None:
        raise ApprovalError("not_found")
    if effective_status(row, now) not in ("PENDING", "APPROVED"):
        raise ApprovalError("not_revocable")
    row.status = "REVOKED"
    row.decided_at = now
    row.decided_by_user_id = user_id
    await db.flush()
    return row


async def consume(db: AsyncSession, *, tenant_id: UUID, task_id: UUID, digest: str) -> UUID:
    """Atomically spend one APPROVED, unexpired approval that matches the exact digest."""
    spent = await db.scalar(
        update(Approval)
        .where(Approval.tenant_id == tenant_id, Approval.task_id == task_id,
               Approval.action_digest == digest, Approval.status == "APPROVED",
               Approval.expires_at > func.now())
        .values(status="CONSUMED", consumed_at=func.now())
        .returning(Approval.id)
    )
    if spent is not None:
        return spent
    now = await db_now(db)
    latest = await db.scalar(
        select(Approval)
        .where(Approval.tenant_id == tenant_id, Approval.task_id == task_id,
               Approval.action_digest == digest)
        .order_by(Approval.created_at.desc())
        .limit(1)
    )
    if latest is None:
        raise ApprovalRejected("approval_missing")
    reason = {
        "DENIED": "approval_denied", "REVOKED": "approval_revoked",
        "CONSUMED": "approval_replayed", "EXPIRED": "approval_expired",
        "PENDING": "approval_pending",
    }.get(effective_status(latest, now), "approval_expired")
    raise ApprovalRejected(reason)

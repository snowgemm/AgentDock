from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey,
    ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint,
    Uuid, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(63), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True, unique=True)
    display_name: Mapped[str | None] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AuthIdentity(Base):
    """Stable mapping from a verified external issuer/subject pair to one AgentDock account."""

    __tablename__ = "auth_identities"
    __table_args__ = (
        UniqueConstraint("issuer", "subject", name="uq_auth_identities_issuer_subject"),
        Index("ix_auth_identities_user_id", "user_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    issuer: Mapped[str] = mapped_column(String(512), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    default_tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_authenticated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class UserSession(Base):
    """One revocable AgentDock login session bound to a user and workspace."""

    __tablename__ = "user_sessions"
    __table_args__ = (
        Index("ix_user_sessions_user_created", "user_id", "created_at"),
        Index("ix_user_sessions_expires_at", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SessionToken(Base):
    """Only one-way token hashes are stored; used refresh tokens remain for replay detection."""

    __tablename__ = "session_tokens"
    __table_args__ = (
        CheckConstraint("token_type IN ('ACCESS', 'REFRESH')", name="ck_session_tokens_type"),
        UniqueConstraint("token_hash", name="uq_session_tokens_hash"),
        Index("ix_session_tokens_session_type", "session_id", "token_type"),
        Index("ix_session_tokens_expires_at", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("user_sessions.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_type: Mapped[str] = mapped_column(String(8), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TenantMembership(Base):
    __tablename__ = "tenant_memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_memberships_tenant_user"),
        CheckConstraint("role IN ('owner', 'admin', 'member')", name="ck_memberships_role"),
        Index("ix_memberships_user_id", "user_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'member'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_tasks_id_tenant"),
        ForeignKeyConstraint(
            ["tenant_id", "created_by_user_id"],
            ["tenant_memberships.tenant_id", "tenant_memberships.user_id"],
            name="fk_tasks_creator_membership",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN ('QUEUED', 'PLANNING', 'RUNNING', 'WAITING_APPROVAL', "
            "'VERIFYING', 'SUCCEEDED', 'FAILED', 'CANCELLED', 'PAUSED', "
            "'RETRYING', 'RECOVERING', 'EXPIRED')",
            name="ck_tasks_status",
        ),
        Index("ix_tasks_tenant_status_created", "tenant_id", "status", "created_at"),
        Index("ix_tasks_tenant_created_id", "tenant_id", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    created_by_user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'QUEUED'")
    )
    attributes: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class TaskEvent(Base):
    __tablename__ = "task_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "tenant_id"], ["tasks.id", "tasks.tenant_id"],
            name="fk_task_events_task_tenant", ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id", "task_id", "sequence", name="uq_task_events_task_sequence"
        ),
        Index("ix_task_events_tenant_occurred", "tenant_id", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "actor_user_id", "idempotency_key",
            name="uq_idempotency_tenant_actor_key",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "actor_user_id"],
            ["tenant_memberships.tenant_id", "tenant_memberships.user_id"],
            name="fk_idempotency_actor_membership",
            ondelete="RESTRICT",
        ),
        CheckConstraint("state IN ('IN_PROGRESS', 'COMPLETED')", name="ck_idempotency_state"),
        Index("ix_idempotency_expires_at", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    actor_user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'IN_PROGRESS'")
    )
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_payload: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TaskDispatch(Base):
    """Routing/lease data for the worker.

    Intentionally NOT tenant-RLS protected so a worker can find ready work across
    tenants. It holds only identifiers, timing and lease fields; the worker must set
    the tenant GUC and read or write tenant data under forced RLS after a claim.
    """

    __tablename__ = "task_dispatch"
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "tenant_id"], ["tasks.id", "tasks.tenant_id"],
            name="fk_task_dispatch_task_tenant", ondelete="CASCADE",
        ),
        CheckConstraint("state IN ('PENDING', 'LEASED', 'DONE')", name="ck_task_dispatch_state"),
        CheckConstraint("attempts >= 0 AND max_attempts >= 1", name="ck_task_dispatch_attempts"),
        Index("ix_task_dispatch_state_available", "state", "available_at"),
    )

    task_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'PENDING'")
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_token: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("3"))
    last_error: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TaskReceipt(Base):
    """Durable record that a side-effecting step was started and whether it completed.

    The STARTED row is committed before the effect runs, so a crash leaves proof that
    completion is uncertain and the step must not be blindly replayed.
    """

    __tablename__ = "task_receipts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "tenant_id"], ["tasks.id", "tasks.tenant_id"],
            name="fk_task_receipts_task_tenant", ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "task_id", "step_key", name="uq_task_receipts_step"),
        CheckConstraint("state IN ('STARTED', 'COMPLETED')", name="ck_task_receipts_state"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    step_key: Mapped[str] = mapped_column(String(128), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(12), nullable=False)
    result: Mapped[dict | None] = mapped_column(JSONB)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

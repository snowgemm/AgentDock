"""Complete identity, worker and approval schema to match the ORM.

Revision ID: 20261112_0002
Revises: 20261101_0001
Create Date: 2026-11-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261112_0002"
down_revision: Union[str, None] = "20261101_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# These tables are tenant-owned. Worker routing data in task_dispatch is
# deliberately unscoped so a worker can claim ready work across tenants.
TENANT_TABLES = (
    "tenant_memberships",
    "tasks",
    "task_events",
    "idempotency_records",
    "task_receipts",
    "task_checkpoints",
    "approvals",
    "audit_events",
)


def upgrade() -> None:
    # The initial migration made email mandatory, while the ORM and identity
    # flow allow users without a verified email address.
    op.alter_column("users", "email", existing_type=sa.String(length=320), nullable=True)

    op.create_index(
        "ix_tasks_tenant_created_id", "tasks",
        ["tenant_id", "created_at", "id"],
    )

    op.create_table(
        "auth_identities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("issuer", sa.String(length=512), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("default_tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_authenticated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["default_tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("issuer", "subject", name="uq_auth_identities_issuer_subject"),
    )
    op.create_index("ix_auth_identities_user_id", "auth_identities", ["user_id"])

    op.create_table(
        "user_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_sessions_user_created", "user_sessions", ["user_id", "created_at"])
    op.create_index("ix_user_sessions_expires_at", "user_sessions", ["expires_at"])

    op.create_table(
        "session_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("token_type", sa.String(length=8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("token_type IN ('ACCESS', 'REFRESH')", name="ck_session_tokens_type"),
        sa.ForeignKeyConstraint(["session_id"], ["user_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_session_tokens_hash"),
    )
    op.create_index("ix_session_tokens_session_type", "session_tokens", ["session_id", "token_type"])
    op.create_index("ix_session_tokens_expires_at", "session_tokens", ["expires_at"])

    op.create_table(
        "task_dispatch",
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("state", sa.String(length=16), server_default=sa.text("'PENDING'"), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default=sa.text("3"), nullable=False),
        sa.Column("last_error", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("state IN ('PENDING', 'LEASED', 'DONE')", name="ck_task_dispatch_state"),
        sa.CheckConstraint("attempts >= 0 AND max_attempts >= 1", name="ck_task_dispatch_attempts"),
        sa.ForeignKeyConstraint(
            ["task_id", "tenant_id"], ["tasks.id", "tasks.tenant_id"],
            name="fk_task_dispatch_task_tenant", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("task_id"),
    )
    op.create_index("ix_task_dispatch_state_available", "task_dispatch", ["state", "available_at"])

    op.create_table(
        "task_receipts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_key", sa.String(length=128), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=12), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("state IN ('STARTED', 'COMPLETED')", name="ck_task_receipts_state"),
        sa.ForeignKeyConstraint(
            ["task_id", "tenant_id"], ["tasks.id", "tasks.tenant_id"],
            name="fk_task_receipts_task_tenant", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "task_id", "step_key", name="uq_task_receipts_step"),
    )

    op.create_table(
        "task_checkpoints",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("state", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["task_id", "tenant_id"], ["tasks.id", "tasks.tenant_id"],
            name="fk_task_checkpoints_task_tenant", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "task_id", "iteration", name="uq_task_checkpoints_iteration"),
    )

    op.create_table(
        "approvals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requested_for_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool_name", sa.String(length=64), nullable=False),
        sa.Column("action_digest", sa.String(length=64), nullable=False),
        sa.Column("action", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("policy_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=12), server_default=sa.text("'PENDING'"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('PENDING', 'APPROVED', 'DENIED', 'REVOKED', 'CONSUMED', 'EXPIRED')",
            name="ck_approvals_status",
        ),
        sa.ForeignKeyConstraint(
            ["task_id", "tenant_id"], ["tasks.id", "tasks.tenant_id"],
            name="fk_approvals_task_tenant", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_approvals_active_digest", "approvals",
        ["tenant_id", "task_id", "action_digest"],
        unique=True,
        postgresql_where=sa.text("status IN ('PENDING', 'APPROVED')"),
    )
    op.create_index("ix_approvals_task", "approvals", ["tenant_id", "task_id", "created_at"])

    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_type", sa.String(length=12), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target", sa.String(length=256), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("policy_version", sa.String(length=32), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("actor_type IN ('user', 'agent', 'system')", name="ck_audit_actor_type"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_events_tenant_created", "audit_events", ["tenant_id", "created_at"])

    # Policies use only transaction-local, server-set tenant context. The
    # client-supplied tenant identifier is never an authorization decision.
    tenant_expression = (
        "tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
    )
    for table_name in ("task_receipts", "task_checkpoints", "approvals", "audit_events"):
        op.execute(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY "{table_name}_tenant_isolation" ON "{table_name}" '
            f"USING ({tenant_expression}) WITH CHECK ({tenant_expression})"
        )


def downgrade() -> None:
    for table_name in ("audit_events", "approvals", "task_checkpoints", "task_receipts"):
        op.drop_table(table_name)
    op.drop_index("ix_task_dispatch_state_available", table_name="task_dispatch")
    op.drop_table("task_dispatch")
    op.drop_index("ix_session_tokens_expires_at", table_name="session_tokens")
    op.drop_index("ix_session_tokens_session_type", table_name="session_tokens")
    op.drop_table("session_tokens")
    op.drop_index("ix_user_sessions_expires_at", table_name="user_sessions")
    op.drop_index("ix_user_sessions_user_created", table_name="user_sessions")
    op.drop_table("user_sessions")
    op.drop_index("ix_auth_identities_user_id", table_name="auth_identities")
    op.drop_table("auth_identities")
    op.drop_index("ix_tasks_tenant_created_id", table_name="tasks")
    op.alter_column("users", "email", existing_type=sa.String(length=320), nullable=False)

"""Grant least-privilege access to the API and worker roles.

Revision ID: 20261112_0008
Revises: 20261113_0007

The four AgentDock database roles must be provisioned before Alembic runs.
This migration is the source of truth for application table grants so fresh
deployments receive the same permissions as the PostgreSQL CI database.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "20261112_0008"
down_revision: Union[str, None] = "20261113_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # API control plane. It cannot read or write the worker dispatch queue.
    op.execute(
        "GRANT SELECT, INSERT ON TABLE tenants, users TO agentdock_runtime"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE "
        "ON TABLE auth_identities, user_sessions, session_tokens "
        "TO agentdock_runtime"
    )
    op.execute("GRANT SELECT, INSERT ON TABLE tenant_memberships TO agentdock_runtime")
    op.execute("GRANT SELECT, INSERT ON TABLE tasks TO agentdock_runtime")
    op.execute("GRANT SELECT, INSERT ON TABLE task_events TO agentdock_runtime")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE "
        "ON TABLE idempotency_records TO agentdock_runtime"
    )
    op.execute("GRANT SELECT, UPDATE ON TABLE approvals TO agentdock_runtime")
    # SQLAlchemy INSERT ... RETURNING created_at needs SELECT on that column.
    # Keep the append-only audit payload unreadable to both service roles.
    op.execute(
        "GRANT SELECT (created_at), INSERT ON TABLE audit_events TO agentdock_runtime"
    )

    # Worker: routing metadata plus tenant-scoped data protected by forced RLS.
    op.execute("GRANT SELECT, UPDATE ON TABLE task_dispatch TO agentdock_worker")
    op.execute("GRANT SELECT ON TABLE tasks TO agentdock_worker")
    op.execute(
        "GRANT UPDATE (status, updated_at) ON TABLE tasks TO agentdock_worker"
    )
    op.execute("GRANT SELECT, INSERT ON TABLE task_events TO agentdock_worker")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON TABLE task_receipts TO agentdock_worker"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON TABLE task_checkpoints TO agentdock_worker"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON TABLE approvals TO agentdock_worker"
    )
    op.execute(
        "GRANT SELECT (created_at), INSERT ON TABLE audit_events TO agentdock_worker"
    )
    op.execute("GRANT SELECT ON TABLE tenant_memberships TO agentdock_worker")
    op.execute(
        "GRANT SELECT (id, is_active) ON TABLE users TO agentdock_worker"
    )


def downgrade() -> None:
    op.execute(
        "REVOKE SELECT (id, is_active) ON TABLE users FROM agentdock_worker"
    )
    op.execute("REVOKE SELECT ON TABLE tenant_memberships FROM agentdock_worker")
    op.execute(
        "REVOKE SELECT (created_at), INSERT ON TABLE audit_events FROM agentdock_worker"
    )
    op.execute(
        "REVOKE SELECT, INSERT, UPDATE ON TABLE approvals FROM agentdock_worker"
    )
    op.execute(
        "REVOKE SELECT, INSERT, UPDATE ON TABLE task_checkpoints FROM agentdock_worker"
    )
    op.execute(
        "REVOKE SELECT, INSERT, UPDATE ON TABLE task_receipts FROM agentdock_worker"
    )
    op.execute("REVOKE SELECT, INSERT ON TABLE task_events FROM agentdock_worker")
    op.execute(
        "REVOKE UPDATE (status, updated_at) ON TABLE tasks FROM agentdock_worker"
    )
    op.execute("REVOKE SELECT ON TABLE tasks FROM agentdock_worker")
    op.execute("REVOKE SELECT, UPDATE ON TABLE task_dispatch FROM agentdock_worker")

    op.execute(
        "REVOKE SELECT (created_at), INSERT ON TABLE audit_events FROM agentdock_runtime"
    )
    op.execute("REVOKE SELECT, UPDATE ON TABLE approvals FROM agentdock_runtime")
    op.execute("REVOKE SELECT, INSERT ON TABLE task_events FROM agentdock_runtime")
    op.execute("REVOKE SELECT, INSERT ON TABLE tasks FROM agentdock_runtime")
    op.execute(
        "REVOKE SELECT, INSERT ON TABLE tenant_memberships FROM agentdock_runtime"
    )
    op.execute(
        "REVOKE SELECT, INSERT, UPDATE, DELETE "
        "ON TABLE idempotency_records FROM agentdock_runtime"
    )
    op.execute(
        "REVOKE SELECT, INSERT, UPDATE "
        "ON TABLE auth_identities, user_sessions, session_tokens "
        "FROM agentdock_runtime"
    )
    op.execute("REVOKE SELECT, INSERT ON TABLE tenants, users FROM agentdock_runtime")

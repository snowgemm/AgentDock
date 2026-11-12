"""Add durable worker dispatch leases and execution receipts.

Revision ID: 20261111_0004
Revises: 20261105_0003
Create Date: 2026-11-11

task_dispatch is deliberately not tenant-RLS protected: it carries only routing and
lease data so a worker can find ready work across tenants without weakening RLS on
tenant data. task_receipts is tenant-scoped under forced RLS like the other tenant
tables. A SECURITY DEFINER trigger enqueues every new task so the API role needs no
privileges on task_dispatch at all.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261111_0004"
down_revision: Union[str, None] = "20261105_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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
    tenant_expression = (
        "tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
    )
    op.execute('ALTER TABLE "task_receipts" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "task_receipts" FORCE ROW LEVEL SECURITY')
    op.execute(
        'CREATE POLICY "task_receipts_tenant_isolation" ON "task_receipts" '
        f"USING ({tenant_expression}) WITH CHECK ({tenant_expression})"
    )

    # Keep the trigger's SECURITY DEFINER owner separate from both the API
    # runtime and the migration owner. It can only enqueue routing identifiers.
    op.execute("CREATE SCHEMA agentdock_private AUTHORIZATION agentdock_migrator")
    op.execute("GRANT USAGE, CREATE ON SCHEMA agentdock_private TO agentdock_dispatcher")
    op.execute("GRANT USAGE ON SCHEMA public TO agentdock_dispatcher")
    op.execute("GRANT INSERT ON TABLE public.task_dispatch TO agentdock_dispatcher")
    # ON CONFLICT (task_id) reads the conflict target, so grant only that column.
    op.execute(
        "GRANT SELECT (task_id) ON TABLE public.task_dispatch TO agentdock_dispatcher"
    )
    op.execute("SET LOCAL ROLE agentdock_dispatcher")
    op.execute(
        """
        CREATE FUNCTION agentdock_private.enqueue_task_dispatch() RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
        BEGIN
            INSERT INTO public.task_dispatch (task_id, tenant_id)
            VALUES (NEW.id, NEW.tenant_id)
            ON CONFLICT (task_id) DO NOTHING;
            RETURN NEW;
        END;
        $function$
        """
    )
    # The function owner grants CREATE TRIGGER permission to the migration role.
    op.execute(
        "GRANT EXECUTE ON FUNCTION agentdock_private.enqueue_task_dispatch() "
        "TO agentdock_migrator"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION agentdock_private.enqueue_task_dispatch() FROM PUBLIC"
    )
    op.execute("RESET ROLE")
    op.execute(
        """
        CREATE TRIGGER tasks_enqueue_dispatch AFTER INSERT ON public.tasks
        FOR EACH ROW EXECUTE FUNCTION agentdock_private.enqueue_task_dispatch()
        """
    )
    op.execute("SET LOCAL ROLE agentdock_dispatcher")
    op.execute(
        "REVOKE EXECUTE ON FUNCTION agentdock_private.enqueue_task_dispatch() "
        "FROM agentdock_migrator"
    )
    op.execute("RESET ROLE")

    # Backfill tasks created before this migration. tasks has FORCE RLS, so scope the
    # transaction to each tenant in turn (tenants itself is not RLS protected).
    op.execute(
        """
        DO $$
        DECLARE tenant record;
        BEGIN
            FOR tenant IN SELECT id FROM tenants LOOP
                PERFORM set_config('app.current_tenant_id', tenant.id::text, true);
                INSERT INTO task_dispatch (task_id, tenant_id, state)
                SELECT id, tenant_id,
                       CASE WHEN status IN ('QUEUED', 'RETRYING', 'PAUSED', 'RUNNING', 'RECOVERING')
                            THEN 'PENDING' ELSE 'DONE' END
                FROM tasks WHERE tenant_id = tenant.id
                ON CONFLICT (task_id) DO NOTHING;
            END LOOP;
            PERFORM set_config('app.current_tenant_id', '', true);
        END
        $$
        """
    )


def downgrade() -> None:
    # Dropping task_dispatch discards in-flight leases: stop all workers first.
    op.execute("DROP TRIGGER IF EXISTS tasks_enqueue_dispatch ON tasks")
    # The private trigger function is owned by the isolated dispatcher role.
    op.execute("SET LOCAL ROLE agentdock_dispatcher")
    op.execute("DROP FUNCTION IF EXISTS agentdock_private.enqueue_task_dispatch()")
    op.execute("RESET ROLE")
    op.execute("DROP SCHEMA IF EXISTS agentdock_private")
    op.execute(
        "REVOKE SELECT (task_id), INSERT ON TABLE public.task_dispatch "
        "FROM agentdock_dispatcher"
    )
    op.drop_table("task_receipts")
    op.drop_table("task_dispatch")

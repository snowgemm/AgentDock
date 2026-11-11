"""Add agent checkpoints.

Revision ID: 20261112_0006
Revises: 20261111_0005
Create Date: 2026-11-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261112_0006"
down_revision: Union[str, None] = "20261111_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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
    expression = "tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
    op.execute('ALTER TABLE "task_checkpoints" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "task_checkpoints" FORCE ROW LEVEL SECURITY')
    op.execute(
        'CREATE POLICY "task_checkpoints_tenant_isolation" ON "task_checkpoints" '
        f"USING ({expression}) WITH CHECK ({expression})"
    )


def downgrade() -> None:
    op.drop_table("task_checkpoints")

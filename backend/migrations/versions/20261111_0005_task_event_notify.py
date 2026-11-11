"""Notify listeners when task events are committed.

Revision ID: 20261111_0005
Revises: 20261111_0004
Create Date: 2026-11-11

NOTIFY is only a wake-up hint (task_events stays the source of truth): the payload is
"tenant_id:task_id:sequence" and carries no task content. It fires on commit for every
writer (API, worker, future code) without those writers needing to know about it.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "20261111_0005"
down_revision: Union[str, None] = "20261111_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION agentdock_notify_task_event() RETURNS trigger
        LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
            PERFORM pg_notify(
                'agentdock_task_events',
                NEW.tenant_id::text || ':' || NEW.task_id::text || ':' || NEW.sequence::text
            );
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER task_events_notify AFTER INSERT ON task_events "
        "FOR EACH ROW EXECUTE FUNCTION agentdock_notify_task_event()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS task_events_notify ON task_events")
    op.execute("DROP FUNCTION IF EXISTS agentdock_notify_task_event()")

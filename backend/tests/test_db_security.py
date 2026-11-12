import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

ADMIN_DATABASE_URL = os.getenv("AGENTDOCK_TEST_ADMIN_DATABASE_URL")
RUNTIME_DATABASE_URL = os.getenv("AGENTDOCK_TEST_DATABASE_URL")
POSTGRES_TESTS_ENABLED = bool(ADMIN_DATABASE_URL and RUNTIME_DATABASE_URL)

pytestmark = pytest.mark.skipif(
    not POSTGRES_TESTS_ENABLED,
    reason="PostgreSQL integration URLs are not configured; CI always configures them.",
)


def test_runtime_role_is_restricted_and_tenant_tables_force_rls() -> None:
    async def check_database() -> None:
        admin_engine = create_async_engine(ADMIN_DATABASE_URL, pool_pre_ping=True)
        try:
            async with admin_engine.connect() as connection:
                roles = (
                    await connection.execute(
                        text(
                            "SELECT rolname, rolsuper, rolbypassrls, rolcanlogin FROM pg_roles "
                            "WHERE rolname IN ('agentdock_runtime', 'agentdock_worker', 'agentdock_dispatcher')"
                        )
                    )
                ).all()
                assert {row.rolname for row in roles} == {
                    "agentdock_runtime", "agentdock_worker", "agentdock_dispatcher"
                }
                assert all(row.rolsuper is False and row.rolbypassrls is False for row in roles)
                assert next(row for row in roles if row.rolname == "agentdock_dispatcher").rolcanlogin is False

                rows = (
                    await connection.execute(
                        text(
                            "SELECT relname, relrowsecurity, relforcerowsecurity, "
                            "pg_get_userbyid(relowner) AS owner "
                            "FROM pg_class "
                            "WHERE relnamespace = 'public'::regnamespace "
                            "AND relname IN "
                            "('tenant_memberships', 'tasks', 'task_events', "
                            "'idempotency_records', 'task_receipts', 'task_checkpoints', "
                            "'approvals', 'audit_events')"
                        )
                    )
                ).all()
                assert len(rows) == 8
                assert all(row.relrowsecurity and row.relforcerowsecurity for row in rows)
                assert all(row.owner == "agentdock_migrator" for row in rows)

                grants = (
                    await connection.execute(
                        text(
                            "SELECT "
                            "has_table_privilege('agentdock_runtime', 'tenants', 'INSERT') AS tenant_insert, "
                            "has_table_privilege('agentdock_runtime', 'tenants', 'UPDATE') AS tenant_update, "
                            "has_table_privilege('agentdock_runtime', 'users', 'INSERT') AS user_insert, "
                            "has_table_privilege('agentdock_runtime', 'users', 'UPDATE') AS user_update, "
                            "has_table_privilege('agentdock_runtime', 'auth_identities', 'INSERT') AS identity_insert, "
                            "has_table_privilege('agentdock_runtime', 'user_sessions', 'INSERT') AS session_insert, "
                            "has_table_privilege('agentdock_runtime', 'session_tokens', 'INSERT') AS token_insert, "
                            "has_table_privilege('agentdock_runtime', 'tasks', 'INSERT') AS task_insert, "
                            "has_table_privilege('agentdock_runtime', 'tasks', 'UPDATE') AS runtime_task_update, "
                            "has_table_privilege('agentdock_runtime', 'tasks', 'DELETE') AS runtime_task_delete, "
                            "has_table_privilege('agentdock_runtime', 'task_events', 'INSERT') AS runtime_event_insert, "
                            "has_table_privilege('agentdock_runtime', 'idempotency_records', 'DELETE') AS runtime_idempotency_delete, "
                            "has_table_privilege('agentdock_runtime', 'audit_events', 'SELECT') AS runtime_audit_read, "
                            "has_table_privilege('agentdock_runtime', 'audit_events', 'INSERT') AS runtime_audit_insert, "
                            "has_table_privilege('agentdock_runtime', 'alembic_version', 'SELECT') AS migration_history_read, "
                            "has_table_privilege('agentdock_runtime', 'task_dispatch', 'INSERT') AS runtime_dispatch_insert, "
                            "has_table_privilege('agentdock_dispatcher', 'task_dispatch', 'INSERT') AS dispatcher_insert, "
                            "has_column_privilege('agentdock_dispatcher', 'task_dispatch', 'task_id', 'SELECT') AS dispatcher_task_id_select, "
                            "has_table_privilege('agentdock_dispatcher', 'task_dispatch', 'SELECT') AS dispatcher_full_select, "
                            "has_table_privilege('agentdock_worker', 'task_dispatch', 'SELECT') AS worker_dispatch_select, "
                            "has_table_privilege('agentdock_worker', 'task_dispatch', 'UPDATE') AS worker_dispatch_update, "
                            "has_database_privilege('agentdock_migrator', current_database(), 'CREATE') AS migrator_database_create, "
                            "has_schema_privilege('agentdock_runtime', 'agentdock_private', 'USAGE') AS runtime_private_schema_usage, "
                            "has_schema_privilege('anon', 'agentdock_private', 'USAGE') AS anon_private_schema_usage, "
                            "(SELECT pg_get_userbyid(p.proowner) FROM pg_proc p "
                            "JOIN pg_namespace n ON n.oid = p.pronamespace "
                            "WHERE n.nspname = 'agentdock_private' AND p.proname = 'enqueue_task_dispatch') AS trigger_owner, "
                            "(SELECT p.prosecdef FROM pg_proc p "
                            "JOIN pg_namespace n ON n.oid = p.pronamespace "
                            "WHERE n.nspname = 'agentdock_private' AND p.proname = 'enqueue_task_dispatch') AS trigger_security_definer, "
                            "(SELECT p.proconfig FROM pg_proc p "
                            "JOIN pg_namespace n ON n.oid = p.pronamespace "
                            "WHERE n.nspname = 'agentdock_private' AND p.proname = 'enqueue_task_dispatch') AS trigger_config, "
                            "has_function_privilege('agentdock_dispatcher', "
                            "(SELECT p.oid FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                            "WHERE n.nspname = 'agentdock_private' AND p.proname = 'enqueue_task_dispatch'), 'EXECUTE') AS dispatcher_trigger_execute, "
                            "has_function_privilege('agentdock_runtime', "
                            "(SELECT p.oid FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                            "WHERE n.nspname = 'agentdock_private' AND p.proname = 'enqueue_task_dispatch'), 'EXECUTE') AS runtime_trigger_execute, "
                            "has_function_privilege('anon', "
                            "(SELECT p.oid FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                            "WHERE n.nspname = 'agentdock_private' AND p.proname = 'enqueue_task_dispatch'), 'EXECUTE') AS anon_trigger_execute, "
                            "has_function_privilege('authenticated', "
                            "(SELECT p.oid FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                            "WHERE n.nspname = 'agentdock_private' AND p.proname = 'enqueue_task_dispatch'), 'EXECUTE') AS authenticated_trigger_execute, "
                            "has_schema_privilege('agentdock_runtime', 'public', 'CREATE') AS schema_create"
                        )
                    )
                ).one()
                assert grants.tenant_insert is True
                assert grants.tenant_update is False
                assert grants.user_insert is True
                assert grants.user_update is False
                assert grants.identity_insert is True
                assert grants.session_insert is True
                assert grants.token_insert is True
                assert grants.task_insert is True
                assert grants.runtime_task_update is False
                assert grants.runtime_task_delete is False
                assert grants.runtime_event_insert is True
                assert grants.runtime_idempotency_delete is True
                assert grants.runtime_audit_read is False
                assert grants.runtime_audit_insert is True
                assert grants.migration_history_read is False
                assert grants.runtime_dispatch_insert is False
                assert grants.dispatcher_insert is True
                assert grants.dispatcher_task_id_select is True
                assert grants.dispatcher_full_select is False
                assert grants.worker_dispatch_select is True
                assert grants.worker_dispatch_update is True
                assert grants.migrator_database_create is True
                assert grants.runtime_private_schema_usage is False
                assert grants.anon_private_schema_usage is False
                assert grants.trigger_owner == "agentdock_dispatcher"
                assert grants.trigger_security_definer is True
                assert "search_path=pg_catalog" in grants.trigger_config
                assert grants.dispatcher_trigger_execute is True
                assert grants.runtime_trigger_execute is False
                assert grants.anon_trigger_execute is False
                assert grants.authenticated_trigger_execute is False
                assert grants.schema_create is False
        finally:
            await admin_engine.dispose()

    asyncio.run(check_database())


def test_tenant_context_is_transaction_local_and_blocks_cross_tenant_writes() -> None:
    async def check_isolation() -> None:
        admin_engine = create_async_engine(ADMIN_DATABASE_URL, pool_pre_ping=True)
        runtime_engine = create_async_engine(RUNTIME_DATABASE_URL, pool_pre_ping=True)

        tenant_a, tenant_b = uuid4(), uuid4()
        user_a_id, user_b_id = uuid4(), uuid4()
        task_a, task_b = uuid4(), uuid4()
        suffix = uuid4().hex
        try:
            async with admin_engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO tenants (id, slug, name) VALUES "
                        "(:tenant_a, :slug_a, 'Tenant A'), "
                        "(:tenant_b, :slug_b, 'Tenant B')"
                    ),
                    {
                        "tenant_a": tenant_a,
                        "slug_a": f"test-a-{suffix}",
                        "tenant_b": tenant_b,
                        "slug_b": f"test-b-{suffix}",
                    },
                )
                await connection.execute(
                    text(
                        "INSERT INTO users (id, email, display_name) "
                        "VALUES (:user_a, :email_a, 'Tenant A user'), "
                        "(:user_b, :email_b, 'Tenant B user')"
                    ),
                    {
                        "user_a": user_a_id,
                        "email_a": f"rls-a-{suffix}@example.test",
                        "user_b": user_b_id,
                        "email_b": f"rls-b-{suffix}@example.test",
                    },
                )
                await connection.execute(
                    text(
                        "INSERT INTO tenant_memberships (id, tenant_id, user_id, role) "
                        "VALUES (:membership_a, :tenant_a, :user_a, 'owner'), "
                        "(:membership_b, :tenant_b, :user_b, 'owner')"
                    ),
                    {
                        "membership_a": uuid4(),
                        "membership_b": uuid4(),
                        "tenant_a": tenant_a,
                        "tenant_b": tenant_b,
                        "user_a": user_a_id,
                        "user_b": user_b_id,
                    },
                )
                await connection.execute(
                    text(
                        "INSERT INTO tasks "
                        "(id, tenant_id, created_by_user_id, title, prompt) "
                        "VALUES "
                        "(:task_a, :tenant_a, :user_a, 'Task A', 'test prompt'), "
                        "(:task_b, :tenant_b, :user_b, 'Task B', 'test prompt')"
                    ),
                    {
                        "task_a": task_a,
                        "task_b": task_b,
                        "tenant_a": tenant_a,
                        "tenant_b": tenant_b,
                        "user_a": user_a_id,
                        "user_b": user_b_id,
                    },
                )

                dispatch_rows = (
                    await connection.execute(
                        text(
                            "SELECT task_id, tenant_id FROM task_dispatch "
                            "WHERE task_id IN (:task_a, :task_b) ORDER BY task_id"
                        ),
                        {"task_a": task_a, "task_b": task_b},
                    )
                ).all()
                assert {(row.task_id, row.tenant_id) for row in dispatch_rows} == {
                    (task_a, tenant_a), (task_b, tenant_b)
                }

                # Tenant A's member cannot be recorded as the creator in Tenant B.
                with pytest.raises(DBAPIError):
                    async with connection.begin_nested():
                        await connection.execute(
                            text(
                                "INSERT INTO tasks "
                                "(id, tenant_id, created_by_user_id, title, prompt) "
                                "VALUES (:task_id, :tenant_b, :user_a, 'Invalid actor', 'blocked')"
                            ),
                            {
                                "task_id": uuid4(),
                                "tenant_b": tenant_b,
                                "user_a": user_a_id,
                            },
                        )

            # The unprivileged API role can create a tenant task; the trigger,
            # not the API role, writes the dispatch row through its narrow owner role.
            runtime_task = uuid4()
            async with runtime_engine.begin() as connection:
                await connection.execute(
                    text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
                    {"tenant_id": str(tenant_a)},
                )
                await connection.execute(
                    text(
                        "INSERT INTO tasks "
                        "(id, tenant_id, created_by_user_id, title, prompt) "
                        "VALUES (:task_id, :tenant_id, :user_id, 'Runtime trigger test', 'safe test')"
                    ),
                    {"task_id": runtime_task, "tenant_id": tenant_a, "user_id": user_a_id},
                )

            async with admin_engine.connect() as connection:
                dispatched = (
                    await connection.execute(
                        text(
                            "SELECT task_id, tenant_id FROM task_dispatch WHERE task_id = :task_id"
                        ),
                        {"task_id": runtime_task},
                    )
                ).one()
                assert dispatched.task_id == runtime_task
                assert dispatched.tenant_id == tenant_a

            async with runtime_engine.connect() as connection:
                async with connection.begin():
                    await connection.execute(
                        text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
                        {"tenant_id": str(tenant_a)},
                    )
                    visible_tasks = (
                        await connection.execute(
                            text("SELECT id FROM tasks ORDER BY title")
                        )
                    ).scalars().all()
                    visible_memberships = (
                        await connection.execute(
                            text("SELECT tenant_id FROM tenant_memberships")
                        )
                    ).scalars().all()
                    assert set(visible_tasks) == {task_a, runtime_task}
                    assert visible_memberships == [tenant_a]

                # SET LOCAL must not leak when the pooled connection is reused.
                async with connection.begin():
                    unscoped_count = (
                        await connection.execute(text("SELECT count(*) FROM tasks"))
                    ).scalar_one()
                    assert unscoped_count == 0

            with pytest.raises(DBAPIError):
                async with runtime_engine.begin() as connection:
                    await connection.execute(
                        text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
                        {"tenant_id": str(tenant_a)},
                    )
                    await connection.execute(
                        text(
                            "INSERT INTO tasks "
                            "(id, tenant_id, created_by_user_id, title, prompt) "
                            "VALUES (:task_id, :tenant_b, :user_a, 'Cross tenant', 'blocked')"
                        ),
                        {
                            "task_id": uuid4(),
                            "tenant_b": tenant_b,
                            "user_a": user_a_id,
                        },
                    )
        finally:
            await runtime_engine.dispose()
            await admin_engine.dispose()

    asyncio.run(check_isolation())

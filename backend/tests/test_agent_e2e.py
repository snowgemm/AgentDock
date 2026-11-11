"""Agent + worker + PostgreSQL end to end with a deterministic gateway.

The live-vendor test at the bottom only runs when OPENAI_API_KEY and
AGENTDOCK_OPENAI_MODEL are present; otherwise it is reported as skipped (blocked).
"""
from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from agent_fakes import FakeGateway, text_response, tool_response
from app.agent.gateway import GatewayError
from app.agent.handler import AgentHandler, budgets_from_settings
from app.agent.tools import default_tools
from app.agent.verifier import StructuralVerifier
from app.main import create_app
from app.worker.runner import Worker
from app.worker.store import WorkerStore
from test_tasks_api import ADMIN_DATABASE_URL, signed_in_client  # noqa: F401
from test_worker import Env, environment, run, settings, WORKER_URL

pytestmark = pytest.mark.skipif(
    not (ADMIN_DATABASE_URL and WORKER_URL),
    reason="PostgreSQL integration URLs are not configured; CI always configures them.",
)


def agent_handler(gateway: FakeGateway, **overrides) -> AgentHandler:
    return AgentHandler(gateway, default_tools(), budgets_from_settings(settings(**overrides)),
                        StructuralVerifier())


async def work_until(env: Env, handler: AgentHandler, task_ids, status: str = "SUCCEEDED", **overrides) -> None:
    worker = Worker(settings(**overrides), env.store, handler)
    runner = asyncio.create_task(worker.run())
    try:
        for _ in range(150):
            if all([await env.status(t) == status for t in task_ids]):
                break
            await asyncio.sleep(0.1)
    finally:
        worker.request_stop()
        await asyncio.wait_for(runner, timeout=10)


def test_agent_run_completes_with_a_tool_call_checkpoints_and_ordered_events() -> None:
    async def scenario(env: Env) -> None:
        task_id = await env.make_task()
        gateway = FakeGateway([
            tool_response("get_task_context", {"section": "task"}),
            text_response("Here is the answer."),
        ])
        await work_until(env, agent_handler(gateway), [task_id])

        assert await env.status(task_id) == "SUCCEEDED"
        events = await env.events(task_id)
        assert [s for s, _ in events] == list(range(1, len(events) + 1))  # contiguous sequences
        types = [t for _, t in events]
        assert types == ["TASK_CREATED", "TASK_STARTED", "AGENT_STARTED", "AGENT_MODEL_CALL",
                         "AGENT_TOOL_CALL", "AGENT_MODEL_CALL", "TASK_VERIFYING", "AGENT_RESULT",
                         "TASK_SUCCEEDED"]
        assert await env.scalar("SELECT count(*) FROM task_checkpoints WHERE task_id = :id", id=task_id) == 2
        # The tool saw the real tenant-scoped record, delivered as untrusted data.
        tool_result = gateway.requests[1].messages[-1].text
        assert "untrusted_data" in tool_result and "Prompt" in tool_result

    run(scenario)


def test_worker_retry_resumes_the_agent_from_its_database_checkpoint() -> None:
    async def scenario(env: Env) -> None:
        task_id = await env.make_task()
        gateway = FakeGateway([
            tool_response("get_task_context", {"section": "task"}),   # attempt 1, iteration 1
            GatewayError("provider_unavailable", retryable=True),      # attempt 1 fails
            text_response("Recovered."),                                # attempt 2 resumes: ONE call
        ])
        await work_until(env, agent_handler(gateway), [task_id])

        assert await env.status(task_id) == "SUCCEEDED"
        types = [t for _, t in await env.events(task_id)]
        assert types.count("AGENT_STARTED") == 1 and types.count("TASK_STARTED") == 2
        assert "TASK_RETRY_SCHEDULED" in types
        assert gateway.script == []  # every scripted response used exactly once
        assert len(gateway.requests) == 3
        resumed = [m.kind for m in gateway.requests[2].messages]
        assert resumed == ["user", "provider_items", "tool_result"]

    run(scenario)


def test_permanent_provider_errors_fail_the_task_with_a_code_and_no_secret_text() -> None:
    async def scenario(env: Env) -> None:
        task_id = await env.make_task()
        gateway = FakeGateway([GatewayError("provider_auth", retryable=False)])
        await work_until(env, agent_handler(gateway), [task_id], status="FAILED")
        failed = await env.scalar(
            "SELECT payload::text FROM task_events WHERE task_id = :id AND event_type = 'TASK_FAILED'",
            id=task_id)
        assert "provider_auth" in failed

    run(scenario)


def test_context_tool_reads_only_the_leased_tasks_own_tenant_scoped_record() -> None:
    async def scenario(env: Env) -> None:
        other = await env.new_tenant()
        mine = await env.make_task()
        theirs = await env.make_task(other)
        lease_a = await env.store.claim_next("w", 30)
        assert lease_a is not None
        lease_b = await env.store.claim_next("w", 30)
        assert lease_b is not None
        leases = {lease_a.task_id: lease_a, lease_b.task_id: lease_b}
        for task_id in (mine, theirs):
            assert await env.store.begin_execution(leases[task_id]) is not None
        await env.store.append_event(leases[mine], "AGENT_RESULT", {"answer": "private", "k": 1})

        own = await env.store.read_context(leases[mine], "task", 5)
        assert own["title"] == "Title" and own["status"] == "RUNNING"
        events = await env.store.read_context(leases[mine], "recent_events", 20)
        assert all("answer" not in e["payload"] for e in events["events"])  # large results are not echoed
        # The other tenant's lease can only ever see its own task: there is no id argument.
        other_view = await env.store.read_context(leases[theirs], "recent_events", 20)
        assert len(other_view["events"]) == 2 and all(e["sequence"] <= 2 for e in other_view["events"])

    run(scenario)


def test_result_is_visible_through_the_api_after_a_fresh_app_instance(signed_in_client) -> None:  # noqa: F811
    ctx = signed_in_client
    created = ctx["client"].post(
        "/api/v1/tasks", headers={**ctx["headers"], "Idempotency-Key": uuid4().hex},
        json={"title": "Question", "prompt": "What is 2 + 2?"},
    )
    assert created.status_code == 201
    task_id = created.json()["id"]
    assert created.json()["status"] == "QUEUED"

    async def work() -> None:
        async with environment() as env:
            # environment() parks leftovers, so re-open this task's dispatch row explicitly.
            await env.scalar("UPDATE task_dispatch SET state = 'PENDING', available_at = now() "
                             "WHERE task_id = :id RETURNING 1", id=task_id)
            gateway = FakeGateway([text_response("2 + 2 = 4")])
            await work_until(env, agent_handler(gateway), [task_id])

    asyncio.run(work())

    # "App restart": a brand-new application instance (no in-memory state) serves the result.
    fresh = create_app(ctx["settings"])
    fresh.state.oidc_jwks_client = ctx["client"].app.state.oidc_jwks_client
    with TestClient(fresh) as restarted:
        task = restarted.get(f"/api/v1/tasks/{task_id}", headers=ctx["headers"]).json()
        assert task["status"] == "SUCCEEDED"
        events = restarted.get(f"/api/v1/tasks/{task_id}/events", headers=ctx["headers"]).json()["items"]
        result = next(e for e in events if e["event_type"] == "AGENT_RESULT")
        assert result["payload"]["answer"] == "2 + 2 = 4" and result["payload"]["verified"] is True
        assert [e["sequence"] for e in events] == sorted(e["sequence"] for e in events)


LIVE_READY = bool(os.getenv("OPENAI_API_KEY") and os.getenv("AGENTDOCK_OPENAI_MODEL"))


@pytest.mark.skipif(not LIVE_READY, reason="BLOCKED: OPENAI_API_KEY and AGENTDOCK_OPENAI_MODEL are not set; no live vendor test was run.")
def test_live_vendor_gateway_answers_a_trivial_prompt() -> None:  # pragma: no cover - needs credentials
    from openai import AsyncOpenAI

    from app.agent.gateway import Message, ModelRequest
    from app.agent.openai_gateway import OpenAIGateway

    gateway = OpenAIGateway(AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"], max_retries=0),
                            os.environ["AGENTDOCK_OPENAI_MODEL"])
    result = asyncio.run(gateway.generate(ModelRequest(
        instructions="Reply with the single word: pong.",
        messages=(Message(kind="user", text="ping"),), max_output_tokens=64, timeout_seconds=30)))
    assert result.text.strip() and result.usage.total_tokens > 0 and result.response_id

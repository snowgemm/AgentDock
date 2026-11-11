"""Policy, approvals, typed tools and audit: pure tests plus PostgreSQL integration."""
from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, ConfigDict, Field

from agent_fakes import FakeGateway, text_response, tool_response
from app.agent.handler import AgentHandler, budgets_from_settings
from app.agent.tools import ActionDescription, RiskClass, ToolDefinition, ToolInvocation, ToolRegistry
from app.agent.verifier import StructuralVerifier
from app.policy.action import POLICY_VERSION, action_digest
from app.policy.approvals import ApprovalRejected
from app.policy.executor import PolicyEnforcingExecutor, ToolDenied
from app.policy.pdp import Effect, PolicyEngine, PolicyFacts, PolicyRequest
from app.policy.redact import REDACTED, redact
from app.worker.handlers import LeaseLost, UncertainSideEffect
from app.worker.runner import _Context
from test_tasks_api import ADMIN_DATABASE_URL, _cleanup_identity, _external_access_token, signed_in_client  # noqa: F401
from test_worker import Env, WORKER_URL, environment, run, settings


# ------------------------------------------------------------------ test-only tools

class NoteArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str = Field(max_length=64)
    body: str = Field(max_length=200)
    api_token: str | None = None


class Effects:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []


def note_tool(effects: Effects, name: str = "test_send_note", risk: RiskClass = RiskClass.CONSEQUENTIAL,
              enabled: bool = True) -> ToolDefinition:
    async def execute(invocation: ToolInvocation) -> Any:
        args = invocation.arguments
        assert isinstance(args, NoteArgs)
        effects.sent.append(args.model_dump())
        return {"sent_to": args.target, "server_credential": "sk-live-ABCDEFGH12345678"}

    return ToolDefinition(
        name=name, description="TEST ONLY: pretend to send a note.", args_model=NoteArgs, execute=execute,
        risk=risk, resource_scopes=("sandbox/*",), enabled=enabled,
        describe=lambda a: ActionDescription(
            a.target, f"Send a note to {a.target}",  # type: ignore[attr-defined]
            {"target": a.target, "body": a.body, "api_token": a.api_token}),  # type: ignore[attr-defined]
    )


def args(**overrides: Any) -> NoteArgs:
    base: dict[str, Any] = {"target": "sandbox/alice", "body": "hello"}
    base.update(overrides)
    return NoteArgs(**base)


# ------------------------------------------------------------------------ pure tests

FACTS = PolicyFacts(True, True, "RUNNING", True)


def req(**overrides: Any) -> PolicyRequest:
    base: dict[str, Any] = dict(facts=FACTS, tool_name="t", tool_enabled=True, risk=RiskClass.READ_ONLY,
                                resource_scopes=("sandbox/*",), target="sandbox/x")
    base.update(overrides)
    return PolicyRequest(**base)


def test_policy_decision_matrix() -> None:
    pdp = PolicyEngine()
    assert pdp.decide(req()).effect is Effect.ALLOW
    assert pdp.decide(req(risk=RiskClass.REVERSIBLE)).effect is Effect.ALLOW
    assert pdp.decide(req(risk=RiskClass.CONSEQUENTIAL)).effect is Effect.REQUIRE_APPROVAL
    approved = pdp.decide(req(risk=RiskClass.CONSEQUENTIAL, approval_presented=True))
    assert (approved.effect, approved.reason) == (Effect.ALLOW, "approved")

    denials = {
        "tool_disabled": req(tool_enabled=False),
        "task_not_found": req(facts=PolicyFacts(True, True, None, False)),
        "membership_revoked": req(facts=PolicyFacts(False, True, "RUNNING", True)),
        "user_inactive": req(facts=PolicyFacts(True, False, "RUNNING", True)),
        "task_not_running": req(facts=PolicyFacts(True, True, "CANCELLED", True)),
        "resource_out_of_scope": req(target="prod/db"),
    }
    for reason, request in denials.items():
        decision = pdp.decide(request)
        assert (decision.effect, decision.reason) == (Effect.DENY, reason)
    # An approval flag can never override a hard denial.
    overridden = pdp.decide(req(risk=RiskClass.CONSEQUENTIAL, approval_presented=True, target="prod/db"))
    assert overridden.effect is Effect.DENY
    assert PolicyEngine(denied_tools=frozenset({"t"})).decide(req()).effect is Effect.DENY
    assert pdp.decide(req()).policy_version == POLICY_VERSION


def test_digest_covers_every_bound_field_and_is_order_independent() -> None:
    tenant, task = uuid4(), uuid4()
    base = dict(tenant_id=tenant, task_id=task, tool="t", args={"a": 1, "b": 2}, target="sandbox/x",
                risk="consequential", policy_version="v1")
    digest = action_digest(**base)
    assert digest == action_digest(**{**base, "args": {"b": 2, "a": 1}})
    changed = [
        {"tenant_id": uuid4()}, {"task_id": uuid4()}, {"tool": "u"}, {"args": {"a": 1, "b": 3}},
        {"target": "sandbox/y"}, {"risk": "reversible"}, {"policy_version": "v2"},
    ]
    digests = {action_digest(**{**base, **change}) for change in changed}
    assert digest not in digests and len(digests) == len(changed)


def test_redaction_masks_sensitive_keys_and_secret_looking_values() -> None:
    cleaned = redact({"api_token": "abc", "Authorization": "Bearer abcdefghijkl", "note": "key sk-live-ABCDEFGH123",
                      "nested": {"password": "x", "ok": "fine"}, "list": ["ghp_abcdefghijklmnopqrst", 3]})
    assert cleaned["api_token"] == REDACTED and cleaned["Authorization"] == REDACTED
    assert "sk-live" not in cleaned["note"] and REDACTED in cleaned["note"]
    assert cleaned["nested"] == {"password": REDACTED, "ok": "fine"}
    assert cleaned["list"] == [REDACTED, 3]


# ----------------------------------------------------------------- database tests

pytestmark = pytest.mark.skipif(
    not (ADMIN_DATABASE_URL and WORKER_URL),
    reason="PostgreSQL integration URLs are not configured; CI always configures them.",
)


async def running(env: Env, tenant=None) -> tuple[_Context, Any]:
    task_id = await env.make_task(tenant)
    lease = await env.store.claim_next("w", 60)
    assert lease is not None and lease.task_id == task_id
    execution = await env.store.begin_execution(lease)
    assert execution is not None
    return _Context(env.store, lease, execution), lease


def executor(effects: Effects, *, ttl: float = 30.0, tool: ToolDefinition | None = None,
             **policy: Any) -> tuple[PolicyEnforcingExecutor, ToolDefinition]:
    definition = tool or note_tool(effects)
    return (PolicyEnforcingExecutor(ToolRegistry([definition]), PolicyEngine(**policy),
                                    approval_ttl_seconds=ttl, poll_seconds=0.05), definition)


async def pending_id(env: Env, task_id: UUID, timeout: float = 5.0) -> UUID:
    for _ in range(int(timeout / 0.05)):
        found = await env.scalar("SELECT id FROM approvals WHERE task_id = :t AND status = 'PENDING' "
                                 "ORDER BY created_at DESC LIMIT 1", t=task_id)
        if found:
            return found
        await asyncio.sleep(0.05)
    raise AssertionError("no pending approval appeared")


async def set_approval(env: Env, approval_id: UUID, status: str) -> None:
    await env.scalar("UPDATE approvals SET status = :s, decided_at = now() WHERE id = :id RETURNING 1",
                     s=status, id=approval_id)


async def audit_rows(env: Env, task_id: UUID) -> list[tuple[str, str]]:
    async with env.admin.begin() as c:
        from sqlalchemy import text
        rows = await c.execute(text("SELECT action, outcome FROM audit_events WHERE task_id = :t "
                                    "ORDER BY created_at, id"), {"t": task_id})
        return [(r.action, r.outcome) for r in rows]


def test_policy_denials_block_execution_and_are_audited() -> None:
    async def scenario(env: Env) -> None:
        effects = Effects()
        context, _ = await running(env)
        task_id = context.task_id

        disabled, tool = executor(effects, tool=note_tool(effects, enabled=False))
        with pytest.raises(ToolDenied) as caught:
            await disabled.execute(context, tool, args())
        assert caught.value.code == "tool_disabled"

        enforcing, tool = executor(effects)
        with pytest.raises(ToolDenied) as caught:
            await enforcing.execute(context, tool, args(target="prod/customers"))
        assert caught.value.code == "resource_out_of_scope"

        denylisted, tool = executor(effects, denied_tools=frozenset({"test_send_note"}))
        with pytest.raises(ToolDenied):
            await denylisted.execute(context, tool, args())

        await env.scalar("UPDATE tasks SET status = 'PAUSED' WHERE id = :id RETURNING 1", id=task_id)
        with pytest.raises(ToolDenied) as caught:
            await enforcing.execute(context, tool, args())
        assert caught.value.code == "task_not_running"
        await env.scalar("UPDATE tasks SET status = 'RUNNING' WHERE id = :id RETURNING 1", id=task_id)

        await env.scalar("UPDATE users SET is_active = false WHERE id = :u RETURNING 1", u=env.tenant.user_id)
        with pytest.raises(ToolDenied) as caught:
            await enforcing.execute(context, tool, args())
        assert caught.value.code == "user_inactive"

        assert effects.sent == []
        outcomes = [o for a, o in await audit_rows(env, task_id) if a == "tool.decision"]
        assert outcomes == ["DENY"] * 5

    run(scenario)


def test_consequential_action_waits_for_the_exact_approval_then_runs_exactly_once() -> None:
    async def scenario(env: Env) -> None:
        effects = Effects()
        context, lease = await running(env)
        enforcing, tool = executor(effects)
        call = asyncio.create_task(enforcing.execute(context, tool, args(api_token="sk-live-SECRETSECRET99")))

        approval_id = await pending_id(env, context.task_id)
        assert await env.status(context.task_id) == "WAITING_APPROVAL"
        assert effects.sent == []  # nothing runs before approval

        # What the approver is shown: exact action, target, redacted key args, risk, effect, expiry.
        stored = await env.scalar("SELECT action::text FROM approvals WHERE id = :id", id=approval_id)
        assert "sandbox/alice" in stored and "consequential" in stored and "Send a note to sandbox/alice" in stored
        assert "SECRETSECRET" not in stored and REDACTED in stored

        await set_approval(env, approval_id, "APPROVED")
        output = await asyncio.wait_for(call, timeout=5)

        assert len(effects.sent) == 1
        assert "sk-live-ABCDEFGH" not in output and "untrusted_data" in output  # output redacted + wrapped
        assert await env.status(context.task_id) == "RUNNING"
        assert await env.scalar("SELECT status FROM approvals WHERE id = :id", id=approval_id) == "CONSUMED"
        events = [t for _, t in await env.events(context.task_id)]
        assert events[-3:] == ["APPROVAL_REQUESTED", "TASK_WAITING_APPROVAL", "TASK_APPROVAL_RESOLVED"]
        actions = [a for a, _ in await audit_rows(env, context.task_id)]
        assert actions == ["tool.decision", "approval.requested", "tool.decision", "tool.executed"]

        # Re-running the identical action in the same task is deduplicated by its receipt.
        again = asyncio.create_task(enforcing.execute(context, tool, args(api_token="sk-live-SECRETSECRET99")))
        await set_approval(env, await pending_id(env, context.task_id), "APPROVED")
        await asyncio.wait_for(again, timeout=5)
        assert len(effects.sent) == 1

    run(scenario)


def test_a_changed_action_cannot_use_an_approval_for_a_different_digest() -> None:
    async def scenario(env: Env) -> None:
        effects = Effects()
        context, lease = await running(env)
        enforcing, tool = executor(effects)
        approved_action = enforcing.build_action(context, tool, args(body="pay 10"))
        altered_action = enforcing.build_action(context, tool, args(body="pay 10000"))
        assert approved_action.digest != altered_action.digest

        ref = await env.store.request_approval(lease, approved_action, 30)
        await set_approval(env, ref.id, "APPROVED")

        async def effect() -> dict[str, Any]:
            effects.sent.append({"unexpected": True})
            return {}

        with pytest.raises(ApprovalRejected) as caught:
            await env.store.execute_approved(lease, "step-altered", altered_action.digest, effect)
        assert caught.value.code == "approval_missing"
        assert effects.sent == []
        # The approval for the original action is untouched and still usable for that action only.
        assert await env.scalar("SELECT status FROM approvals WHERE id = :id", id=ref.id) == "APPROVED"

        # And through the executor: approving "pay 10" does not unlock "pay 10000".
        enforcing_short, tool = executor(effects, ttl=0.3)
        with pytest.raises(ToolDenied) as denied:
            await enforcing_short.execute(context, tool, args(body="pay 10000"))
        assert denied.value.code == "approval_expired" and effects.sent == []

    run(scenario)


def test_expired_denied_and_revoked_approvals_do_not_authorize_execution() -> None:
    async def scenario(env: Env) -> None:
        effects = Effects()
        context, lease = await running(env)
        enforcing, tool = executor(effects)
        action = enforcing.build_action(context, tool, args())

        async def effect() -> dict[str, Any]:
            effects.sent.append({"ran": True})
            return {}

        ref = await env.store.request_approval(lease, action, 30)
        await set_approval(env, ref.id, "APPROVED")
        await env.scalar("UPDATE approvals SET expires_at = now() - interval '1 second' WHERE id = :id RETURNING 1", id=ref.id)
        with pytest.raises(ApprovalRejected) as caught:
            await env.store.execute_approved(lease, "s1", action.digest, effect)
        assert caught.value.code == "approval_expired"

        ref = await env.store.request_approval(lease, action, 30)  # new approval for the same digest
        await set_approval(env, ref.id, "DENIED")
        with pytest.raises(ApprovalRejected) as caught:
            await env.store.execute_approved(lease, "s2", action.digest, effect)
        assert caught.value.code == "approval_denied"

        ref = await env.store.request_approval(lease, action, 30)
        await set_approval(env, ref.id, "APPROVED")
        await set_approval(env, ref.id, "REVOKED")
        with pytest.raises(ApprovalRejected) as caught:
            await env.store.execute_approved(lease, "s3", action.digest, effect)
        assert caught.value.code == "approval_revoked"
        assert effects.sent == []

    run(scenario)


def test_an_approval_is_single_use_and_a_replay_is_blocked() -> None:
    async def scenario(env: Env) -> None:
        effects = Effects()
        context, lease = await running(env)
        enforcing, tool = executor(effects)
        action = enforcing.build_action(context, tool, args())
        ref = await env.store.request_approval(lease, action, 30)
        await set_approval(env, ref.id, "APPROVED")

        async def effect() -> dict[str, Any]:
            effects.sent.append({"ran": True})
            return {"id": len(effects.sent)}

        assert await env.store.execute_approved(lease, "first", action.digest, effect) == {"id": 1}
        with pytest.raises(ApprovalRejected) as caught:
            await env.store.execute_approved(lease, "second", action.digest, effect)
        assert caught.value.code == "approval_replayed"
        # Same step again (e.g. a retry after a crash): stored receipt, no new effect, no new approval.
        assert await env.store.execute_approved(lease, "first", action.digest, effect) == {"id": 1}
        assert len(effects.sent) == 1

    run(scenario)


def test_concurrent_consumers_of_one_approval_produce_one_execution() -> None:
    async def scenario(env: Env) -> None:
        effects = Effects()
        context, lease = await running(env)
        enforcing, tool = executor(effects)
        action = enforcing.build_action(context, tool, args())
        ref = await env.store.request_approval(lease, action, 30)
        await set_approval(env, ref.id, "APPROVED")

        async def effect() -> dict[str, Any]:
            effects.sent.append({})
            return {}

        results = await asyncio.gather(
            *(env.store.execute_approved(lease, f"s{i}", action.digest, effect) for i in range(5)),
            return_exceptions=True,
        )
        assert len(effects.sent) == 1
        assert sum(isinstance(r, ApprovalRejected) for r in results) == 4

    run(scenario)


def test_an_interrupted_consequential_step_is_never_blindly_replayed() -> None:
    async def scenario(env: Env) -> None:
        effects = Effects()
        context, lease = await running(env)
        enforcing, tool = executor(effects)
        action = enforcing.build_action(context, tool, args())
        ref = await env.store.request_approval(lease, action, 30)
        await set_approval(env, ref.id, "APPROVED")

        async def crashing() -> dict[str, Any]:
            raise RuntimeError("worker died after the external call may have been sent")

        with pytest.raises(RuntimeError):
            await env.store.execute_approved(lease, "pay", action.digest, crashing)
        ref = await env.store.request_approval(lease, action, 30)  # even with a fresh approval...
        await set_approval(env, ref.id, "APPROVED")
        with pytest.raises(UncertainSideEffect):
            await env.store.execute_approved(lease, "pay", action.digest, crashing)
        assert await env.scalar("SELECT status FROM approvals WHERE id = :id", id=ref.id) == "APPROVED"  # not spent

    run(scenario)


def test_approvals_are_tenant_isolated() -> None:
    async def scenario(env: Env) -> None:
        other = await env.new_tenant()
        effects = Effects()
        context_a, lease_a = await running(env)
        enforcing, tool = executor(effects)
        action_a = enforcing.build_action(context_a, tool, args())
        ref = await env.store.request_approval(lease_a, action_a, 30)
        await set_approval(env, ref.id, "APPROVED")

        context_b, lease_b = await running(env, other)

        async def effect() -> dict[str, Any]:
            effects.sent.append({})
            return {}

        with pytest.raises(ApprovalRejected) as caught:  # B presents A's digest
            await env.store.execute_approved(lease_b, "steal", action_a.digest, effect)
        assert caught.value.code == "approval_missing"
        with pytest.raises(LeaseLost):  # B cannot even read A's approval
            await env.store.get_approval(lease_b, ref.id)
        assert effects.sent == [] and await env.scalar("SELECT status FROM approvals WHERE id = :id", id=ref.id) == "APPROVED"

    run(scenario)


def test_agent_end_to_end_with_approval_then_denial() -> None:
    async def scenario(env: Env) -> None:
        for decision, expected_sent in (("APPROVED", 1), ("DENIED", 0)):
            effects = Effects()
            task_id = await env.make_task()
            registry = ToolRegistry([note_tool(effects)])
            gateway = FakeGateway([
                tool_response("test_send_note", {"target": "sandbox/bob", "body": "hi"}),
                text_response("Handled."),
            ])
            handler = AgentHandler(
                gateway, registry, budgets_from_settings(settings()), StructuralVerifier(),
                PolicyEnforcingExecutor(registry, PolicyEngine(), approval_ttl_seconds=30, poll_seconds=0.05),
            )
            from app.worker.runner import Worker

            worker = Worker(settings(), env.store, handler)
            runner_task = asyncio.create_task(worker.run())
            try:
                await set_approval(env, await pending_id(env, task_id), decision)
                for _ in range(100):
                    if await env.status(task_id) == "SUCCEEDED":
                        break
                    await asyncio.sleep(0.1)
            finally:
                worker.request_stop()
                await asyncio.wait_for(runner_task, timeout=10)

            assert await env.status(task_id) == "SUCCEEDED"
            assert len(effects.sent) == expected_sent
            types = [t for _, t in await env.events(task_id)]
            assert "TASK_WAITING_APPROVAL" in types and "APPROVAL_REQUESTED" in types
            if decision == "DENIED":
                assert "AGENT_TOOL_DENIED" in types
                assert "approval_denied" in gateway.requests[1].messages[-1].text

    run(scenario)


def test_audit_and_events_never_contain_raw_secrets() -> None:
    async def scenario(env: Env) -> None:
        effects = Effects()
        context, lease = await running(env)
        enforcing, tool = executor(effects)
        call = asyncio.create_task(enforcing.execute(context, tool, args(api_token="sk-live-SECRETSECRET99",
                                                                          body="Bearer abcdefghijklmnop")))
        await set_approval(env, await pending_id(env, context.task_id), "APPROVED")
        await asyncio.wait_for(call, timeout=5)
        from sqlalchemy import text
        async with env.admin.begin() as c:
            dump = " ".join(str(v) for row in (
                await c.execute(text("SELECT details::text FROM audit_events"))).all() for v in row)
            dump += " ".join(str(v) for row in (
                await c.execute(text("SELECT action::text FROM approvals"))).all() for v in row)
            dump += " ".join(str(v) for row in (
                await c.execute(text("SELECT payload::text FROM task_events"))).all() for v in row)
        assert "SECRETSECRET" not in dump and "abcdefghijklmnop" not in dump
        assert REDACTED in dump

    run(scenario)


def test_audit_events_are_append_only_for_the_application_roles() -> None:
    async def scenario(env: Env) -> None:
        from sqlalchemy import text
        from sqlalchemy.exc import DBAPIError

        async with env.worker.begin() as c:
            with pytest.raises(DBAPIError):
                await c.execute(text("UPDATE audit_events SET outcome = 'x'"))
        async with env.worker.begin() as c:
            with pytest.raises(DBAPIError):
                await c.execute(text("DELETE FROM audit_events"))

    run(scenario)


# ----------------------------------------------------------------------- API tests

def _insert_approval(ctx, task_id: str, *, digest: str | None = None, status: str = "PENDING",
                     ttl_seconds: int = 600, target: str = "sandbox/alice") -> tuple[str, str]:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    approval_id = str(uuid4())
    digest = digest or uuid4().hex + uuid4().hex

    async def go() -> None:
        engine = create_async_engine(ADMIN_DATABASE_URL)
        try:
            async with engine.begin() as c:
                await c.execute(text(
                    "INSERT INTO approvals (id, tenant_id, task_id, requested_for_user_id, tool_name, "
                    "action_digest, action, policy_version, status, expires_at) VALUES "
                    "(:id, :t, :task, :u, 'test_send_note', :d, CAST(:a AS jsonb), :v, :s, "
                    "now() + make_interval(secs => :ttl))"),
                    {"id": approval_id, "t": ctx["tenant_id"], "task": task_id, "u": ctx["user_id"], "d": digest,
                     "a": '{"tool":"test_send_note","target":"%s","risk":"consequential",'
                          '"summary":"Send a note","key_args":{"body":"hello"}}' % target,
                     "v": POLICY_VERSION, "s": status, "ttl": ttl_seconds})
        finally:
            await engine.dispose()

    asyncio.run(go())
    return approval_id, digest


def _task(ctx) -> str:
    created = ctx["client"].post("/api/v1/tasks", headers={**ctx["headers"], "Idempotency-Key": uuid4().hex},
                                 json={"title": "T", "prompt": "P"})
    assert created.status_code == 201
    return created.json()["id"]


def test_api_lists_the_exact_action_and_decides_only_with_the_matching_digest(signed_in_client) -> None:  # noqa: F811
    ctx = signed_in_client
    client, headers = ctx["client"], ctx["headers"]
    task_id = _task(ctx)
    approval_id, digest = _insert_approval(ctx, task_id)

    listed = client.get(f"/api/v1/tasks/{task_id}/approvals", headers=headers).json()
    assert len(listed) == 1
    shown = listed[0]
    assert (shown["tool"], shown["target"], shown["risk"], shown["status"]) == (
        "test_send_note", "sandbox/alice", "consequential", "PENDING")
    assert shown["summary"] == "Send a note" and shown["key_args"] == {"body": "hello"} and shown["digest"] == digest

    url = f"/api/v1/approvals/{approval_id}/decision"
    wrong = client.post(url, headers=headers, json={"decision": "approve", "digest": "0" * 64})
    assert wrong.status_code == 409 and wrong.json()["detail"] == "digest_mismatch"
    assert client.post(url, headers=headers, json={"decision": "approve", "digest": digest, "x": 1}).status_code == 422
    assert client.post(url, headers=headers, json={"decision": "maybe", "digest": digest}).status_code == 422

    ok = client.post(url, headers=headers, json={"decision": "approve", "digest": digest})
    assert ok.status_code == 200 and ok.json()["status"] == "APPROVED"
    again = client.post(url, headers=headers, json={"decision": "deny", "digest": digest})
    assert again.status_code == 409 and again.json()["detail"] == "not_pending"
    assert client.post(f"/api/v1/approvals/{approval_id}/revoke", headers=headers).json()["status"] == "REVOKED"
    assert client.post(f"/api/v1/approvals/{approval_id}/revoke", headers=headers).status_code == 409


def test_api_refuses_expired_approvals_and_other_workspaces(signed_in_client) -> None:  # noqa: F811
    ctx = signed_in_client
    client, headers = ctx["client"], ctx["headers"]
    task_id = _task(ctx)
    expired_id, expired_digest = _insert_approval(ctx, task_id, ttl_seconds=-5)
    response = client.post(f"/api/v1/approvals/{expired_id}/decision", headers=headers,
                           json={"decision": "approve", "digest": expired_digest})
    assert response.status_code == 409 and response.json()["detail"] == "expired"
    assert client.get(f"/api/v1/tasks/{task_id}/approvals", headers=headers).json()[0]["status"] == "EXPIRED"

    live_id, live_digest = _insert_approval(ctx, task_id)
    subject = f"approvals-other-{uuid4().hex}"
    try:
        other = client.post("/api/v1/auth/session", headers={
            "Authorization": f"Bearer {_external_access_token(ctx['private_key'], subject)}"})
        other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
        assert client.get(f"/api/v1/tasks/{task_id}/approvals", headers=other_headers).json() == []
        for path, body in ((f"/api/v1/approvals/{live_id}/decision", {"decision": "approve", "digest": live_digest}),
                           (f"/api/v1/approvals/{live_id}/revoke", None)):
            assert client.post(path, headers=other_headers, json=body).status_code == 404
        assert client.get(f"/api/v1/tasks/{task_id}/approvals", headers=headers).json()[0]["status"] == "PENDING"
        assert client.get(f"/api/v1/tasks/{task_id}/approvals").status_code == 401
    finally:
        asyncio.run(_cleanup_identity(subject))

"""Policy Enforcement Point: the only path by which an agent tool call executes.

Immediately before every execution it re-reads identity/task facts from the database,
asks the PDP, writes an audit event, and for consequential actions obtains a
single-use approval bound to the exact action digest. A decision made earlier (or by
the model) is never trusted.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel

from app.agent.tools import RiskClass, ToolDefinition, ToolInvocation, ToolRegistry, wrap_tool_output
from app.policy.action import ActionRecord, action_digest
from app.policy.approvals import ApprovalRejected
from app.policy.pdp import Decision, Effect, PolicyEngine, PolicyRequest
from app.policy.redact import redact
from app.worker.handlers import PermanentError, TaskContext


class ToolDenied(Exception):
    """The call was refused; ``code`` is safe to show the model and store."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class PolicyEnforcingExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        policy: PolicyEngine,
        *,
        approval_ttl_seconds: float = 900.0,
        poll_seconds: float = 1.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._registry = registry
        self._policy = policy
        self._ttl = approval_ttl_seconds
        self._poll = poll_seconds
        self._sleep = sleep

    def build_action(self, context: TaskContext, tool: ToolDefinition, arguments: BaseModel) -> ActionRecord:
        description = tool.action_description(arguments)
        args = arguments.model_dump(mode="json")
        digest = action_digest(
            tenant_id=context.tenant_id, task_id=context.task_id, tool=tool.name, args=args,
            target=description.target, risk=tool.risk.value, policy_version=self._policy.version,
        )
        return ActionRecord(
            tool=tool.name, args=args, target=description.target, risk=tool.risk.value,
            summary=description.summary, key_args=redact(description.key_args),
            policy_version=self._policy.version, digest=digest,
        )

    async def _decide(
        self, context: TaskContext, tool: ToolDefinition, action: ActionRecord, *, approved: bool
    ) -> Decision:
        facts = await context.policy_facts()
        decision = self._policy.decide(
            PolicyRequest(
                facts=facts, tool_name=tool.name, tool_enabled=tool.enabled, risk=tool.risk,
                resource_scopes=tool.resource_scopes, target=action.target, approval_presented=approved,
            )
        )
        await context.audit(
            "tool.decision", action.target, decision.effect.value,
            {"tool": tool.name, "reason": decision.reason, "risk": action.risk,
             "digest": action.digest, "approved": approved},
            decision.policy_version,
        )
        return decision

    async def execute(self, context: TaskContext, tool: ToolDefinition, arguments: BaseModel) -> str:
        action = self.build_action(context, tool, arguments)
        decision = await self._decide(context, tool, action, approved=False)
        if decision.effect is Effect.DENY:
            raise ToolDenied(decision.reason)

        approved = False
        if decision.effect is Effect.REQUIRE_APPROVAL:
            await self._obtain_approval(context, tool, action)
            # Re-check identity, task state and policy right before executing.
            recheck = await self._decide(context, tool, action, approved=True)
            if recheck.effect is not Effect.ALLOW:
                raise ToolDenied(recheck.reason)
            approved = True

        try:
            data = await self._run(context, tool, arguments, action, approved)
        except ApprovalRejected as rejection:
            await context.audit("tool.executed", action.target, "REJECTED",
                                {"tool": tool.name, "reason": rejection.code, "digest": action.digest},
                                action.policy_version)
            raise ToolDenied(rejection.code) from None
        await context.audit("tool.executed", action.target, "OK",
                            {"tool": tool.name, "digest": action.digest}, action.policy_version)
        return wrap_tool_output(tool.name, data, tool.max_output_chars)

    async def _obtain_approval(self, context: TaskContext, tool: ToolDefinition, action: ActionRecord) -> None:
        approval = await context.request_approval(action, self._ttl)
        await context.emit(
            "APPROVAL_REQUESTED",
            {"approval_id": str(approval.id), "digest": action.digest, **action.display_json(),
             "expires_at": approval.expires_at.isoformat()},
        )
        await context.transition("WAITING_APPROVAL", "TASK_WAITING_APPROVAL",
                                 {"approval_id": str(approval.id)})
        while True:
            await context.checkpoint()
            approval = await context.get_approval(approval.id)
            if approval.status != "PENDING":
                break
            await self._sleep(self._poll)
        await context.transition("RUNNING", "TASK_APPROVAL_RESOLVED",
                                 {"approval_id": str(approval.id), "status": approval.status})
        if approval.status != "APPROVED":
            reason = {"DENIED": "approval_denied", "EXPIRED": "approval_expired",
                      "REVOKED": "approval_revoked"}.get(approval.status, "approval_unavailable")
            await context.audit("approval.resolved", action.target, approval.status,
                                {"approval_id": str(approval.id), "digest": action.digest},
                                action.policy_version)
            raise ToolDenied(reason)

    async def _run(
        self, context: TaskContext, tool: ToolDefinition, arguments: BaseModel,
        action: ActionRecord, approved: bool,
    ) -> Any:
        invocation = ToolInvocation(context, arguments)

        async def effect() -> dict[str, Any]:
            data = await asyncio.wait_for(tool.execute(invocation), timeout=tool.timeout_seconds)
            return {"output": redact(data)}

        if tool.risk is RiskClass.READ_ONLY:
            return await asyncio.wait_for(tool.execute(invocation), timeout=tool.timeout_seconds)
        step_key = f"tool:{action.digest}"
        if tool.risk is RiskClass.CONSEQUENTIAL:
            if not approved:
                raise PermanentError("approval_required")  # defence in depth: PDP already enforced
            result = await context.execute_approved(step_key, action.digest, effect)
        else:
            result = await context.run_step(step_key, effect, idempotent=tool.idempotent)
        return result.get("output")

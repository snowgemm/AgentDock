"""Policy Decision Point: a pure function of server-held facts.

The model cannot grant or override anything: its only influence is the *validated
arguments* it proposed, which feed the target resource. Identity, task state and tool
configuration come from the database/registry immediately before execution.
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from enum import Enum

from app.agent.tools import RiskClass
from app.policy.action import POLICY_VERSION


class Effect(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    DENY = "DENY"


@dataclass(frozen=True, slots=True)
class PolicyFacts:
    membership_active: bool
    user_active: bool
    task_status: str | None
    tenant_matches: bool


@dataclass(frozen=True, slots=True)
class PolicyRequest:
    facts: PolicyFacts
    tool_name: str
    tool_enabled: bool
    risk: RiskClass
    resource_scopes: tuple[str, ...]
    target: str
    approval_presented: bool = False


@dataclass(frozen=True, slots=True)
class Decision:
    effect: Effect
    reason: str
    policy_version: str


class PolicyEngine:
    def __init__(self, *, denied_tools: frozenset[str] = frozenset(), version: str = POLICY_VERSION) -> None:
        self._denied = denied_tools
        self.version = version

    def decide(self, request: PolicyRequest) -> Decision:
        def decision(effect: Effect, reason: str) -> Decision:
            return Decision(effect, reason, self.version)

        facts = request.facts
        if not request.tool_enabled or request.tool_name in self._denied:
            return decision(Effect.DENY, "tool_disabled")
        if not facts.tenant_matches or facts.task_status is None:
            return decision(Effect.DENY, "task_not_found")
        if not facts.membership_active:
            return decision(Effect.DENY, "membership_revoked")
        if not facts.user_active:
            return decision(Effect.DENY, "user_inactive")
        if facts.task_status not in ("RUNNING", "WAITING_APPROVAL"):
            return decision(Effect.DENY, "task_not_running")
        if not any(fnmatch.fnmatchcase(request.target, scope) for scope in request.resource_scopes):
            return decision(Effect.DENY, "resource_out_of_scope")
        if request.risk in (RiskClass.READ_ONLY, RiskClass.REVERSIBLE):
            return decision(Effect.ALLOW, "risk_allowed")
        if request.approval_presented:
            return decision(Effect.ALLOW, "approved")
        return decision(Effect.REQUIRE_APPROVAL, "consequential_requires_approval")

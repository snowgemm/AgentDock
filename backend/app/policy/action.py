"""Canonical action description and its digest.

An approval is bound to the digest of the exact action about to run. The digest covers
tenant, task, tool, canonical validated arguments, target resource, risk class and
policy version, so changing any of them (including a policy change) yields a different
digest and the old approval simply does not match.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

POLICY_VERSION = "2026-11-13.1"
DIGEST_SCHEMA = 1


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def action_digest(
    *, tenant_id: UUID, task_id: UUID, tool: str, args: dict[str, Any], target: str,
    risk: str, policy_version: str,
) -> str:
    document = {
        "v": DIGEST_SCHEMA, "tenant_id": str(tenant_id), "task_id": str(task_id), "tool": tool,
        "args": args, "target": target, "risk": risk, "policy_version": policy_version,
    }
    return hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ActionRecord:
    """What the approver sees and what the digest covers (display fields are redacted)."""

    tool: str
    args: dict[str, Any]       # canonical validated arguments (covered by the digest)
    target: str
    risk: str
    summary: str               # expected effect, shown to the approver
    key_args: dict[str, Any]   # redacted subset for display
    policy_version: str
    digest: str

    def display_json(self) -> dict[str, Any]:
        return {"tool": self.tool, "target": self.target, "risk": self.risk,
                "summary": self.summary, "key_args": self.key_args}

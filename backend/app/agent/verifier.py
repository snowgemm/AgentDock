"""Definition of Done and the evidence verifier.

This is a *structural* verifier: it proves the run produced a complete answer within
budget and left evidence of where it came from. It cannot judge whether the answer is
correct, so AgentDock reports SUCCEEDED as "answer produced and structurally verified"
and never as proof of real-world correctness.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class DefinitionOfDone:
    criteria: tuple[str, ...]
    max_answer_chars: int
    required_evidence: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {"criteria": list(self.criteria), "max_answer_chars": self.max_answer_chars,
                "required_evidence": list(self.required_evidence)}


def default_definition_of_done(max_answer_chars: int = 20_000) -> DefinitionOfDone:
    return DefinitionOfDone(
        criteria=(
            "A non-empty final answer addressing the request was produced.",
            "The answer was not truncated by the output limit.",
            "The answer is backed by a recorded model response.",
            "The run stayed within its token, tool, iteration and time budgets.",
            "The answer does not contain server credentials.",
        ),
        max_answer_chars=max_answer_chars,
        required_evidence=("model_response",),
    )


@dataclass(frozen=True, slots=True)
class RunFacts:
    finish: str
    within_budget: bool
    evidence: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class VerificationResult:
    passed: bool
    checks: tuple[dict[str, Any], ...] = field(default=())

    def to_json(self) -> dict[str, Any]:
        return {"passed": self.passed, "kind": "structural", "checks": list(self.checks)}


class Verifier(Protocol):
    def verify(self, done: DefinitionOfDone, answer: str, facts: RunFacts) -> VerificationResult: ...


class StructuralVerifier:
    def __init__(self, secrets: tuple[str, ...] = ()) -> None:
        self._secrets = tuple(s for s in secrets if len(s) >= 8)

    def verify(self, done: DefinitionOfDone, answer: str, facts: RunFacts) -> VerificationResult:
        have = {e.get("type") for e in facts.evidence if e.get("id")}
        checks = (
            {"name": "answer_present", "passed": bool(answer.strip())},
            {"name": "answer_within_limit", "passed": len(answer) <= done.max_answer_chars},
            {"name": "not_truncated", "passed": facts.finish == "stop"},
            {"name": "evidence_recorded", "passed": all(kind in have for kind in done.required_evidence)},
            {"name": "within_budget", "passed": facts.within_budget},
            {"name": "no_credential_echo", "passed": not any(s in answer for s in self._secrets)},
        )
        return VerificationResult(passed=all(c["passed"] for c in checks), checks=checks)

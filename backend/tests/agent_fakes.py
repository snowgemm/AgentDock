"""Deterministic test doubles for the agent: a scripted gateway and an in-memory TaskContext."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from app.agent.gateway import (
    GatewayError,
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    ToolCall,
    Usage,
)
from app.worker.handlers import LeaseLost, TaskCancelled


def text_response(text: str, *, tokens: int = 30, finish: str = "stop", rid: str | None = None) -> ModelResponse:
    rid = rid or f"resp_{uuid4().hex[:8]}"
    return ModelResponse(
        text=text, tool_calls=(), usage=Usage(tokens // 2, tokens - tokens // 2, tokens),
        model_id="fake-model", response_id=rid, finish=finish,  # type: ignore[arg-type]
        provider_items=({"type": "message", "role": "assistant", "content": text},),
    )


def tool_response(name: str, arguments: Any, *, call_id: str | None = None, tokens: int = 20) -> ModelResponse:
    call_id = call_id or f"call_{uuid4().hex[:8]}"
    raw = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return ModelResponse(
        text="", tool_calls=(ToolCall(call_id, name, raw),),
        usage=Usage(tokens // 2, tokens - tokens // 2, tokens), model_id="fake-model",
        response_id=f"resp_{uuid4().hex[:8]}", finish="tool_calls",
        provider_items=({"type": "function_call", "call_id": call_id, "name": name, "arguments": raw},),
    )


class FakeGateway:
    """Returns scripted responses/errors in order and records every request."""

    def __init__(self, script: list[ModelResponse | GatewayError], *, tools: bool = True) -> None:
        self.script = list(script)
        self.requests: list[ModelRequest] = []
        self._capabilities = ModelCapabilities("fake-model", tools, False, False, False, 8192)

    @property
    def capabilities(self) -> ModelCapabilities:
        return self._capabilities

    async def generate(self, request: ModelRequest, on_text_delta=None) -> ModelResponse:
        self.requests.append(request)
        if not self.script:
            raise AssertionError("FakeGateway script exhausted")
        item = self.script.pop(0)
        if isinstance(item, GatewayError):
            raise item
        return item


@dataclass
class FakeContext:
    prompt: str = "What is 2 + 2?"
    title: str = "Math"
    task_id: UUID = field(default_factory=uuid4)
    tenant_id: UUID = field(default_factory=uuid4)
    attempt: int = 1
    events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    checkpoints: dict[int, dict[str, Any]] = field(default_factory=dict)
    transitions: list[str] = field(default_factory=list)
    cancelled: bool = False
    audits: list[tuple[str, str]] = field(default_factory=list)

    async def checkpoint(self) -> None:
        if self.cancelled:
            raise TaskCancelled

    async def emit(self, event_type: str, payload: dict[str, Any]) -> int:
        self.events.append((event_type, payload))
        return len(self.events)

    async def transition(self, target: str, event_type: str, payload: dict[str, Any]) -> None:
        self.transitions.append(target)
        self.events.append((event_type, payload))

    async def read_context(self, section: str, limit: int) -> dict[str, Any]:
        if section == "task":
            return {"title": self.title, "prompt": self.prompt, "status": "RUNNING"}
        return {"events": [{"type": t} for t, _ in self.events[-limit:]]}

    async def save_checkpoint(self, iteration: int, state: dict[str, Any]) -> None:
        self.checkpoints[iteration] = json.loads(json.dumps(state))

    async def load_checkpoint(self) -> dict[str, Any] | None:
        return self.checkpoints[max(self.checkpoints)] if self.checkpoints else None

    async def run_step(self, step_key, effect, *, idempotent: bool = False):
        return await effect()

    async def policy_facts(self):
        from app.policy.pdp import PolicyFacts

        return PolicyFacts(True, True, "RUNNING", True)

    async def audit(self, action, target, outcome, details, policy_version=None) -> None:
        self.audits.append((action, outcome))

    async def request_approval(self, action, ttl_seconds):
        raise AssertionError("the default read-only tool never needs approval")

    async def get_approval(self, approval_id):
        raise AssertionError("unused")

    async def execute_approved(self, step_key, digest, effect):
        raise AssertionError("unused")

    def types(self) -> list[str]:
        return [t for t, _ in self.events]

    def payload(self, event_type: str) -> dict[str, Any]:
        return next(p for t, p in self.events if t == event_type)


__all__ = ["FakeContext", "FakeGateway", "LeaseLost", "text_response", "tool_response"]

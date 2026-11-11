"""AgentDock-owned model interface.

Provider SDK types never leave an adapter. Capabilities are declared per exact model
ID by the adapter and exercised by contract tests; callers must check them rather
than assume a model supports tools, streaming or structured output.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


@dataclass(frozen=True, slots=True)
class ModelCapabilities:
    model_id: str
    supports_tools: bool
    supports_streaming: bool
    supports_structured_output: bool
    supports_vision: bool
    context_window_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema generated from the server-side args model


@dataclass(frozen=True, slots=True)
class ToolCall:
    call_id: str
    name: str
    arguments_json: str  # untrusted model output; validate before use


@dataclass(frozen=True, slots=True)
class Message:
    """Provider-neutral conversation item.

    kind: "user" (text), "provider_items" (opaque assistant output replayed verbatim to
    the same provider), "tool_result" (call_id + text, wrapped as untrusted data).
    """

    kind: Literal["user", "provider_items", "tool_result"]
    text: str = ""
    call_id: str = ""
    items: tuple[dict[str, Any], ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {"kind": self.kind, "text": self.text, "call_id": self.call_id, "items": list(self.items)}

    @staticmethod
    def from_json(data: dict[str, Any]) -> "Message":
        return Message(
            kind=data["kind"], text=data.get("text", ""), call_id=data.get("call_id", ""),
            items=tuple(data.get("items", ())),
        )


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float | None = None  # None when pricing for the model is not configured

    def plus(self, other: "Usage") -> "Usage":
        cost = None if self.cost_usd is None or other.cost_usd is None else self.cost_usd + other.cost_usd
        return Usage(
            self.input_tokens + other.input_tokens, self.output_tokens + other.output_tokens,
            self.total_tokens + other.total_tokens, cost,
        )


@dataclass(frozen=True, slots=True)
class ModelRequest:
    instructions: str  # server-owned policy; never contains user or tool content
    messages: tuple[Message, ...]
    tools: tuple[ToolSpec, ...] = ()
    max_output_tokens: int = 1024
    timeout_seconds: float = 60.0


@dataclass(frozen=True, slots=True)
class ModelResponse:
    text: str
    tool_calls: tuple[ToolCall, ...]
    usage: Usage
    model_id: str
    response_id: str | None
    finish: Literal["stop", "tool_calls", "length", "other"]
    provider_items: tuple[dict[str, Any], ...] = field(default=())


class GatewayError(Exception):
    """Normalized provider failure. ``code`` is safe to store and show; never raw text."""

    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class ProviderNotConfigured(GatewayError):
    def __init__(self) -> None:
        super().__init__("provider-not-configured", retryable=False)


TextDelta = Callable[[str], Awaitable[None]]


class ModelGateway(Protocol):
    @property
    def capabilities(self) -> ModelCapabilities: ...

    async def generate(
        self, request: ModelRequest, on_text_delta: TextDelta | None = None
    ) -> ModelResponse:
        """One model turn. With ``on_text_delta`` the adapter streams text as it arrives.

        Cancelling the awaiting task cancels the in-flight HTTP request. Failures are
        raised as GatewayError (retryable or permanent), never as provider exceptions.
        """

"""OpenAI Responses API adapter (official ``openai`` SDK).

Stateless usage: ``store=False`` and prior output items are replayed in ``input``.
The exact model ID is operator-supplied; capabilities are what AgentDock verified
for tool-less/tool calling through contract tests, not marketing claims.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import openai
from openai import AsyncOpenAI

from app.agent.gateway import (
    GatewayError,
    Message,
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    TextDelta,
    ToolCall,
    Usage,
)

_PERMANENT_STATUS_CODES = {
    400: "bad_request", 401: "provider_auth", 403: "provider_auth", 404: "model_not_found",
    422: "bad_request",
}


def normalize_error(error: BaseException) -> GatewayError:
    """Map SDK/transport exceptions to codes only; messages may echo prompts or keys."""
    if isinstance(error, GatewayError):
        return error
    if isinstance(error, (openai.APITimeoutError, asyncio.TimeoutError)):
        return GatewayError("provider_timeout", retryable=True)
    if isinstance(error, openai.APIConnectionError):
        return GatewayError("provider_unreachable", retryable=True)
    if isinstance(error, openai.RateLimitError):
        return GatewayError("provider_rate_limited", retryable=True)
    if isinstance(error, openai.APIStatusError):
        status = error.status_code
        if status in (408, 409, 429) or status >= 500:
            return GatewayError("provider_unavailable", retryable=True)
        return GatewayError(_PERMANENT_STATUS_CODES.get(status, "provider_rejected"), retryable=False)
    return GatewayError("provider_error", retryable=False)


class OpenAIGateway:
    def __init__(
        self,
        client: AsyncOpenAI,
        model_id: str,
        *,
        context_window_tokens: int | None = None,
        input_cost_per_million: float | None = None,
        output_cost_per_million: float | None = None,
    ) -> None:
        if not model_id.strip():
            raise ValueError("model_id is required")
        self._client = client
        self._model_id = model_id
        self._prices = (input_cost_per_million, output_cost_per_million)
        self._capabilities = ModelCapabilities(
            model_id=model_id,
            supports_tools=True,
            supports_streaming=True,
            supports_structured_output=False,  # not exercised yet; do not claim it
            supports_vision=False,
            context_window_tokens=context_window_tokens,
        )

    @property
    def capabilities(self) -> ModelCapabilities:
        return self._capabilities

    # ------------------------------------------------------------------ request

    @staticmethod
    def _input_items(messages: tuple[Message, ...]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for message in messages:
            if message.kind == "user":
                items.append({"role": "user", "content": message.text})
            elif message.kind == "provider_items":
                items.extend(dict(item) for item in message.items)
            else:
                items.append(
                    {"type": "function_call_output", "call_id": message.call_id, "output": message.text}
                )
        return items

    def _kwargs(self, request: ModelRequest) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self._model_id,
            "instructions": request.instructions,
            "input": self._input_items(request.messages),
            "max_output_tokens": request.max_output_tokens,
            "store": False,
            "timeout": request.timeout_seconds,
        }
        if request.tools:
            kwargs["tools"] = [
                {"type": "function", "name": tool.name, "description": tool.description,
                 "parameters": tool.parameters, "strict": False}
                for tool in request.tools
            ]
            kwargs["tool_choice"] = "auto"
            kwargs["parallel_tool_calls"] = False
        return kwargs

    # ----------------------------------------------------------------- response

    def _usage(self, usage: Any) -> Usage:
        if usage is None:
            return Usage()
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        cost = None
        if self._prices[0] is not None and self._prices[1] is not None:
            cost = (input_tokens * self._prices[0] + output_tokens * self._prices[1]) / 1_000_000
        return Usage(input_tokens, output_tokens,
                     int(getattr(usage, "total_tokens", input_tokens + output_tokens) or 0), cost)

    def _parse(self, response: Any) -> ModelResponse:
        status = getattr(response, "status", "completed")
        if status in ("failed", "cancelled") or getattr(response, "error", None) is not None:
            raise GatewayError("provider_failed", retryable=status == "failed")
        text_parts: list[str] = []
        calls: list[ToolCall] = []
        items: list[dict[str, Any]] = []
        for item in response.output:
            items.append(item.model_dump(mode="json", exclude_none=True))
            if item.type == "message":
                for part in item.content:
                    if getattr(part, "type", "") == "output_text":
                        text_parts.append(part.text)
                    elif getattr(part, "type", "") == "refusal":
                        raise GatewayError("provider_refusal", retryable=False)
            elif item.type == "function_call":
                calls.append(ToolCall(item.call_id, item.name, item.arguments))
        incomplete = getattr(response, "incomplete_details", None)
        if status == "incomplete":
            reason = getattr(incomplete, "reason", None)
            finish = "length" if reason == "max_output_tokens" else "other"
        else:
            finish = "tool_calls" if calls else "stop"
        return ModelResponse(
            text="".join(text_parts), tool_calls=tuple(calls), usage=self._usage(response.usage),
            model_id=getattr(response, "model", self._model_id) or self._model_id,
            response_id=getattr(response, "id", None), finish=finish,
            provider_items=tuple(items),
        )

    # --------------------------------------------------------------------- call

    async def generate(
        self, request: ModelRequest, on_text_delta: TextDelta | None = None
    ) -> ModelResponse:
        kwargs = self._kwargs(request)
        try:
            return await asyncio.wait_for(
                self._call(kwargs, on_text_delta), timeout=request.timeout_seconds + 5
            )
        except asyncio.CancelledError:
            raise  # cancellation propagates; httpx closes the in-flight request
        except Exception as error:  # noqa: BLE001 - normalized below
            raise normalize_error(error) from None

    async def _call(self, kwargs: dict[str, Any], on_text_delta: TextDelta | None) -> ModelResponse:
        if on_text_delta is None:
            return self._parse(await self._client.responses.create(**kwargs))
        final = None
        stream = await self._client.responses.create(stream=True, **kwargs)
        async for event in stream:
            if event.type == "response.output_text.delta":
                await on_text_delta(event.delta)
            elif event.type in ("response.completed", "response.incomplete", "response.failed"):
                final = event.response
        if final is None:
            raise GatewayError("provider_stream_incomplete", retryable=True)
        return self._parse(final)


def tool_arguments_preview(arguments_json: str, limit: int = 200) -> str:
    """Bounded, JSON-normalized text for logs/events (never for execution)."""
    try:
        return json.dumps(json.loads(arguments_json), separators=(",", ":"))[:limit]
    except ValueError:
        return "<invalid-json>"

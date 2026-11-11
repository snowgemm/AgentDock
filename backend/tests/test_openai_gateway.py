"""Contract tests for the OpenAI Responses adapter using a mocked HTTP transport."""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from openai import AsyncOpenAI

from app.agent.gateway import GatewayError, Message, ModelRequest, ToolSpec
from app.agent.handler import build_agent_handler
from app.agent.openai_gateway import OpenAIGateway
from app.core.config import Settings
from app.worker.handlers import HandlerNotConfigured

SECRET = "sk-test-very-secret-key-123456"
TOOL = ToolSpec("get_task_context", "read", {"type": "object", "properties": {"section": {"type": "string"}}})


def response_body(output: list[dict], *, status: str = "completed", usage: bool = True, **extra) -> dict:
    body = {
        "id": "resp_abc", "object": "response", "created_at": 0, "status": status, "model": "exact-model-id",
        "output": output, "parallel_tool_calls": False, "tool_choice": "auto", "tools": [],
        "error": None, "incomplete_details": None, **extra,
    }
    if usage:
        body["usage"] = {"input_tokens": 100, "output_tokens": 40, "total_tokens": 140,
                         "input_tokens_details": {"cached_tokens": 0},
                         "output_tokens_details": {"reasoning_tokens": 0}}
    return body


def message_item(text: str) -> dict:
    return {"type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": text, "annotations": []}]}


def gateway_with(handler, **kwargs) -> tuple[OpenAIGateway, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    async def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return await handler(request) if asyncio.iscoroutinefunction(handler) else handler(request)

    client = AsyncOpenAI(api_key=SECRET, max_retries=0,
                         http_client=httpx.AsyncClient(transport=httpx.MockTransport(wrapped)))
    return OpenAIGateway(client, "exact-model-id", **kwargs), seen


def request(**kwargs) -> ModelRequest:
    return ModelRequest(instructions="policy", messages=(Message(kind="user", text="hello"),), **kwargs)


def run(coro):
    return asyncio.run(coro)


def test_request_shape_uses_exact_model_stateless_and_declared_tools() -> None:
    gateway, seen = gateway_with(lambda r: httpx.Response(200, json=response_body([message_item("hi")])))
    result = run(gateway.generate(request(tools=(TOOL,), max_output_tokens=321)))

    body = json.loads(seen[0].content)
    assert seen[0].url.path.endswith("/responses")
    assert body["model"] == "exact-model-id" and body["store"] is False
    assert body["instructions"] == "policy" and body["max_output_tokens"] == 321
    assert body["input"] == [{"role": "user", "content": "hello"}]
    assert body["tools"][0]["type"] == "function" and body["tools"][0]["name"] == "get_task_context"
    assert body["parallel_tool_calls"] is False
    assert result.text == "hi" and result.finish == "stop" and result.response_id == "resp_abc"
    assert (result.usage.input_tokens, result.usage.output_tokens, result.usage.total_tokens) == (100, 40, 140)
    assert result.usage.cost_usd is None  # no pricing configured: do not invent a cost


def test_cost_is_reported_only_when_pricing_is_configured() -> None:
    gateway, _ = gateway_with(lambda r: httpx.Response(200, json=response_body([message_item("hi")])),
                              input_cost_per_million=2.0, output_cost_per_million=8.0)
    assert run(gateway.generate(request())).usage.cost_usd == pytest.approx((100 * 2 + 40 * 8) / 1e6)


def test_tool_calls_are_parsed_and_results_replayed_as_function_call_outputs() -> None:
    call = {"type": "function_call", "id": "fc_1", "call_id": "call_9", "name": "get_task_context",
            "arguments": "{\"section\":\"task\"}", "status": "completed"}
    gateway, seen = gateway_with(lambda r: httpx.Response(200, json=response_body([call])))
    first = run(gateway.generate(request(tools=(TOOL,))))
    assert first.finish == "tool_calls"
    assert [(c.call_id, c.name, c.arguments_json) for c in first.tool_calls] == [
        ("call_9", "get_task_context", "{\"section\":\"task\"}")]

    follow_up = ModelRequest(
        instructions="policy",
        messages=(Message(kind="user", text="hello"),
                  Message(kind="provider_items", items=first.provider_items),
                  Message(kind="tool_result", call_id="call_9", text="{\"trust\":\"untrusted_data\"}")),
    )
    run(gateway.generate(follow_up))
    items = json.loads(seen[1].content)["input"]
    assert items[1]["type"] == "function_call" and items[1]["call_id"] == "call_9"
    assert items[2] == {"type": "function_call_output", "call_id": "call_9", "output": "{\"trust\":\"untrusted_data\"}"}


def test_incomplete_output_is_reported_as_length() -> None:
    body = response_body([message_item("cut")], status="incomplete",
                         incomplete_details={"reason": "max_output_tokens"})
    gateway, _ = gateway_with(lambda r: httpx.Response(200, json=body))
    assert run(gateway.generate(request())).finish == "length"


def test_refusals_and_failed_responses_are_normalized() -> None:
    refusal = {"type": "message", "id": "m", "role": "assistant", "status": "completed",
               "content": [{"type": "refusal", "refusal": "no"}]}
    gateway, _ = gateway_with(lambda r: httpx.Response(200, json=response_body([refusal])))
    with pytest.raises(GatewayError) as caught:
        run(gateway.generate(request()))
    assert (caught.value.code, caught.value.retryable) == ("provider_refusal", False)


@pytest.mark.parametrize("status,code,retryable", [
    (429, "provider_rate_limited", True), (500, "provider_unavailable", True),
    (503, "provider_unavailable", True), (408, "provider_unavailable", True),
    (401, "provider_auth", False), (403, "provider_auth", False),
    (404, "model_not_found", False), (400, "bad_request", False), (422, "bad_request", False),
])
def test_http_errors_map_to_retryable_or_permanent_codes_without_leaking_details(status, code, retryable) -> None:
    leaky = {"error": {"message": f"bad key {SECRET} and prompt hello", "type": "x"}}
    gateway, _ = gateway_with(lambda r: httpx.Response(status, json=leaky))
    with pytest.raises(GatewayError) as caught:
        run(gateway.generate(request()))
    assert (caught.value.code, caught.value.retryable) == (code, retryable)
    assert SECRET not in str(caught.value) and "hello" not in str(caught.value)


def test_transport_failures_are_retryable() -> None:
    def timeout(_request):
        raise httpx.ReadTimeout("slow")

    def refused(_request):
        raise httpx.ConnectError("down")

    for handler, code in ((timeout, "provider_timeout"), (refused, "provider_unreachable")):
        gateway, _ = gateway_with(handler)
        with pytest.raises(GatewayError) as caught:
            run(gateway.generate(request(timeout_seconds=1)))
        assert (caught.value.code, caught.value.retryable) == (code, True)


def test_cancellation_aborts_the_inflight_call_and_is_not_swallowed() -> None:
    started = asyncio.Event()

    async def hang(_request):
        started.set()
        await asyncio.sleep(30)
        return httpx.Response(200, json=response_body([message_item("late")]))

    async def scenario() -> None:
        gateway, _ = gateway_with(hang)
        task = asyncio.create_task(gateway.generate(request()))
        await asyncio.wait_for(started.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    run(scenario())


def test_streaming_delivers_text_deltas_then_the_final_response() -> None:
    final = response_body([message_item("Hello")])
    events = [
        {"type": "response.output_text.delta", "item_id": "msg_1", "output_index": 0, "content_index": 0,
         "delta": "Hel", "sequence_number": 1, "logprobs": []},
        {"type": "response.output_text.delta", "item_id": "msg_1", "output_index": 0, "content_index": 0,
         "delta": "lo", "sequence_number": 2, "logprobs": []},
        {"type": "response.completed", "response": final, "sequence_number": 3},
    ]
    sse = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events)
    gateway, seen = gateway_with(lambda r: httpx.Response(200, content=sse.encode(),
                                                          headers={"content-type": "text/event-stream"}))
    deltas: list[str] = []

    async def on_delta(text: str) -> None:
        deltas.append(text)

    result = run(gateway.generate(request(), on_delta))
    assert deltas == ["Hel", "lo"] and result.text == "Hello"
    assert json.loads(seen[0].content)["stream"] is True


def test_capabilities_name_the_exact_model_and_do_not_overclaim() -> None:
    gateway, _ = gateway_with(lambda r: httpx.Response(200, json=response_body([])))
    caps = gateway.capabilities
    assert caps.model_id == "exact-model-id" and caps.supports_tools and caps.supports_streaming
    assert not caps.supports_structured_output and not caps.supports_vision


class _NoKeys:
    async def get_api_key(self, provider: str):
        return None


def test_missing_model_or_key_fails_closed_with_provider_not_configured() -> None:
    no_model = Settings(environment="test")
    with pytest.raises(HandlerNotConfigured) as caught:
        run(build_agent_handler(no_model))
    assert caught.value.reason == "provider-not-configured"

    with pytest.raises(HandlerNotConfigured) as caught:
        run(build_agent_handler(Settings(environment="test", openai_model="m"), credentials=_NoKeys()))
    assert caught.value.reason == "provider-not-configured"


def test_a_configured_provider_builds_a_handler_with_the_key_from_the_credential_source() -> None:
    from pydantic import SecretStr

    class Keys:
        async def get_api_key(self, provider: str):
            return SecretStr(SECRET)

    handler = run(build_agent_handler(Settings(environment="test", openai_model="m"), credentials=Keys()))
    assert handler.name == "agent"

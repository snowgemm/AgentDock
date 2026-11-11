"""Registers the "agent" worker handler (AGENTDOCK_WORKER_HANDLER=agent)."""
from __future__ import annotations

from openai import AsyncOpenAI

from app.agent.credentials import CredentialSource, EnvCredentialSource
from app.agent.gateway import ModelGateway, ProviderNotConfigured
from app.agent.loop import AgentBudgets, AgentRunner
from app.agent.openai_gateway import OpenAIGateway
from app.agent.tools import ToolRegistry, default_tools
from app.agent.verifier import StructuralVerifier, Verifier
from app.core.config import Settings
from app.worker.handlers import (
    HandlerNotConfigured,
    HandlerOutcome,
    TaskContext,
    register_handler,
)


class AgentHandler:
    name = "agent"

    def __init__(self, gateway: ModelGateway, tools: ToolRegistry, budgets: AgentBudgets,
                 verifier: Verifier) -> None:
        self._runner = AgentRunner(gateway, tools, budgets, verifier)

    async def run(self, context: TaskContext) -> HandlerOutcome:
        return await self._runner.run(context)


def budgets_from_settings(settings: Settings) -> AgentBudgets:
    return AgentBudgets(
        max_iterations=settings.agent_max_iterations,
        max_tool_calls=settings.agent_max_tool_calls,
        max_total_tokens=settings.agent_max_total_tokens,
        max_output_tokens=settings.agent_max_output_tokens,
        wall_seconds=settings.agent_wall_seconds,
        model_timeout_seconds=settings.agent_model_timeout_seconds,
    )


async def build_agent_handler(
    settings: Settings, credentials: CredentialSource | None = None
) -> AgentHandler:
    """Fail closed: no model ID or no API key means no handler, so tasks stay QUEUED."""
    if not settings.openai_model:
        raise HandlerNotConfigured(ProviderNotConfigured().code)
    key = await (credentials or EnvCredentialSource()).get_api_key("openai")
    if key is None:
        raise HandlerNotConfigured(ProviderNotConfigured().code)
    client = AsyncOpenAI(api_key=key.get_secret_value(), max_retries=0)
    gateway = OpenAIGateway(
        client, settings.openai_model,
        context_window_tokens=settings.openai_context_window_tokens,
        input_cost_per_million=settings.openai_input_cost_per_million,
        output_cost_per_million=settings.openai_output_cost_per_million,
    )
    return AgentHandler(gateway, default_tools(), budgets_from_settings(settings),
                        StructuralVerifier(secrets=(key.get_secret_value(),)))


register_handler("agent", build_agent_handler)

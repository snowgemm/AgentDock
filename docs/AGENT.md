# Main Agent (single agent, one read-only tool)

**Status:** implemented and tested with a deterministic gateway and a mocked OpenAI HTTP transport. **No live-vendor run has been made**: it needs `OPENAI_API_KEY` and `AGENTDOCK_OPENAI_MODEL` (the live test in `backend/tests/test_agent_e2e.py` is skipped without them).

## Enabling it

```bash
AGENTDOCK_WORKER_HANDLER=agent
AGENTDOCK_OPENAI_MODEL=<exact model ID from your OpenAI account>   # no default is assumed
OPENAI_API_KEY=<from your secret store>                             # env only, never logged or sent to Android
```

With either value missing the worker logs `provider-not-configured`, reports it on `/readyz` (`"reason"`), claims nothing, and tasks stay `QUEUED`. Budgets: `AGENTDOCK_AGENT_MAX_ITERATIONS` (4), `_MAX_TOOL_CALLS` (3), `_MAX_TOTAL_TOKENS` (20000), `_MAX_OUTPUT_TOKENS` (1500), `_WALL_SECONDS` (120), `_MODEL_TIMEOUT_SECONDS` (60). Pricing (`AGENTDOCK_OPENAI_INPUT_COST_PER_MILLION`/`…OUTPUT…`) is optional; without it cost is reported as unknown, never guessed.

## Shape

* `ModelGateway` (`app/agent/gateway.py`) is AgentDock-owned: exact model ID, declared capabilities, optional text streaming, structured tool calls, token usage and optional cost, request timeout, cancellation, and normalized `GatewayError(code, retryable)`. Error text from the provider is never stored.
* One adapter: the official OpenAI SDK, Responses API, stateless (`store=false`, prior output items replayed). Replay of reasoning-model items is **unverified**. LiteLLM is intentionally not used yet.
* The loop (`app/agent/loop.py`) is an explicit bounded state machine, not LangGraph: its wheels resolve for Python 3.14, but it could not be exercised on 3.14 here, it adds ~25 transitive packages for one linear loop, and checkpoints/status live in PostgreSQL anyway. It sits behind `TaskHandler`, so a graph runtime can replace it.
* Exactly one tool, `get_task_context` (read-only, current task only — it has no task-ID argument). Names and JSON arguments are validated by a server-side pydantic model that also generates the schema shown to the model; unknown/disabled tools and bad arguments are rejected, recorded as `AGENT_TOOL_REJECTED` and answered with an error code only. Repeated rejection stops the run (`tool_misuse`). Tool output is size-bounded and wrapped as `{"trust":"untrusted_data"}`.
* System policy, user content and tool output travel in separate channels. Model and tool output are untrusted.
* Each run records a Definition of Done (`AGENT_STARTED`), per-call usage (`AGENT_MODEL_CALL`), a checkpoint per iteration (`task_checkpoints`), evidence references, and a final `AGENT_RESULT`.
* `SUCCEEDED` is reached only through `VERIFYING` after the structural verifier passes: non-empty answer, within length, not truncated, evidence recorded, within budget, no credential echo. A failed check ends the task `FAILED` (`verification_failed`) but keeps the answer, labelled unverified. **Structural verification does not prove the answer is correct.**
* Crash/retry recovery: a replacement attempt reloads the latest checkpoint and does not repeat finished model calls. A model call has no side effects, so re-sending one that may not have been recorded is safe; side-effecting steps must use `run_step` receipts and are never retried when completion is uncertain.

"""Narrow, typed handler interface between the worker and task execution logic."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from app.core.config import Settings


class RetryableError(Exception):
    """A transient failure; the worker may retry the task with backoff."""

    def __init__(self, code: str = "retryable_error") -> None:
        super().__init__(code)
        self.code = code


class PermanentError(Exception):
    """A failure retrying cannot fix; the task becomes FAILED."""

    def __init__(self, code: str = "permanent_error") -> None:
        super().__init__(code)
        self.code = code


class LeaseLost(Exception):
    """Another worker owns the task now; this worker must stop writing."""


class TaskCancelled(Exception):
    """The task left RUNNING outside this worker (for example, cancelled)."""


class UncertainSideEffect(PermanentError):
    """A side-effecting step started earlier but its completion was never recorded."""

    def __init__(self) -> None:
        super().__init__("side_effect_uncertain")


@dataclass(frozen=True, slots=True)
class HandlerOutcome:
    """Final result of a successful run. ``summary`` must not contain secrets."""

    summary: dict[str, Any] = field(default_factory=dict)


class TaskContext(Protocol):
    """What a handler can do. All writes are fenced by the worker's lease token."""

    task_id: UUID
    tenant_id: UUID
    title: str
    prompt: str
    attempt: int

    async def checkpoint(self) -> None:
        """Raise LeaseLost/TaskCancelled if this worker should stop."""

    async def emit(self, event_type: str, payload: dict[str, Any]) -> int:
        """Append a task event and return its sequence."""

    async def transition(self, target: str, event_type: str, payload: dict[str, Any]) -> None:
        """Move the task through the legal-transition table, appending an event."""

    async def read_context(self, section: str, limit: int) -> dict[str, Any]:
        """Read-only view of this task's own record ("task" or "recent_events")."""

    async def save_checkpoint(self, iteration: int, state: dict[str, Any]) -> None:
        """Persist agent working state; a replacement worker resumes from the latest."""

    async def load_checkpoint(self) -> dict[str, Any] | None: ...

    async def run_step(
        self,
        step_key: str,
        effect: Callable[[], Awaitable[dict[str, Any]]],
        *,
        idempotent: bool = False,
    ) -> dict[str, Any]:
        """Run a side effect at most once.

        A STARTED receipt is committed before the effect runs. If a previous attempt
        left a STARTED receipt behind, the effect is re-run only when ``idempotent``;
        otherwise UncertainSideEffect is raised. A COMPLETED receipt returns its stored
        result without running the effect again.
        """


class TaskHandler(Protocol):
    name: str

    async def run(self, context: TaskContext) -> HandlerOutcome: ...


HandlerFactory = Callable[[Settings], Awaitable[TaskHandler]]
HANDLER_FACTORIES: dict[str, HandlerFactory] = {}


def register_handler(name: str, factory: HandlerFactory) -> None:
    HANDLER_FACTORIES[name] = factory


class HandlerNotConfigured(RuntimeError):
    """The worker must not claim tasks; ``reason`` is a stable operator-facing code."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def build_handler(settings: Settings) -> TaskHandler | None:
    """Return the configured handler, or None (the worker then claims nothing).

    Raises HandlerNotConfigured when a handler is selected but cannot be built safely
    (for example the model provider is not configured).
    """
    if not settings.worker_handler:
        return None
    factory = HANDLER_FACTORIES.get(settings.worker_handler)
    if factory is None:
        raise HandlerNotConfigured("unknown-handler")
    return await factory(settings)

"""Worker loop: claim -> run handler under a heartbeat -> finish, with graceful shutdown."""
from __future__ import annotations

import asyncio
import logging
import random
import socket
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from time import monotonic
from typing import Any

from app.core.config import Settings
from app.worker.handlers import (
    HandlerOutcome,
    LeaseLost,
    PermanentError,
    RetryableError,
    TaskCancelled,
    TaskHandler,
)
from app.worker.store import Execution, Lease, WorkerStore
from app.worker.transitions import IllegalTransition

logger = logging.getLogger("agentdock.worker")


@dataclass
class WorkerHealth:
    started_at: float = field(default_factory=monotonic)
    last_poll_at: float | None = None
    last_db_ok_at: float | None = None
    claiming: bool = False
    reason: str | None = None  # why the worker is not claiming, when it is not
    in_flight: int = 0
    stopping: bool = False

    def live(self, max_idle: float) -> bool:
        return self.last_poll_at is not None and monotonic() - self.last_poll_at < max_idle

    def ready(self, max_idle: float) -> bool:
        return (
            not self.stopping
            and self.live(max_idle)
            and self.last_db_ok_at is not None
            and monotonic() - self.last_db_ok_at < max_idle
        )


class _Context:
    """TaskContext implementation bound to one claimed lease."""

    def __init__(self, store: WorkerStore, lease: Lease, execution: Execution) -> None:
        self._store = store
        self._lease = lease
        self.task_id = lease.task_id
        self.tenant_id = lease.tenant_id
        self.attempt = lease.attempt
        self.title = execution.title
        self.prompt = execution.prompt

    async def checkpoint(self) -> None:
        await self._store.checkpoint(self._lease)

    async def emit(self, event_type: str, payload: dict[str, Any]) -> int:
        return await self._store.append_event(self._lease, event_type, payload)

    async def transition(self, target: str, event_type: str, payload: dict[str, Any]) -> None:
        await self._store.transition(self._lease, target, event_type, payload)

    async def read_context(self, section: str, limit: int) -> dict[str, Any]:
        return await self._store.read_context(self._lease, section, limit)

    async def save_checkpoint(self, iteration: int, state: dict[str, Any]) -> None:
        await self._store.save_checkpoint(self._lease, iteration, state)

    async def load_checkpoint(self) -> dict[str, Any] | None:
        return await self._store.load_checkpoint(self._lease)

    async def run_step(
        self,
        step_key: str,
        effect: Callable[[], Awaitable[dict[str, Any]]],
        *,
        idempotent: bool = False,
    ) -> dict[str, Any]:
        return await self._store.run_step(self._lease, step_key, effect, idempotent=idempotent)


def retry_delay(settings: Settings, attempt: int, jitter: Callable[[], float] = random.random) -> float:
    """Exponential backoff with +-20% jitter, capped."""
    base = min(settings.worker_retry_max_seconds, settings.worker_retry_base_seconds * (2 ** max(0, attempt - 1)))
    return max(0.0, base * (0.8 + 0.4 * jitter()))


class Worker:
    def __init__(
        self,
        settings: Settings,
        store: WorkerStore,
        handler: TaskHandler | None,
        *,
        owner: str | None = None,
        not_claiming_reason: str | None = None,
    ) -> None:
        self._settings = settings
        self._store = store
        self._handler = handler
        self._owner = owner or f"{socket.gethostname()}:{uuid.uuid4().hex[:8]}"
        self._stop = asyncio.Event()
        self.health = WorkerHealth(
            claiming=handler is not None,
            reason=None if handler is not None else (not_claiming_reason or "no-handler-configured"),
        )
        self._tasks: set[asyncio.Task[None]] = set()

    def request_stop(self) -> None:
        self.health.stopping = True
        self._stop.set()

    async def run(self) -> None:
        """Poll until stop is requested, then drain in-flight work within the grace period."""
        slots = asyncio.Semaphore(self._settings.worker_concurrency)
        while not self._stop.is_set():
            self.health.last_poll_at = monotonic()
            claimed = False
            if self._handler is not None:
                await slots.acquire()
                lease = None
                try:
                    lease = await self._store.claim_next(self._owner, self._settings.worker_lease_seconds)
                    self.health.last_db_ok_at = monotonic()
                except Exception:  # noqa: BLE001 - keep polling through transient DB errors
                    logger.warning("claim failed", exc_info=False)
                if lease is None:
                    slots.release()
                else:
                    claimed = True
                    task = asyncio.create_task(self._guarded(lease, slots))
                    self._tasks.add(task)
                    task.add_done_callback(self._tasks.discard)
            else:
                self.health.last_db_ok_at = monotonic()
            if not claimed:
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self._settings.worker_poll_seconds)
                except asyncio.TimeoutError:
                    pass
        await self._drain()

    async def _drain(self) -> None:
        pending = set(self._tasks)
        if not pending:
            return
        _, still_running = await asyncio.wait(pending, timeout=self._settings.worker_shutdown_grace_seconds)
        for task in still_running:
            task.cancel()
        if still_running:
            await asyncio.gather(*still_running, return_exceptions=True)

    async def _guarded(self, lease: Lease, slots: asyncio.Semaphore) -> None:
        self.health.in_flight += 1
        try:
            await self.process(lease)
        except asyncio.CancelledError:
            # Shutdown forced a stop: let another worker reclaim immediately.
            try:
                await asyncio.shield(self._store.abandon(lease))
            except Exception:  # noqa: BLE001
                pass
            raise
        except Exception:  # noqa: BLE001
            logger.exception("task %s processing failed", lease.task_id)
        finally:
            self.health.in_flight -= 1
            slots.release()

    async def process(self, lease: Lease) -> None:
        assert self._handler is not None
        try:
            execution = await self._store.begin_execution(lease)
        except LeaseLost:
            return
        if execution is None:
            return

        context = _Context(self._store, lease, execution)
        heartbeat = asyncio.create_task(self._heartbeat(lease))
        run = asyncio.create_task(self._run_handler(context))
        try:
            done, _ = await asyncio.wait({heartbeat, run}, return_when=asyncio.FIRST_COMPLETED)
            if run not in done:  # heartbeat ended first => lease lost
                run.cancel()
                await asyncio.gather(run, return_exceptions=True)
                return
            outcome = run.result() if not run.cancelled() else None
        except asyncio.CancelledError:
            run.cancel()
            raise
        except BaseException as error:  # noqa: BLE001 - classified below
            await self._finish_error(lease, error)
            return
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)

        if outcome is None:
            return
        try:
            await self._store.finish_success(lease, outcome.summary)
        except (LeaseLost, IllegalTransition):
            logger.warning("task %s result discarded: lease lost", lease.task_id)

    async def _run_handler(self, context: _Context) -> HandlerOutcome:
        assert self._handler is not None
        return await asyncio.wait_for(
            self._handler.run(context), timeout=self._settings.worker_task_timeout_seconds
        )

    async def _heartbeat(self, lease: Lease) -> None:
        interval = self._settings.worker_heartbeat_seconds
        while True:
            await asyncio.sleep(interval)
            try:
                if not await self._store.renew(lease, self._settings.worker_lease_seconds):
                    return  # lease lost: ending signals process() to stop the handler
            except Exception:  # noqa: BLE001 - a transient DB error is retried next beat
                logger.warning("heartbeat failed for %s", lease.task_id)

    async def _finish_error(self, lease: Lease, error: BaseException) -> None:
        try:
            if isinstance(error, LeaseLost):
                return
            if isinstance(error, TaskCancelled):
                await self._store.release_done(lease, "cancelled")
            elif isinstance(error, PermanentError):
                await self._store.finish_failure(lease, error.code)
            elif isinstance(error, (RetryableError, asyncio.TimeoutError)):
                code = error.code if isinstance(error, RetryableError) else "handler_timeout"
                if lease.attempt >= lease.max_attempts:
                    await self._store.finish_failure(lease, "retries_exhausted")
                else:
                    await self._store.schedule_retry(
                        lease, code, retry_delay(self._settings, lease.attempt)
                    )
            else:
                # Unknown errors are never retried: completion of any side effect is uncertain.
                logger.error("handler error for %s: %s", lease.task_id, type(error).__name__)
                await self._store.finish_failure(lease, "handler_error")
        except (LeaseLost, IllegalTransition):
            logger.warning("task %s error result discarded: lease lost", lease.task_id)

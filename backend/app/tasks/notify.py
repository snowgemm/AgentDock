"""LISTEN/NOTIFY wake-up hub for task event streams.

Notifications are hints only. Streams always read ``task_events`` from the database
and also poll on a bounded interval, so a lost, delayed or duplicated notification
can never lose or reorder history. If the LISTEN connection drops the hub reconnects
with backoff and wakes every stream so they re-read immediately.
"""
from __future__ import annotations

import asyncio
import logging
from uuid import UUID

import asyncpg

logger = logging.getLogger("agentdock.notify")
CHANNEL = "agentdock_task_events"


def to_asyncpg_dsn(sqlalchemy_url: str) -> str:
    return sqlalchemy_url.replace("postgresql+asyncpg://", "postgresql://", 1)


class TaskEventHub:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._waiters: dict[UUID, set[asyncio.Event]] = {}
        self._runner: asyncio.Task[None] | None = None
        self.connected = False

    async def start(self) -> None:
        if self._runner is None:
            self._runner = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._runner is not None:
            self._runner.cancel()
            await asyncio.gather(self._runner, return_exceptions=True)
            self._runner = None
        self.connected = False

    def subscribe(self, task_id: UUID) -> asyncio.Event:
        event = asyncio.Event()
        self._waiters.setdefault(task_id, set()).add(event)
        return event

    def unsubscribe(self, task_id: UUID, event: asyncio.Event) -> None:
        waiters = self._waiters.get(task_id)
        if waiters is not None:
            waiters.discard(event)
            if not waiters:
                del self._waiters[task_id]

    def _wake(self, task_id: UUID | None) -> None:
        targets = self._waiters.values() if task_id is None else [self._waiters.get(task_id, set())]
        for waiters in targets:
            for event in waiters:
                event.set()

    def _on_notify(self, _connection, _pid, _channel, payload: str) -> None:
        try:
            self._wake(UUID(payload.split(":")[1]))
        except (IndexError, ValueError):
            self._wake(None)  # unreadable hint: wake everyone, they re-read the table

    async def _run(self) -> None:
        delay = 1.0
        while True:
            connection = None
            try:
                connection = await asyncpg.connect(self._dsn, timeout=5)
                await connection.add_listener(CHANNEL, self._on_notify)
                self.connected = True
                delay = 1.0
                self._wake(None)  # anything committed while disconnected is re-read now
                while True:
                    await asyncio.sleep(15)
                    await connection.execute("SELECT 1")  # detects a dead connection
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - reconnect on any failure
                logger.warning("task event listener disconnected; retrying in %.0fs", delay)
            finally:
                self.connected = False
                if connection is not None:
                    try:
                        await connection.close(timeout=2)
                    except Exception:  # noqa: BLE001
                        pass
            await asyncio.sleep(delay)
            delay = min(30.0, delay * 2)

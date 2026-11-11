"""Entry point: ``python -m app.worker``. Shares the API image; runs its own lifecycle."""
from __future__ import annotations

import asyncio
import logging
import signal

from app.core.config import get_settings
from app.db.session import create_database_engine, create_session_factory
from app.worker.handlers import build_handler
from app.worker.health import serve_health
from app.worker.runner import Worker
from app.worker.store import WorkerStore

logger = logging.getLogger("agentdock.worker")


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    if settings.worker_database_url is None:
        raise SystemExit("AGENTDOCK_WORKER_DATABASE_URL is required (use the agentdock_worker role).")

    engine = create_database_engine(settings.worker_database_url.get_secret_value())
    handler = build_handler(settings)
    if handler is None:
        logger.warning("No AGENTDOCK_WORKER_HANDLER configured: the worker will not claim tasks.")
    worker = Worker(settings, WorkerStore(create_session_factory(engine)), handler)

    loop = asyncio.get_running_loop()
    for signal_number in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signal_number, worker.request_stop)

    health_server = None
    if settings.worker_health_port:
        health_server = await serve_health(
            worker.health, settings.worker_health_port, max_idle=settings.worker_poll_seconds * 5 + 10
        )
    try:
        await worker.run()
    finally:
        if health_server is not None:
            health_server.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

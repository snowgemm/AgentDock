"""Minimal liveness/readiness endpoint for the worker process (no web framework)."""
from __future__ import annotations

import asyncio
import json

from app.worker.runner import WorkerHealth


async def serve_health(health: WorkerHealth, port: int, max_idle: float) -> asyncio.AbstractServer:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request_line = (await asyncio.wait_for(reader.readline(), timeout=2)).decode("ascii", "replace")
            path = request_line.split(" ")[1] if " " in request_line else ""
            if path == "/healthz":
                ok = health.live(max_idle)
            elif path == "/readyz":
                ok = health.ready(max_idle)
            else:
                writer.write(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                return
            body = json.dumps(
                {"status": "ok" if ok else "unavailable", "claiming": health.claiming,
                 "in_flight": health.in_flight}
            ).encode()
            status = b"200 OK" if ok else b"503 Service Unavailable"
            writer.write(
                b"HTTP/1.1 " + status + b"\r\nContent-Type: application/json\r\nContent-Length: "
                + str(len(body)).encode() + b"\r\nConnection: close\r\n\r\n" + body
            )
        except (asyncio.TimeoutError, ConnectionError):
            pass
        finally:
            try:
                await writer.drain()
            except ConnectionError:
                pass
            writer.close()

    return await asyncio.start_server(handle, host="0.0.0.0", port=port)

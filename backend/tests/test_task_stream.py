"""SSE timeline tests: replay, reconnect, heartbeat, live delivery, access control."""
from __future__ import annotations

import asyncio
import json
import threading
import time
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from test_tasks_api import (  # noqa: F401 - fixture reuse
    ADMIN_DATABASE_URL,
    _cleanup_identity,
    _external_access_token,
    signed_in_client,
)

pytestmark = pytest.mark.skipif(
    not ADMIN_DATABASE_URL,
    reason="PostgreSQL integration URLs are not configured; CI always configures them.",
)


def _admin(sql: str, **params) -> None:
    async def go() -> None:
        engine = create_async_engine(ADMIN_DATABASE_URL)
        try:
            async with engine.begin() as connection:
                await connection.execute(text(sql), params)
        finally:
            await engine.dispose()

    asyncio.run(go())


def _add_event(tenant_id: str, task_id: str, sequence: int, event_type: str = "STEP") -> None:
    _admin(
        "INSERT INTO task_events (id, tenant_id, task_id, sequence, event_type, payload) "
        "VALUES (gen_random_uuid(), :t, :k, :s, :e, '{}')",
        t=tenant_id, k=task_id, s=sequence, e=event_type,
    )


def _configure(ctx, **overrides) -> None:
    settings = ctx["settings"]
    values = dict(sse_heartbeat_seconds=0.3, sse_poll_seconds=0.2, sse_max_lifetime_seconds=1.2,
                  sse_revalidate_seconds=20.0)
    values.update(overrides)
    for key, value in values.items():
        setattr(settings, key, value)


def _create_task(ctx) -> str:
    response = ctx["client"].post(
        "/api/v1/tasks",
        headers={**ctx["headers"], "Idempotency-Key": uuid4().hex},
        json={"title": "Streamed", "prompt": "Stream me"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _stream(ctx, task_id: str, **headers) -> str:
    with ctx["client"].stream(
        "GET", f"/api/v1/tasks/{task_id}/events/stream",
        headers={**ctx["headers"], **headers},
    ) as response:
        assert response.status_code == 200, response.read()
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "no-store"
        return "".join(response.iter_text())


def _frames(body: str) -> list[dict]:
    frames = []
    for block in body.split("\n\n"):
        fields = {"comment": []}
        for line in block.split("\n"):
            if line.startswith(":"):
                fields["comment"].append(line[1:].strip())
            elif ": " in line:
                key, value = line.split(": ", 1)
                fields[key] = value
        if len(fields) > 1 or fields["comment"]:
            frames.append(fields)
    return frames


def _events(body: str) -> list[dict]:
    return [
        {**json.loads(f["data"]), "sse_id": int(f["id"])}
        for f in _frames(body) if f.get("event") == "task_event"
    ]


def test_stream_replays_from_the_beginning_then_asks_clients_to_reconnect(signed_in_client) -> None:
    ctx = signed_in_client
    _configure(ctx)
    task_id = _create_task(ctx)
    for sequence in (2, 3):
        _add_event(ctx["tenant_id"], task_id, sequence)

    body = _stream(ctx, task_id)

    events = _events(body)
    assert [e["sequence"] for e in events] == [1, 2, 3]
    assert [e["sse_id"] for e in events] == [1, 2, 3]  # SSE id is the persisted sequence
    assert events[0]["event_type"] == "TASK_CREATED"
    assert body.startswith("retry: 3000")
    assert _frames(body)[-1]["event"] == "reconnect"


def test_last_event_id_resumes_after_a_dropped_connection_without_duplicates(signed_in_client) -> None:
    ctx = signed_in_client
    _configure(ctx)
    task_id = _create_task(ctx)
    for sequence in (2, 3):
        _add_event(ctx["tenant_id"], task_id, sequence)

    first = _events(_stream(ctx, task_id, **{"Last-Event-ID": "1"}))
    assert [e["sequence"] for e in first] == [2, 3]

    for sequence in (4, 5):
        _add_event(ctx["tenant_id"], task_id, sequence)
    second = _events(_stream(ctx, task_id, **{"Last-Event-ID": str(first[-1]["sse_id"])}))
    assert [e["sequence"] for e in second] == [4, 5]

    # Query parameter works too and the larger cursor wins.
    third = ctx["client"].get(
        f"/api/v1/tasks/{task_id}/events/stream?after_sequence=4",
        headers={**ctx["headers"], "Last-Event-ID": "2"},
    )
    assert [e["sequence"] for e in _events(third.text)] == [5]


def test_events_committed_while_streaming_are_delivered(signed_in_client) -> None:
    ctx = signed_in_client
    _configure(ctx, sse_max_lifetime_seconds=2.0)
    task_id = _create_task(ctx)
    timer = threading.Timer(0.6, _add_event, args=(ctx["tenant_id"], task_id, 2, "LIVE"))
    timer.start()
    try:
        events = _events(_stream(ctx, task_id))
    finally:
        timer.join()
    assert [e["event_type"] for e in events] == ["TASK_CREATED", "LIVE"]


def test_notify_wakes_a_stream_long_before_its_poll_interval(signed_in_client) -> None:
    ctx = signed_in_client
    # Polling alone (30s) could not deliver within the 2.5s lifetime: NOTIFY must wake it.
    _configure(ctx, sse_poll_seconds=30.0, sse_heartbeat_seconds=30.0, sse_max_lifetime_seconds=2.5)
    task_id = _create_task(ctx)
    timer = threading.Timer(1.0, _add_event, args=(ctx["tenant_id"], task_id, 2, "WOKEN"))
    timer.start()
    try:
        events = _events(_stream(ctx, task_id))
    finally:
        timer.join()
    assert [e["event_type"] for e in events] == ["TASK_CREATED", "WOKEN"]


def test_idle_streams_send_heartbeat_comments(signed_in_client) -> None:
    ctx = signed_in_client
    _configure(ctx, sse_heartbeat_seconds=0.3, sse_max_lifetime_seconds=1.5)
    task_id = _create_task(ctx)
    frames = _frames(_stream(ctx, task_id, **{"Last-Event-ID": "1"}))
    assert any("heartbeat" in f["comment"] for f in frames)
    assert frames[-1]["event"] == "reconnect"


def test_terminal_tasks_end_the_stream_after_replay(signed_in_client) -> None:
    ctx = signed_in_client
    _configure(ctx, sse_max_lifetime_seconds=5.0)
    task_id = _create_task(ctx)
    _admin("UPDATE tasks SET status = 'SUCCEEDED' WHERE id = :id", id=task_id)
    started = time.monotonic()
    frames = _frames(_stream(ctx, task_id))
    assert time.monotonic() - started < 3  # ended by itself, not by the lifetime cap
    assert frames[-1]["event"] == "end"
    assert json.loads(frames[-1]["data"])["status"] == "SUCCEEDED"


def test_access_is_denied_across_tenants_and_without_valid_credentials(signed_in_client) -> None:
    ctx = signed_in_client
    task_id = _create_task(ctx)
    subject = f"stream-other-{uuid4().hex}"
    try:
        other = ctx["client"].post(
            "/api/v1/auth/session",
            headers={"Authorization": f"Bearer {_external_access_token(ctx['private_key'], subject)}"},
        )
        assert other.status_code == 201
        other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
        url = f"/api/v1/tasks/{task_id}/events/stream"

        assert ctx["client"].get(url, headers=other_headers).status_code == 404  # other workspace
        assert ctx["client"].get(url).status_code == 401
        assert ctx["client"].get(url, headers={"Authorization": "Bearer nope"}).status_code == 401
        assert ctx["client"].get(
            url, headers={**ctx["headers"], "Last-Event-ID": "abc"}
        ).status_code == 400
        assert ctx["client"].get(
            f"/api/v1/tasks/{uuid4()}/events/stream", headers=ctx["headers"]
        ).status_code == 404
    finally:
        asyncio.run(_cleanup_identity(subject))


def test_a_revoked_session_is_cut_off_mid_stream(signed_in_client) -> None:
    ctx = signed_in_client
    _configure(ctx, sse_revalidate_seconds=0.2, sse_max_lifetime_seconds=5.0)
    task_id = _create_task(ctx)
    timer = threading.Timer(
        0.5, _admin,
        args=("UPDATE user_sessions SET revoked_at = now() WHERE user_id = :u",),
        kwargs={"u": ctx["user_id"]},
    )
    timer.start()
    started = time.monotonic()
    try:
        frames = _frames(_stream(ctx, task_id, **{"Last-Event-ID": "1"}))
    finally:
        timer.join()
    assert time.monotonic() - started < 4
    assert frames[-1]["event"] == "error"
    assert json.loads(frames[-1]["data"]) == {"code": "access_revoked"}

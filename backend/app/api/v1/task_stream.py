from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.tasks.stream import Access, StreamConfig, check_access, event_stream

router = APIRouter(prefix="/tasks", tags=["tasks"])
_bearer = HTTPBearer(auto_error=False)


@router.get(
    "/{task_id}/events/stream",
    summary="Stream ordered task events (Server-Sent Events)",
    response_class=StreamingResponse,
)
async def stream_task_events(
    task_id: UUID,
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    after_sequence: Annotated[int, Query(ge=0)] = 0,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID", max_length=20)] = None,
) -> StreamingResponse:
    factory = request.app.state.database_session_factory
    if factory is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Database is not configured.")
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid or missing bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    resume_from = after_sequence
    if last_event_id:
        if not last_event_id.isascii() or not last_event_id.isdigit():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid Last-Event-ID.")
        resume_from = max(resume_from, int(last_event_id))

    verdict, tenant_id, _ = await check_access(factory, credentials.credentials, task_id)
    if verdict is Access.UNAUTHENTICATED:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid or missing bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if verdict is Access.FORBIDDEN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Active workspace membership is required.")
    if verdict is Access.NOT_FOUND or tenant_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found.")

    settings = request.app.state.settings
    config = StreamConfig(
        heartbeat_seconds=settings.sse_heartbeat_seconds,
        poll_seconds=settings.sse_poll_seconds,
        max_lifetime_seconds=settings.sse_max_lifetime_seconds,
        revalidate_seconds=settings.sse_revalidate_seconds,
    )
    body = event_stream(
        factory=factory,
        hub=getattr(request.app.state, "task_event_hub", None),
        config=config,
        token=credentials.credentials,
        tenant_id=tenant_id,
        task_id=task_id,
        after_sequence=resume_from,
    )
    return StreamingResponse(
        body,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

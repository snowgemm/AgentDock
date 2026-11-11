# Task event stream (SSE)

`GET /api/v1/tasks/{task_id}/events/stream` streams the same events as `GET …/events`, ordered by their persisted per-task sequence. `task_events` is the only source of truth; the stream is a delivery mechanism.

## Contract

* Authentication: `Authorization: Bearer <AgentDock access token>` (never a query parameter). Session, workspace membership and task visibility are checked when the stream opens — including every reconnect — and again every `AGENTDOCK_SSE_REVALIDATE_SECONDS` (default 20). Revocation or expiry ends the stream with `event: error` (`access_revoked`). A task in another workspace returns 404.
* Resume: `Last-Event-ID` (the sequence of the last event received) or `?after_sequence=`; the larger wins. A malformed `Last-Event-ID` is 400.
* Frames: `id: <sequence>`, `event: task_event`, `data: <TaskEventRead JSON>`. `: heartbeat` comment lines are sent every `AGENTDOCK_SSE_HEARTBEAT_SECONDS` (default 15) when idle. `retry: 3000` is sent on open.
* Lifecycle events: `event: reconnect` when the connection lifetime (`AGENTDOCK_SSE_MAX_LIFETIME_SECONDS`, default 300) elapses — reconnect immediately with `Last-Event-ID`; `event: end` once the task is terminal and all events were delivered — do not reconnect; `event: error` with `code` for `access_revoked` or `task_not_found`.
* No transaction is held between events; each poll uses a short transaction with the tenant context set, so forced RLS applies to every read.

## Delivery and loss

A database trigger issues `pg_notify('agentdock_task_events', 'tenant:task:sequence')` on commit of every `task_events` insert. The payload contains no task content. One LISTEN connection per API process wakes the matching streams. Notifications are hints only: each stream also polls every `AGENTDOCK_SSE_POLL_SECONDS` (default 2), the hub wakes every stream after it reconnects, and each wake re-reads `task_events` from the stream's last sequence. A lost, late or duplicate notification therefore cannot lose or reorder history.

## Android behaviour

The client streams only while the task screen is started (lifecycle-aware), always performs a REST catch-up before (re)connecting, suppresses duplicates by sequence, backs off exponentially (1 s doubling to 30 s with jitter) and shows connecting / live / reconnecting / offline / ended / sign-in-needed states. Only the last-seen sequence number is persisted (to mark new events on reopening); event content is never cached on disk.

## Not included

WebSockets, a message broker, per-user stream quotas and rate limits (a stream holds one HTTP connection and one asyncio task).

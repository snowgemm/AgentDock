# AgentDock Task API contract

**Status on `test`:** The FastAPI task create/list/detail/event endpoints, approvals endpoints, SSE task stream, and Android HTTP task/approval clients are present in this branch. Deployment against Supabase and live Android end-to-end verification are still pending.

## Authentication and tenant boundary

Every task endpoint requires an AgentDock access token in the Bearer authorization header. The API validates the internal session and checks active membership in the session's workspace. The workspace is derived from the authenticated session; requests cannot choose or override it with a tenant ID.

Tenant context is transaction-local and every tenant query executes under forced RLS. Task responses use `Cache-Control: no-store` and `Pragma: no-cache`.

## Endpoints

| Method | Path | Behavior |
|---|---|---|
| POST | `/api/v1/tasks` | Create and persist a task |
| GET | `/api/v1/tasks` | List tasks in the current workspace |
| GET | `/api/v1/tasks/{task_id}` | Read a task in the current workspace |
| GET | `/api/v1/tasks/{task_id}/events` | Read ordered events after a sequence |
| GET | `/api/v1/tasks/{task_id}/events/stream` | Stream task events using Server-Sent Events |
| GET | `/api/v1/tasks/{task_id}/approvals` | List approvals for a task |
| POST | `/api/v1/approvals/{approval_id}/decision` | Approve or deny the exact action digest |
| POST | `/api/v1/approvals/{approval_id}/revoke` | Revoke an eligible approval |

## Create and idempotency

Send `Idempotency-Key` (8–128 printable ASCII characters) with a JSON body:

```json
{
  "title": "Review a release",
  "prompt": "Check the release checklist and report missing gates."
}
```

- Title is trimmed and limited to 200 characters.
- Prompt is limited to 32,000 characters and cannot be blank.
- Unknown fields are rejected; client-supplied `tenant_id` is not accepted.
- The task, initial event, idempotency response and dispatch row are committed atomically.
- A successful create begins in `QUEUED`: it is persisted and awaiting a configured worker, not necessarily running.
- The idempotency window is 24 hours. Repeating the same key/request returns the same task; reusing the key for a different request returns 409.

## Timeline and streaming

Task event sequence numbers are task-local and strictly ordered. The initial event is `TASK_CREATED` with sequence 1. Use the events endpoint for replay and the stream endpoint for live updates. SSE supports `Last-Event-ID` and `after_sequence` reconnect positions, periodic heartbeats and bounded stream lifetime. PostgreSQL `LISTEN/NOTIFY` is only a wake-up hint; persisted `task_events` remain the source of truth.

## Approvals

The approval API returns a digest for the exact action presented to the user. A decision must echo that digest; a changed action is rejected rather than silently approved. Approval expiry, status and policy version are checked by the backend, and user decisions are written to the audit log. The model does not grant itself approval.

## Execution state

The durable worker uses PostgreSQL dispatch leases, fencing tokens, retries, receipts and checkpoints. A task can be accepted and remain `QUEUED` when no handler/provider is configured. The current optional single-agent handler uses OpenAI only when `AGENTDOCK_WORKER_HANDLER=agent`, `AGENTDOCK_OPENAI_MODEL` and `OPENAI_API_KEY` are configured. Database migration and API readiness do not imply model execution is configured.

## Not included in this slice

- Pause/resume/cancel API commands and complete lifecycle transition controls.
- Broad multi-agent orchestration and additional model-provider adapters.
- Usage quotas, per-user rate limits, retention cleanup and operational alerting.
- Live deployment and end-to-end provider/Android verification.

Do not present a `QUEUED` task as running or completed until the deployed worker reports a real execution result.

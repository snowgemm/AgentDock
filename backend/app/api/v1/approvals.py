"""Approval endpoints: list a task's approvals, decide, revoke.

The workspace comes from the authenticated session (never from the request). A decision
must echo the digest of the exact action the approver was shown; if the action changed
since it was displayed the digest no longer matches and the decision is refused.
"""
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.db.models import Approval
from app.policy import approvals as store
from app.tenancy.dependencies import TenantRequestContext, get_current_tenant_context

router = APIRouter(tags=["approvals"])
TenantContext = Annotated[
    TenantRequestContext, Depends(get_current_tenant_context, scope="function")
]


class ApprovalRead(BaseModel):
    id: UUID
    task_id: UUID
    tool: str
    target: str
    risk: str
    summary: str
    key_args: dict[str, Any]
    digest: str
    policy_version: str
    status: str
    expires_at: datetime
    created_at: datetime
    decided_at: datetime | None = None


class ApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "deny"]
    digest: str = Field(min_length=64, max_length=64, pattern="^[0-9a-f]{64}$")


def _read(approval: Approval, now: datetime) -> ApprovalRead:
    action = approval.action
    return ApprovalRead(
        id=approval.id, task_id=approval.task_id, tool=approval.tool_name,
        target=str(action.get("target", "")), risk=str(action.get("risk", "")),
        summary=str(action.get("summary", "")), key_args=dict(action.get("key_args", {})),
        digest=approval.action_digest, policy_version=approval.policy_version,
        status=store.effective_status(approval, now), expires_at=approval.expires_at,
        created_at=approval.created_at, decided_at=approval.decided_at,
    )


_ERRORS = {
    "not_found": status.HTTP_404_NOT_FOUND,
    "digest_mismatch": status.HTTP_409_CONFLICT,
    "not_pending": status.HTTP_409_CONFLICT,
    "expired": status.HTTP_409_CONFLICT,
    "not_revocable": status.HTTP_409_CONFLICT,
}


def _raise(error: store.ApprovalError) -> HTTPException:
    return HTTPException(_ERRORS.get(error.code, status.HTTP_409_CONFLICT), error.code)


@router.get("/tasks/{task_id}/approvals", response_model=list[ApprovalRead],
            summary="List approvals for a task in the current workspace")
async def list_task_approvals(task_id: UUID, context: TenantContext, response: Response) -> list[ApprovalRead]:
    response.headers["Cache-Control"] = "no-store"
    now = await store.db_now(context.db)
    rows = (
        await context.db.scalars(
            select(Approval)
            .where(Approval.tenant_id == context.principal.tenant_id, Approval.task_id == task_id)
            .order_by(Approval.created_at.desc())
            .limit(50)
        )
    ).all()
    return [_read(row, now) for row in rows]


@router.post("/approvals/{approval_id}/decision", response_model=ApprovalRead,
             summary="Approve or deny one exact action")
async def decide_approval(
    approval_id: UUID, payload: ApprovalDecision, context: TenantContext, response: Response
) -> ApprovalRead:
    response.headers["Cache-Control"] = "no-store"
    principal = context.principal
    try:
        row = await store.decide(
            context.db, tenant_id=principal.tenant_id, approval_id=approval_id,
            decider_user_id=principal.user_id, approve=payload.decision == "approve",
            digest=payload.digest,
        )
    except store.ApprovalError as error:
        raise _raise(error) from None
    await store.write_audit(
        context.db, tenant_id=principal.tenant_id, task_id=row.task_id, actor_type="user",
        actor_user_id=principal.user_id, action=f"approval.{payload.decision}",
        target=str(row.action.get("target", "")), outcome=row.status,
        policy_version=row.policy_version,
        details={"approval_id": str(row.id), "tool": row.tool_name, "digest": row.action_digest},
    )
    return _read(row, await store.db_now(context.db))


@router.post("/approvals/{approval_id}/revoke", response_model=ApprovalRead,
             summary="Revoke a pending or unused approval")
async def revoke_approval(approval_id: UUID, context: TenantContext, response: Response) -> ApprovalRead:
    response.headers["Cache-Control"] = "no-store"
    principal = context.principal
    try:
        row = await store.revoke(
            context.db, tenant_id=principal.tenant_id, approval_id=approval_id,
            user_id=principal.user_id,
        )
    except store.ApprovalError as error:
        raise _raise(error) from None
    await store.write_audit(
        context.db, tenant_id=principal.tenant_id, task_id=row.task_id, actor_type="user",
        actor_user_id=principal.user_id, action="approval.revoke",
        target=str(row.action.get("target", "")), outcome="REVOKED",
        policy_version=row.policy_version,
        details={"approval_id": str(row.id), "digest": row.action_digest},
    )
    return _read(row, await store.db_now(context.db))

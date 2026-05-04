from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approval import decide
from app.core.db import get_db
from app.core.permissions import Role, require
from app.models.approval import ApprovalRequest, ApprovalStatus
from app.models.user import User

router = APIRouter()


@router.get("")
async def inbox(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require(Role.MANAGER, Role.DIRECTOR)),
):
    stmt = select(ApprovalRequest).where(
        ApprovalRequest.status == ApprovalStatus.PENDING.value
    )
    if Role(user.role) == Role.MANAGER:
        # manager sees manager-level approvals; director sees all
        stmt = stmt.where(ApprovalRequest.required_role == Role.MANAGER.value)
    rows = (await db.scalars(stmt.order_by(ApprovalRequest.created_at.asc()))).all()
    return [
        {
            "id": str(r.id),
            "target_type": r.target_type,
            "target_id": str(r.target_id),
            "required_role": r.required_role,
            "reason": r.reason,
            "payload": r.payload,
            "requested_by": str(r.requested_by),
            "created_at": r.created_at,
        }
        for r in rows
    ]


@router.post("/{req_id}/approve")
async def approve(
    req_id: UUID,
    notes: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require(Role.MANAGER, Role.DIRECTOR)),
):
    try:
        req = await decide(db, request_id=req_id, decider_id=user.id,
                           decider_role=Role(user.role), approve=True, notes=notes)
    except PermissionError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e
    return {"id": str(req.id), "status": req.status}


@router.post("/{req_id}/reject")
async def reject(
    req_id: UUID,
    notes: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require(Role.MANAGER, Role.DIRECTOR)),
):
    try:
        req = await decide(db, request_id=req_id, decider_id=user.id,
                           decider_role=Role(user.role), approve=False, notes=notes)
    except PermissionError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e
    return {"id": str(req.id), "status": req.status}

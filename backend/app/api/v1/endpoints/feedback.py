"""Feedback: every account can write to the director.

- POST /feedback         — any authenticated user (internal or portal).
- GET  /feedback         — director only, filter by status.
- POST /feedback/{id}/resolve — director marks it handled.
New feedback also surfaces in the director's notification bell.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.permissions import Role
from app.models.feedback import Feedback
from app.models.user import User

router = APIRouter()


class FeedbackIn(BaseModel):
    message: str = Field(min_length=3, max_length=5000)
    page: str | None = Field(default=None, max_length=255)


def _out(f: Feedback, sender: User | None) -> dict:
    return {
        "id": str(f.id),
        "message": f.message,
        "page": f.page,
        "role": f.role,
        "status": f.status,
        "sender_name": sender.full_name if sender else None,
        "created_at": f.created_at,
        "resolved_at": f.resolved_at,
    }


@router.post("", status_code=201)
async def send_feedback(
    payload: FeedbackIn,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    f = Feedback(
        user_id=me.id,
        role=me.role,
        message=payload.message.strip(),
        page=payload.page,
        status="new",
    )
    db.add(f)
    await db.flush()
    return {"ok": True, "id": str(f.id)}


@router.get("")
async def list_feedback(
    status_eq: str | None = None,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    if Role(me.role) != Role.DIRECTOR:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Director only")
    stmt = select(Feedback).order_by(Feedback.created_at.desc()).limit(300)
    if status_eq:
        stmt = stmt.where(Feedback.status == status_eq)
    rows = (await db.scalars(stmt)).all()
    sender_ids = {f.user_id for f in rows if f.user_id}
    senders: dict = {}
    if sender_ids:
        for u in (await db.scalars(
            select(User).where(User.id.in_(list(sender_ids)))
        )).all():
            senders[u.id] = u
    return [_out(f, senders.get(f.user_id)) for f in rows]


@router.post("/{feedback_id}/resolve")
async def resolve_feedback(
    feedback_id: UUID,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    if Role(me.role) != Role.DIRECTOR:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Director only")
    f = await db.get(Feedback, feedback_id)
    if not f:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    f.status = "resolved"
    f.resolved_by = me.id
    f.resolved_at = datetime.now(UTC)
    await db.flush()
    return {"ok": True}

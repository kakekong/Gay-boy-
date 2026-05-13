"""Sales targets — monthly revenue goals per salesperson.

Director sets the targets. Anyone can read their own. HR / Manager / Director
can read everyone's.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.permissions import Role, require
from app.models.quotation import Quotation
from app.models.sales_target import SalesTarget
from app.models.user import User

router = APIRouter()
_director = require(Role.DIRECTOR)


class TargetIn(BaseModel):
    user_id: UUID
    period: str = Field(pattern=r"^\d{4}-\d{2}$")
    target_amount: float
    notes: str | None = None


class TargetPatch(BaseModel):
    target_amount: float | None = None
    notes: str | None = None


async def _achieved(db: AsyncSession, user_id: UUID, period: str) -> float:
    """Sum of won quotations for that user in the given month."""
    # period is YYYY-MM, build the date range
    year, month = period.split("-")
    y = int(year); m = int(month)
    start = datetime(y, m, 1)
    if m == 12:
        end = datetime(y + 1, 1, 1)
    else:
        end = datetime(y, m + 1, 1)

    rows = (await db.scalars(
        select(Quotation).where(
            Quotation.sales_pic_id == user_id,
            Quotation.status == "won",
            Quotation.updated_at >= start,
            Quotation.updated_at < end,
        )
    )).all()
    return float(sum(float(q.total or 0) for q in rows))


async def _serialize(db: AsyncSession, t: SalesTarget) -> dict:
    user = await db.get(User, t.user_id)
    achieved = await _achieved(db, t.user_id, t.period)
    target = float(t.target_amount or 0)
    return {
        "id": str(t.id),
        "user_id": str(t.user_id),
        "user_name": user.full_name if user else None,
        "period": t.period,
        "target_amount": target,
        "achieved_amount": achieved,
        "progress_pct": round((achieved / target) * 100, 1) if target else 0,
        "remaining": max(target - achieved, 0),
        "notes": t.notes,
    }


@router.get("")
async def list_targets(
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
    period: str | None = None,
    user_id: UUID | None = None,
):
    stmt = select(SalesTarget).order_by(SalesTarget.period.desc())
    if period:
        stmt = stmt.where(SalesTarget.period == period)
    if user_id:
        stmt = stmt.where(SalesTarget.user_id == user_id)
    # Sales can only see their own
    if Role(me.role) == Role.SALES:
        stmt = stmt.where(SalesTarget.user_id == me.id)
    elif Role(me.role) == Role.ADMIN:
        # Admin doesn't need to see targets — return empty
        return []

    rows = (await db.scalars(stmt)).all()
    return [await _serialize(db, t) for t in rows]


@router.get("/me/current")
async def my_current_target(
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    """Convenience: this month's target for the logged-in user. None if not set."""
    period = datetime.utcnow().strftime("%Y-%m")
    t = await db.scalar(
        select(SalesTarget).where(
            SalesTarget.user_id == me.id, SalesTarget.period == period
        )
    )
    if not t:
        achieved = await _achieved(db, me.id, period)
        return {
            "user_id": str(me.id), "period": period,
            "target_amount": 0, "achieved_amount": achieved,
            "progress_pct": 0, "remaining": 0, "notes": None, "no_target": True,
        }
    return await _serialize(db, t)


@router.post("", status_code=201)
async def create_target(
    payload: TargetIn,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(_director),
):
    user = await db.get(User, payload.user_id)
    if not user:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "User not found")
    existing = await db.scalar(
        select(SalesTarget).where(
            SalesTarget.user_id == payload.user_id,
            SalesTarget.period == payload.period,
        )
    )
    if existing:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Target already exists for {user.full_name} in {payload.period}. Edit it instead.",
        )
    t = SalesTarget(
        user_id=payload.user_id, period=payload.period,
        target_amount=payload.target_amount, notes=payload.notes, set_by=me.id,
    )
    db.add(t)
    await db.flush()
    return await _serialize(db, t)


@router.patch("/{target_id}")
async def update_target(
    target_id: UUID,
    payload: TargetPatch,
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_director),
):
    t = await db.get(SalesTarget, target_id)
    if not t:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(t, k, v)
    return await _serialize(db, t)


@router.delete("/{target_id}", status_code=204)
async def delete_target(
    target_id: UUID,
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_director),
):
    t = await db.get(SalesTarget, target_id)
    if not t:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    await db.delete(t)
    return None

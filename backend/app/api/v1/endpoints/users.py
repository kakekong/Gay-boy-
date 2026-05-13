"""Employee directory endpoints (HR + Director only)."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.permissions import Role, require
from app.models.crm import Activity, Customer
from app.models.quotation import Quotation
from app.models.tag import Tag, UserTagLink
from app.models.user import User
from app.schemas.auth import UserOut

router = APIRouter()

_hr_or_director = require(Role.HR, Role.DIRECTOR)


@router.get("")
async def list_employees(
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_hr_or_director),
    role: str | None = None,
    q: str | None = None,
    active_only: bool = True,
):
    stmt = select(User).order_by(User.full_name.asc())
    if active_only:
        stmt = stmt.where(User.is_active.is_(True))
    if role:
        stmt = stmt.where(User.role == role)
    if q:
        like = f"%{q}%"
        stmt = stmt.where((User.full_name.ilike(like)) | (User.email.ilike(like)))
    rows = (await db.scalars(stmt)).all()

    # Bulk load tags for all users in one query
    tag_map: dict[str, list[dict]] = {}
    if rows:
        user_ids = [r.id for r in rows]
        result = await db.execute(
            select(UserTagLink.user_id, Tag)
            .join(Tag, Tag.id == UserTagLink.tag_id)
            .where(UserTagLink.user_id.in_(user_ids))
        )
        for uid, tag in result.all():
            tag_map.setdefault(str(uid), []).append({
                "id": str(tag.id), "name": tag.name,
                "color": tag.color, "description": tag.description,
            })

    return [
        {
            "id": str(r.id),
            "email": r.email,
            "full_name": r.full_name,
            "role": r.role,
            "phone": r.phone,
            "is_active": r.is_active,
            "tags": tag_map.get(str(r.id), []),
        }
        for r in rows
    ]


@router.get("/{user_id}", response_model=UserOut)
async def get_employee(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    # employees can always read their own profile; HR + Director can read anyone
    if me.id != user_id and Role(me.role) not in (Role.HR, Role.DIRECTOR):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Out of scope")
    obj = await db.get(User, user_id)
    if not obj:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")
    return obj


@router.get("/{user_id}/stats")
async def employee_stats(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_hr_or_director),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND)

    customers_count = await db.scalar(
        select(func.count(Customer.id)).where(
            Customer.sales_pic_id == user_id, Customer.is_deleted.is_(False)
        )
    ) or 0
    quotations_count = await db.scalar(
        select(func.count(Quotation.id)).where(Quotation.sales_pic_id == user_id)
    ) or 0
    won = await db.scalar(
        select(func.count(Quotation.id)).where(
            Quotation.sales_pic_id == user_id, Quotation.status == "won"
        )
    ) or 0
    lost = await db.scalar(
        select(func.count(Quotation.id)).where(
            Quotation.sales_pic_id == user_id, Quotation.status == "lost"
        )
    ) or 0
    pipeline_value = await db.scalar(
        select(func.coalesce(func.sum(Quotation.total), 0)).where(
            Quotation.sales_pic_id == user_id,
            Quotation.status.in_(["draft", "pending_approval", "approved", "sent"]),
        )
    )
    won_revenue = await db.scalar(
        select(func.coalesce(func.sum(Quotation.total), 0)).where(
            Quotation.sales_pic_id == user_id, Quotation.status == "won"
        )
    )
    activities_30d = await db.scalar(
        select(func.count(Activity.id)).where(
            Activity.user_id == user_id,
            Activity.occurred_at >= datetime.now(UTC) - timedelta(days=30),
        )
    ) or 0
    decided = won + lost
    return {
        "user_id": str(user_id),
        "full_name": user.full_name,
        "role": user.role,
        "customers": customers_count,
        "quotations": quotations_count,
        "won": won,
        "lost": lost,
        "win_rate": round((won / decided), 3) if decided else 0,
        "pipeline_value": float(pipeline_value or 0),
        "won_revenue": float(won_revenue or 0),
        "activities_30d": activities_30d,
    }


@router.get("/{user_id}/quotations")
async def employee_quotations(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_hr_or_director),
    status_eq: str | None = None,
    limit: int = 200,
):
    stmt = (
        select(Quotation, Customer)
        .join(Customer, Quotation.customer_id == Customer.id)
        .where(Quotation.sales_pic_id == user_id)
        .order_by(Quotation.created_at.desc())
        .limit(limit)
    )
    if status_eq:
        stmt = stmt.where(Quotation.status == status_eq)
    out = []
    for q, c in (await db.execute(stmt)).all():
        out.append({
            "id": str(q.id),
            "number": q.number,
            "customer_id": str(c.id),
            "customer_name": c.company_name,
            "variant": q.variant,
            "status": q.status,
            "discount_pct": float(q.discount_pct or 0),
            "total": float(q.total or 0),
            "valid_until": q.valid_until,
            "created_at": q.created_at,
        })
    return out


@router.get("/{user_id}/customers")
async def employee_customers(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_hr_or_director),
    limit: int = 200,
):
    rows = (await db.scalars(
        select(Customer).where(
            Customer.sales_pic_id == user_id, Customer.is_deleted.is_(False)
        ).order_by(Customer.company_name.asc()).limit(limit)
    )).all()
    return [
        {
            "id": str(c.id),
            "company_name": c.company_name,
            "industry": c.industry,
            "stage": c.stage,
            "lifetime_value": float(c.lifetime_value or 0),
        }
        for c in rows
    ]


@router.get("/{user_id}/activities")
async def employee_activities(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_hr_or_director),
    limit: int = 100,
):
    stmt = (
        select(Activity, Customer)
        .join(Customer, Activity.customer_id == Customer.id)
        .where(Activity.user_id == user_id)
        .order_by(Activity.occurred_at.desc())
        .limit(limit)
    )
    out = []
    for a, c in (await db.execute(stmt)).all():
        out.append({
            "id": str(a.id),
            "type": a.type,
            "direction": a.direction,
            "occurred_at": a.occurred_at,
            "notes": a.notes,
            "customer_id": str(c.id),
            "customer_name": c.company_name,
        })
    return out

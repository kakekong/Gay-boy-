from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.approval import (
    decide,
    evaluate_discount,
    request_approval,
)
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.permissions import Role, can_approve_quotation
from app.models.approval import ApprovalRequest, ApprovalStatus
from app.models.quotation import Quotation, QuotationItem
from app.models.user import User
from app.schemas.quotation import QuotationCreate, QuotationDecide, QuotationOut
from app.services.numbering import next_quotation_number

router = APIRouter()


def _recalc(q: Quotation, items: list[QuotationItem]) -> None:
    subtotal = sum(float(it.qty) * float(it.unit_price) for it in items)
    discount_amount = subtotal * float(q.discount_pct) / 100.0
    after_discount = subtotal - discount_amount
    tax = after_discount * float(q.tax_pct) / 100.0
    q.subtotal = subtotal
    q.discount_amount = discount_amount
    q.total = after_discount + tax
    for it in items:
        it.line_total = float(it.qty) * float(it.unit_price)


@router.post("", response_model=QuotationOut, status_code=201)
async def create_quotation(
    payload: QuotationCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    number = await next_quotation_number(db)
    q = Quotation(
        number=number,
        customer_id=payload.customer_id,
        variant=payload.variant,
        sales_pic_id=user.id,
        discount_pct=payload.discount_pct,
        tax_pct=payload.tax_pct,
        valid_until=payload.valid_until,
        notes=payload.notes,
        status="draft",
        created_by=user.id, updated_by=user.id,
    )
    db.add(q)
    await db.flush()
    items = [
        QuotationItem(quotation_id=q.id, **i.model_dump())
        for i in payload.items
    ]
    db.add_all(items)
    _recalc(q, items)
    await db.flush()
    return await _load(q.id, db)


@router.post("/{q_id}/submit", response_model=QuotationOut)
async def submit_quotation(
    q_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = await db.get(Quotation, q_id)
    if not q:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if q.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only draft can be submitted")

    rule = evaluate_discount(float(q.discount_pct))
    if rule.required_role is None:
        q.status = "approved"
    else:
        q.status = "pending_approval"
        await request_approval(
            db,
            target_type="quotation",
            target_id=q.id,
            requested_by=user.id,
            required_role=rule.required_role,
            reason=rule.reason,
            payload={"discount_pct": float(q.discount_pct), "total": float(q.total)},
        )
    await db.flush()
    return await _load(q.id, db)


@router.post("/{q_id}/approve", response_model=QuotationOut)
async def approve_quotation(q_id: UUID, payload: QuotationDecide,
                            db: AsyncSession = Depends(get_db),
                            user: User = Depends(get_current_user)):
    if not can_approve_quotation(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN)
    req = await db.scalar(
        select(ApprovalRequest).where(
            ApprovalRequest.target_type == "quotation",
            ApprovalRequest.target_id == q_id,
            ApprovalRequest.status == ApprovalStatus.PENDING.value,
        )
    )
    if not req:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No pending approval")
    await decide(db, request_id=req.id, decider_id=user.id,
                 decider_role=Role(user.role), approve=True, notes=payload.notes)
    q = await db.get(Quotation, q_id)
    q.status = "approved"
    return await _load(q.id, db)


@router.post("/{q_id}/reject", response_model=QuotationOut)
async def reject_quotation(q_id: UUID, payload: QuotationDecide,
                           db: AsyncSession = Depends(get_db),
                           user: User = Depends(get_current_user)):
    if not can_approve_quotation(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN)
    req = await db.scalar(
        select(ApprovalRequest).where(
            ApprovalRequest.target_type == "quotation",
            ApprovalRequest.target_id == q_id,
            ApprovalRequest.status == ApprovalStatus.PENDING.value,
        )
    )
    if not req:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No pending approval")
    await decide(db, request_id=req.id, decider_id=user.id,
                 decider_role=Role(user.role), approve=False, notes=payload.notes)
    q = await db.get(Quotation, q_id)
    q.status = "rejected"
    return await _load(q.id, db)


@router.post("/{q_id}/won", response_model=QuotationOut)
async def mark_won(q_id: UUID, db: AsyncSession = Depends(get_db),
                   user: User = Depends(get_current_user)):
    q = await db.get(Quotation, q_id)
    if not q:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    q.status = "won"
    # Auto-create project (deferred to service)
    from app.services.project_factory import create_project_from_quotation
    await create_project_from_quotation(db, q, user)
    return await _load(q.id, db)


@router.post("/{q_id}/lost", response_model=QuotationOut)
async def mark_lost(q_id: UUID, reason: str,
                    db: AsyncSession = Depends(get_db),
                    user: User = Depends(get_current_user)):
    q = await db.get(Quotation, q_id)
    if not q:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    q.status = "lost"
    q.notes = (q.notes or "") + f"\n[lost @ {datetime.now(UTC).isoformat()}] {reason}"
    return await _load(q.id, db)


async def _load(q_id: UUID, db: AsyncSession) -> Quotation:
    return await db.scalar(
        select(Quotation)
        .options(selectinload(Quotation.items))
        .where(Quotation.id == q_id)
    )


@router.get("", response_model=list[QuotationOut])
async def list_quotations(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    status_eq: str | None = None,
    customer_id: UUID | None = None,
    limit: int = 50,
):
    stmt = (
        select(Quotation)
        .options(selectinload(Quotation.items))
        .order_by(Quotation.created_at.desc())
        .limit(limit)
    )
    if Role(user.role) == Role.SALES:
        stmt = stmt.where(Quotation.sales_pic_id == user.id)
    if status_eq:
        stmt = stmt.where(Quotation.status == status_eq)
    if customer_id:
        stmt = stmt.where(Quotation.customer_id == customer_id)
    rows = (await db.scalars(stmt)).all()
    return [QuotationOut.model_validate(r) for r in rows]


@router.get("/stats")
async def stats(db: AsyncSession = Depends(get_db),
                user: User = Depends(get_current_user)):
    total = await db.scalar(select(func.count(Quotation.id)))
    return {"total": total or 0}


@router.get("/{q_id}", response_model=QuotationOut)
async def get_quotation(
    q_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = await _load(q_id, db)
    if not q:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quotation not found")
    if Role(user.role) == Role.SALES and q.sales_pic_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Out of scope")
    return q

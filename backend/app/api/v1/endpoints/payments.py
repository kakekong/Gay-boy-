"""Customer-payment verification flow.

Customer submits a payment claim from the customer portal (amount, date,
method, reference, optional proof attachment). Finance / Director sees
pending claims and verifies or rejects them. Verification creates a real
Payment row and recomputes the invoice's status (issued → partial → paid).
"""

from datetime import UTC, date as date_t, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record as audit_record
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.permissions import Role, require
from app.models.finance import Invoice, Payment
from app.models.payment_claim import PaymentClaim
from app.models.user import User

router = APIRouter()
_finance = require(Role.ADMIN, Role.FINANCE, Role.MANAGER, Role.DIRECTOR)


class ClaimIn(BaseModel):
    invoice_id: UUID
    amount: float
    paid_at: date_t | None = None
    method: str | None = None
    reference: str | None = None
    notes: str | None = None
    attachment_id: UUID | None = None


class DecisionIn(BaseModel):
    notes: str | None = None


async def _serialize(db: AsyncSession, c: PaymentClaim) -> dict:
    inv = await db.get(Invoice, c.invoice_id)
    user = await db.get(User, c.customer_user_id) if c.customer_user_id else None
    verifier = await db.get(User, c.verified_by) if c.verified_by else None
    return {
        "id": str(c.id),
        "invoice_id": str(c.invoice_id),
        "invoice_number": inv.number if inv else None,
        "invoice_total": float(inv.total or 0) if inv else None,
        "amount": float(c.amount),
        "paid_at": c.paid_at,
        "method": c.method,
        "reference": c.reference,
        "notes": c.notes,
        "attachment_id": str(c.attachment_id) if c.attachment_id else None,
        "status": c.status,
        "created_at": c.created_at,
        "customer_user_name": user.full_name if user else None,
        "verified_by": str(c.verified_by) if c.verified_by else None,
        "verified_by_name": verifier.full_name if verifier else None,
        "verified_at": c.verified_at,
        "decision_notes": c.decision_notes,
    }


# ─── Customer-side (from the portal) ─────────────────────────────────────────

@router.post("/claims", status_code=201)
async def submit_claim(
    payload: ClaimIn,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    """Submit a payment claim. Customer or internal staff may call this."""
    inv = await db.get(Invoice, payload.invoice_id)
    if not inv:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found")
    # Scope check for customer accounts
    if Role(me.role) == Role.CUSTOMER:
        if not me.linked_customer_id or me.linked_customer_id != inv.customer_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your invoice")
    if payload.amount <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Amount must be positive")
    c = PaymentClaim(
        invoice_id=payload.invoice_id,
        customer_user_id=me.id,
        amount=payload.amount,
        paid_at=payload.paid_at,
        method=payload.method,
        reference=payload.reference,
        notes=payload.notes,
        attachment_id=payload.attachment_id,
        status="pending",
    )
    db.add(c)
    await db.flush()
    return await _serialize(db, c)


@router.get("/claims/mine")
async def my_claims(
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    """Claims the current user submitted (or, for finance, all)."""
    if Role(me.role) in (Role.ADMIN, Role.FINANCE, Role.MANAGER, Role.DIRECTOR):
        rows = (await db.scalars(
            select(PaymentClaim).order_by(PaymentClaim.created_at.desc())
        )).all()
    else:
        rows = (await db.scalars(
            select(PaymentClaim)
            .where(PaymentClaim.customer_user_id == me.id)
            .order_by(PaymentClaim.created_at.desc())
        )).all()
    return [await _serialize(db, c) for c in rows]


# ─── Finance verification ────────────────────────────────────────────────────

@router.get("/claims")
async def list_claims(
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_finance),
    status_eq: str | None = None,
    invoice_id: UUID | None = None,
):
    stmt = select(PaymentClaim).order_by(PaymentClaim.created_at.desc())
    if status_eq:
        stmt = stmt.where(PaymentClaim.status == status_eq)
    if invoice_id:
        stmt = stmt.where(PaymentClaim.invoice_id == invoice_id)
    rows = (await db.scalars(stmt)).all()
    return [await _serialize(db, c) for c in rows]


async def _recompute_invoice_status(db: AsyncSession, invoice_id: UUID) -> str:
    """Sum verified payments vs invoice total → update invoice.status."""
    inv = await db.get(Invoice, invoice_id)
    if not inv:
        return ""
    paid_sum = await db.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0))
        .where(Payment.invoice_id == invoice_id)
    ) or 0
    total = float(inv.total or 0)
    if total <= 0:
        return inv.status
    if paid_sum >= total - 0.01:
        inv.status = "paid"
    elif paid_sum > 0:
        inv.status = "partial"
    return inv.status


@router.post("/claims/{claim_id}/verify")
async def verify_claim(
    claim_id: UUID,
    payload: DecisionIn,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(_finance),
):
    c = await db.get(PaymentClaim, claim_id)
    if not c:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if c.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Claim is already {c.status}")
    # Create a real Payment row
    payment = Payment(
        invoice_id=c.invoice_id,
        amount=c.amount,
        paid_at=datetime.combine(c.paid_at, datetime.min.time()).replace(tzinfo=UTC) if c.paid_at else datetime.now(UTC),
        method=c.method,
        reference=c.reference,
        notes=f"Verified from claim {c.id}. {payload.notes or ''}".strip(),
    )
    db.add(payment)
    await db.flush()

    # Post the receipt to the ledger: cash up, receivable down. Attribute it
    # to the customer's sales rep so it lands on their financial report.
    inv = await db.get(Invoice, c.invoice_id)
    sales_pic_id = None
    if inv:
        from app.models.crm import Customer
        cust = await db.get(Customer, inv.customer_id)
        sales_pic_id = cust.sales_pic_id if cust else None
    from app.services.ledger import post_payment
    await post_payment(
        db,
        amount=float(c.amount),
        entry_date=c.paid_at or datetime.now(UTC).date(),
        invoice_number=inv.number if inv else None,
        customer_id=inv.customer_id if inv else None,
        sales_pic_id=sales_pic_id,
        payment_id=payment.id,
        created_by=me.id,
    )

    c.status = "verified"
    c.verified_by = me.id
    c.verified_at = datetime.now(UTC)
    c.decision_notes = payload.notes
    new_inv_status = await _recompute_invoice_status(db, c.invoice_id)

    await audit_record(
        db, actor=me, action="verify_payment", entity="invoice",
        entity_id=c.invoice_id,
        after={"claim_id": str(c.id), "amount": float(c.amount),
               "new_status": new_inv_status},
    )
    return await _serialize(db, c)


@router.post("/claims/{claim_id}/reject")
async def reject_claim(
    claim_id: UUID,
    payload: DecisionIn,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(_finance),
):
    c = await db.get(PaymentClaim, claim_id)
    if not c:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if c.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Claim is already {c.status}")
    c.status = "rejected"
    c.verified_by = me.id
    c.verified_at = datetime.now(UTC)
    c.decision_notes = payload.notes
    await audit_record(
        db, actor=me, action="reject_payment", entity="invoice",
        entity_id=c.invoice_id,
        after={"claim_id": str(c.id), "notes": payload.notes},
    )
    return await _serialize(db, c)


@router.get("/claims/counts")
async def counts(
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_finance),
):
    pending = await db.scalar(
        select(func.count(PaymentClaim.id)).where(PaymentClaim.status == "pending")
    ) or 0
    return {"pending": pending}

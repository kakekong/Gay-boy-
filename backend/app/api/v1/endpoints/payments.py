"""Recording customer payments.

Finance records a payment against an invoice — amount, date, method,
reference, optional proof — and that creates the Payment row, posts the
receipt to the ledger, recomputes the invoice status (issued → partial →
paid) and, when the invoice lands fully paid, moves the project on.

Customers no longer submit anything here. They used to claim a payment from
the portal for finance to verify, which meant the record of money arriving
started with somebody outside the company saying it had. It is finance who
watches the bank account, so it is finance who writes it down: the entry and
the verification are one act, by the desk that can actually see the money.

The claim table and the verify / reject endpoints stay, for two reasons —
claims submitted before this change still have to be settled rather than
stranded, and every recorded payment still writes one, so the audit trail
reads the same all the way back.
"""

from datetime import UTC, date as date_t, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record as audit_record
from app.core.db import get_db
from app.core.permissions import Role, require
from app.models.finance import Invoice, OUTSTANDING_INVOICE_STATUSES, Payment
from app.models.payment_claim import PaymentClaim
from app.models.user import User

router = APIRouter()
# Admin is out of the finance verification loop — projects/ops/inventory
# only. Finance verifies payment claims; manager sees; director backstop.
_finance = require(Role.FINANCE, Role.MANAGER, Role.DIRECTOR)


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
        # Who wrote this down. On anything recorded since payments became
        # finance's own entry that is a member of staff; on a claim left over
        # from the portal days it is the customer, and `source` says which so
        # the screen can label it honestly rather than calling both the same.
        "submitted_by_name": user.full_name if user else None,
        "source": ("portal" if user and Role(user.role) == Role.CUSTOMER
                   else "finance"),
        # Kept for older clients that still read this key.
        "customer_user_name": user.full_name if user else None,
        "verified_by": str(c.verified_by) if c.verified_by else None,
        "verified_by_name": verifier.full_name if verifier else None,
        "verified_at": c.verified_at,
        "decision_notes": c.decision_notes,
    }


# ─── Finance's own record ────────────────────────────────────────────────────
#
# `POST /claims` and `GET /claims/mine` used to live here: the customer told
# us they had paid, and finance agreed or disagreed. Both are gone. The money
# arriving is something only finance can see, so finance is who writes it
# down — `POST /manual`, below, in one step.

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


@router.get("/open-invoices")
async def open_invoices(
    db: AsyncSession = Depends(get_db),
    _me: User = Depends(_finance),
):
    """Invoices that can still receive a payment — the picker for the
    manual-payment form. Returns outstanding = total - verified payments."""
    from app.models.crm import Customer

    rows = (await db.scalars(
        select(Invoice).where(
            Invoice.status.in_(OUTSTANDING_INVOICE_STATUSES)
        ).order_by(Invoice.issue_date.asc().nullslast())
    )).all()
    if not rows:
        return []
    inv_ids = [r.id for r in rows]
    paid_by_inv: dict = {}
    for row in (await db.execute(
        select(Payment.invoice_id, func.coalesce(func.sum(Payment.amount), 0))
        .where(Payment.invoice_id.in_(inv_ids))
        .group_by(Payment.invoice_id)
    )).all():
        paid_by_inv[row[0]] = float(row[1] or 0)
    cust_ids = {r.customer_id for r in rows if r.customer_id}
    cust_names: dict = {}
    if cust_ids:
        for c in (await db.scalars(
            select(Customer).where(Customer.id.in_(cust_ids))
        )).all():
            cust_names[c.id] = c.company_name
    out = []
    for inv in rows:
        total = float(inv.total or 0)
        paid = paid_by_inv.get(inv.id, 0.0)
        outstanding = max(0.0, total - paid)
        if outstanding <= 0:
            continue
        out.append({
            "id": str(inv.id), "number": inv.number, "type": inv.type,
            "customer_name": cust_names.get(inv.customer_id),
            "total": total, "paid": paid, "outstanding": outstanding,
            "due_date": inv.due_date,
        })
    return out


class ManualPaymentIn(BaseModel):
    invoice_id: UUID
    amount: float
    paid_at: date_t | None = None
    method: str | None = None
    reference: str | None = None
    notes: str | None = None
    attachment_id: UUID | None = None


@router.post("/manual", status_code=201)
async def record_manual_payment(
    payload: ManualPaymentIn,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(_finance),
):
    """Finance writes down a payment that has arrived. This is the way in.

    One step, because the two steps were only ever separate to give the
    customer somewhere to put a claim. Finance is looking at the bank
    statement; asking them to record what they can see and then agree with
    themselves is ceremony. So this creates the claim already verified — the
    audit trail reads the same shape as it always did — plus the Payment row
    and the ledger post, recomputes the invoice status, and advances the
    project when the invoice lands fully paid.
    """
    inv = await db.get(Invoice, payload.invoice_id)
    if not inv:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found")
    if payload.amount <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Amount must be positive")
    if inv.status in ("paid", "rejected", "draft", "pending_finance"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Invoice is '{inv.status}' — payments can only be recorded on "
            "an issued/approved invoice that isn't fully paid yet.",
        )

    now = datetime.now(UTC)
    c = PaymentClaim(
        invoice_id=payload.invoice_id,
        customer_user_id=me.id,
        amount=payload.amount,
        paid_at=payload.paid_at,
        method=payload.method,
        reference=payload.reference,
        notes=(f"[recorded by finance: {me.full_name}] "
               + (payload.notes or "")).strip(),
        attachment_id=payload.attachment_id,
        status="verified",
        verified_by=me.id,
        verified_at=now,
        decision_notes=f"Recorded by {me.full_name} against the bank record.",
    )
    db.add(c)
    payment = Payment(
        invoice_id=payload.invoice_id,
        amount=payload.amount,
        paid_at=(datetime.combine(payload.paid_at, datetime.min.time()).replace(tzinfo=UTC)
                 if payload.paid_at else now),
        method=payload.method,
        reference=payload.reference,
        notes=f"Manual entry by {me.full_name}. {payload.notes or ''}".strip(),
    )
    db.add(payment)
    await db.flush()

    # Ledger: cash up, receivable down — attributed to the customer's rep.
    sales_pic_id = None
    if inv.customer_id:
        from app.models.crm import Customer
        cust = await db.get(Customer, inv.customer_id)
        sales_pic_id = cust.sales_pic_id if cust else None
    from app.services.ledger import post_payment
    await post_payment(
        db,
        amount=float(payload.amount),
        entry_date=payload.paid_at or now.date(),
        invoice_number=inv.number,
        customer_id=inv.customer_id,
        sales_pic_id=sales_pic_id,
        payment_id=payment.id,
        created_by=me.id,
    )

    new_inv_status = await _recompute_invoice_status(db, payload.invoice_id)
    # A deposit invoice paid in full is what starts the job it paid for.
    # No-op for every other invoice, so it is safe to ask after any payment.
    if new_inv_status == "paid":
        from app.api.v1.endpoints.customer_pos import settle_dp_po_for_invoice
        await settle_dp_po_for_invoice(db, inv, actor=me)
    # …but a *deposit* invoice never does. Paying a deposit is what starts
    # a job, not what finishes it, and the settlement above has just linked
    # this invoice to the project it created — so without this the deposit
    # would open the job and close it in the same breath.
    if new_inv_status == "paid" and inv.project_id and inv.type != "dp":
        from app.models.operation import Project, advance_project_status
        project = await db.get(Project, inv.project_id)
        if project:
            advance_project_status(project, "paid")
            advance_project_status(project, "closed")

    await audit_record(
        db, actor=me, action="manual_payment", entity="invoice",
        entity_id=payload.invoice_id,
        after={"claim_id": str(c.id), "amount": float(payload.amount),
               "new_status": new_inv_status},
    )
    return await _serialize(db, c)


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
    # Same invoice-state guard the manual path enforces — verifying against a
    # draft / pending / already-paid invoice still posted to the ledger and
    # could overpay the invoice.
    _inv = await db.get(Invoice, c.invoice_id)
    if _inv is not None and _inv.status in ("paid", "rejected", "draft", "pending_finance"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Invoice is '{_inv.status}' — payments can only be verified on an "
            "approved, unpaid invoice.",
        )
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

    # A deposit invoice paid in full starts the job it paid for — the same
    # settlement the manual path runs, so a customer paying through the
    # portal reaches the same place as one who transfers.
    if new_inv_status == "paid" and inv:
        from app.api.v1.endpoints.customer_pos import settle_dp_po_for_invoice
        await settle_dp_po_for_invoice(db, inv, actor=me)

    # When the invoice is fully paid, advance the project to 'paid', then
    # auto-close it — payment is the last real-world signal in the pipeline.
    # …but a *deposit* invoice never does. Paying a deposit is what starts
    # a job, not what finishes it, and the settlement above has just linked
    # this invoice to the project it created — so without this the deposit
    # would open the job and close it in the same breath.
    if new_inv_status == "paid" and inv and inv.project_id and inv.type != "dp":
        from app.models.operation import Project, advance_project_status
        project = await db.get(Project, inv.project_id)
        if project:
            advance_project_status(project, "paid")
            advance_project_status(project, "closed")

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

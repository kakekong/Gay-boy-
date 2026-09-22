"""Commission claims — a rep's share of a job the customer has actually paid.

One rule shapes every endpoint here: **the money has to have arrived first.**
Not the order being won, not the goods being delivered, not the invoice being
issued — the payment being in the bank. A commission paid against an
outstanding invoice is a payout on a promise, and the promise is the part that
sometimes does not arrive.

That gate is checked on the server when the claim is filed, against the same
`SUM(payments.amount)` the AR screens read, so a reversed payment closes the
door again. It is checked again on the way to approval, because a claim can
sit in the queue for a week and the world can move underneath it.

The figures are frozen onto the claim when it is filed — what had been
collected, the rate, the amount — rather than recomputed on read. Three facts
about a decision, not a live query: re-deriving them would quietly restate an
approved payout the next time a payment is reversed or an order re-priced.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record as audit_record
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.permissions import Role, require
from app.models.commission import (
    CommissionClaim, DEFAULT_RATE_PCT, LIVE_STATUSES,
)
from app.models.crm import Customer
from app.models.operation import Project
from app.models.user import User
from app.services.commission import claim_out, collected_for_projects

router = APIRouter()

# Filing one is the rep's own act, or somebody doing it for them. Deciding it
# is the director's, like every other figure that leaves the company.
_MAY_FILE = (Role.SALES, Role.MANAGER, Role.DIRECTOR)
_DECIDER = require(Role.DIRECTOR)


class ClaimIn(BaseModel):
    project_id: UUID
    notes: str | None = None


class DecisionIn(BaseModel):
    notes: str | None = None
    # The director can settle on a different percentage than the standard one
    # — that is what "baseline 2%" means — and the amount is recomputed from
    # the basis that was frozen when the claim was filed.
    rate_pct: float | None = None


async def _beneficiary_for(db: AsyncSession, project: Project) -> UUID | None:
    """Whose commission a job is. The rep who owns the customer."""
    cust = await db.get(Customer, project.customer_id) if project.customer_id else None
    return cust.sales_pic_id if cust else None


async def _serialize(db: AsyncSession, c: CommissionClaim) -> dict:
    project = await db.get(Project, c.project_id)
    who = await db.get(User, c.beneficiary_id) if c.beneficiary_id else None
    by = await db.get(User, c.claimed_by) if c.claimed_by else None
    decider = await db.get(User, c.decided_by) if c.decided_by else None
    return {
        **(claim_out(c) or {}),
        "project_id": str(c.project_id),
        "project_code": project.code if project else None,
        "project_status": project.status if project else None,
        "beneficiary_id": str(c.beneficiary_id) if c.beneficiary_id else None,
        "beneficiary_name": who.full_name if who else None,
        "claimed_by_name": by.full_name if by else None,
        "decided_by_name": decider.full_name if decider else None,
    }


@router.get("")
async def list_claims(
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
    user_id: UUID | None = None,
    status_eq: str | None = None,
):
    """Claims, optionally for one person or one state.

    A rep sees their own and nobody else's — a commission is pay, and pay is
    not something colleagues browse.
    """
    role = Role(me.role)
    stmt = select(CommissionClaim).order_by(CommissionClaim.created_at.desc())
    if role in (Role.DIRECTOR, Role.MANAGER, Role.FINANCE, Role.HR):
        if user_id:
            stmt = stmt.where(CommissionClaim.beneficiary_id == user_id)
    else:
        stmt = stmt.where(CommissionClaim.beneficiary_id == me.id)
    if status_eq:
        stmt = stmt.where(CommissionClaim.status == status_eq)
    rows = (await db.scalars(stmt)).all()
    return [await _serialize(db, c) for c in rows]


@router.post("", status_code=201)
async def file_claim(
    payload: ClaimIn,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    """Claim the commission on a job the customer has settled."""
    role = Role(me.role)
    if role not in _MAY_FILE:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Commission is claimed by the rep whose customer it is, or by "
            "management on their behalf.",
        )
    project = await db.get(Project, payload.project_id)
    if not project or project.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

    beneficiary = await _beneficiary_for(db, project)
    if beneficiary is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{project.code} has no sales rep on its customer, so there is "
            "nobody to pay. Set the account owner first.",
        )
    # Sales may only claim their own. Management may file on somebody's
    # behalf, which is what the employee page does.
    if role is Role.SALES and beneficiary != me.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "That job belongs to another rep's customer.",
        )

    existing = await db.scalar(
        select(CommissionClaim).where(
            CommissionClaim.project_id == project.id,
            CommissionClaim.status.in_(LIVE_STATUSES),
        )
    )
    if existing:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"A commission claim on {project.code} already exists and is "
            f"'{existing.status}'.",
        )

    money = (await collected_for_projects(db, [project.id])).get(project.id) or {}
    if not money.get("invoices"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{project.code} has not been invoiced yet, so nothing has been "
            "collected to claim against.",
        )
    if not money.get("paid_in_full"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{project.code} is not paid in full — "
            f"Rp {money.get('outstanding', 0):,.0f} is still outstanding. "
            "Commission is claimable once finance has the money."
            .replace(",", "."),
        )

    basis = float(money.get("collected") or 0)
    rate = DEFAULT_RATE_PCT
    claim = CommissionClaim(
        project_id=project.id,
        beneficiary_id=beneficiary,
        claimed_by=me.id,
        status="pending",
        rate_pct=rate,
        basis_amount=basis,
        amount=round(basis * rate / 100.0, 2),
        notes=(payload.notes or "").strip() or None,
    )
    db.add(claim)
    await db.flush()
    await audit_record(
        db, actor=me, action="claim_commission", entity="project",
        entity_id=project.id,
        after={"claim_id": str(claim.id), "beneficiary": str(beneficiary),
               "basis": basis, "rate_pct": rate, "amount": float(claim.amount)},
    )
    return await _serialize(db, claim)


@router.post("/{claim_id}/approve")
async def approve_claim(
    claim_id: UUID,
    payload: DecisionIn,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(_DECIDER),
):
    """Agree the figure. The rate may be settled at something other than the
    baseline, and the amount follows from the basis frozen at claim time."""
    c = await db.get(CommissionClaim, claim_id)
    if not c:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Claim not found")
    if c.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"This claim is already '{c.status}'.")

    # The world can move while a claim sits in the queue — a payment reversed
    # a week later is exactly the case — so the gate is checked again here
    # rather than trusted from the moment it was filed.
    money = (await collected_for_projects(db, [c.project_id])).get(c.project_id) or {}
    if not money.get("paid_in_full"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "The job is no longer paid in full — a payment has been reversed "
            "or a further invoice raised since this was claimed. Settle that "
            "first; the claim can be approved once the money is in again.",
        )

    if payload.rate_pct is not None:
        if payload.rate_pct <= 0 or payload.rate_pct > 100:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "A commission rate is a percentage above zero.")
        c.rate_pct = payload.rate_pct
    c.amount = round(float(c.basis_amount or 0) * float(c.rate_pct or 0) / 100.0, 2)
    c.status = "approved"
    c.decided_by = me.id
    c.decided_at = datetime.now(UTC)
    c.decision_notes = (payload.notes or "").strip() or None
    await audit_record(
        db, actor=me, action="approve_commission", entity="project",
        entity_id=c.project_id,
        after={"claim_id": str(c.id), "rate_pct": float(c.rate_pct),
               "amount": float(c.amount)},
    )
    return await _serialize(db, c)


@router.post("/{claim_id}/reject")
async def reject_claim(
    claim_id: UUID,
    payload: DecisionIn,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(_DECIDER),
):
    """Refuse it, with a reason. The rep can put the case again — a rejected
    claim does not block a new one."""
    c = await db.get(CommissionClaim, claim_id)
    if not c:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Claim not found")
    if c.status not in ("pending", "approved"):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"This claim is '{c.status}'.")
    reason = (payload.notes or "").strip()
    if not reason:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Say why it is refused — it is somebody's pay.")
    c.status = "rejected"
    c.decided_by = me.id
    c.decided_at = datetime.now(UTC)
    c.decision_notes = reason
    await audit_record(
        db, actor=me, action="reject_commission", entity="project",
        entity_id=c.project_id,
        after={"claim_id": str(c.id), "reason": reason},
    )
    return await _serialize(db, c)


@router.post("/{claim_id}/mark-paid")
async def mark_paid(
    claim_id: UUID,
    payload: DecisionIn,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(require(Role.FINANCE, Role.DIRECTOR)),
):
    """It has gone out with payroll. Finance's to say, because finance is who
    can see it leave."""
    c = await db.get(CommissionClaim, claim_id)
    if not c:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Claim not found")
    if c.status != "approved":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Only an approved claim can be marked paid — this one is "
            f"'{c.status}'.",
        )
    c.status = "paid"
    c.paid_at = datetime.now(UTC)
    if (payload.notes or "").strip():
        c.decision_notes = ((c.decision_notes or "") + "\n"
                            + payload.notes.strip()).strip()
    await audit_record(
        db, actor=me, action="pay_commission", entity="project",
        entity_id=c.project_id,
        after={"claim_id": str(c.id), "amount": float(c.amount or 0)},
    )
    return await _serialize(db, c)

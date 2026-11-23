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
from app.core.permissions import Role, require, require_min
from app.models.commission import (
    DEFAULT_RATE_PCT,
    LIVE_STATUSES,
    CommissionClaim,
)
from app.models.crm import Customer
from app.models.operation import Project
from app.models.user import User
from app.services.commission import (
    claim_out,
    claims_for_projects,
    collected_for_projects,
)

# Staff only — portal (customer/supplier) logins never reach this.
router = APIRouter(dependencies=[Depends(require_min(Role.SALES))])

# Filing one is the rep's own act, or somebody doing it for them. Deciding it
# is finance's — a claim goes to their queue, they check the money is in and
# pay it — and the director's, who may also settle a different rate.
_MAY_FILE = (Role.SALES, Role.MANAGER, Role.DIRECTOR)
_DECIDER = require(Role.FINANCE, Role.DIRECTOR)
# Where a paid commission is booked: Beban Komisi Penjualan Sales.
COMMISSION_EXPENSE = "6000-02"


class PayIn(BaseModel):
    notes: str | None = None
    # The bank or cash account it was paid from, and when.
    cash_account_no: str | None = None
    paid_on: str | None = None


class ClaimIn(BaseModel):
    project_id: UUID
    notes: str | None = None


class DecisionIn(BaseModel):
    notes: str | None = None
    # The director can settle on a different percentage than the standard one
    # — that is what "baseline 2%" means — and the amount is recomputed from
    # the basis that was frozen when the claim was filed.
    rate_pct: float | None = None
    # The real selling price (before PPN) commission is worked out on, when it
    # is lower than what was invoiced — and why. Finance or the director, at
    # approval; left out, commission is on the invoiced figure as before.
    basis_amount: float | None = None
    basis_note: str | None = None


class BasisIn(BaseModel):
    basis_amount: float
    basis_note: str | None = None


def _set_basis(c, invoiced: float, basis: float | None, note: str | None, me) -> None:
    """Put the commission basis on a claim: the invoiced figure, or the real
    selling price finance set lower, with its reason. Refuses a basis above
    what was invoiced (commission is never on more than the paperwork), at or
    below zero, or different from the invoice with no reason given."""
    c.invoiced_basis = round(float(invoiced), 2)
    if basis is None or abs(float(basis) - float(invoiced)) <= 0.005:
        c.basis_amount, c.basis_note, c.basis_set_by, c.basis_set_at = c.invoiced_basis, None, None, None
        return
    basis = round(float(basis), 2)
    if basis <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "The real selling price must be more than zero — reject the claim instead.")
    if basis > float(invoiced) + 0.005:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"The real selling price can't be more than was invoiced "
                            f"(Rp {invoiced:,.0f} before PPN).".replace(",", "."))
    why = (note or "").strip()
    if not why:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Say why the real selling price is lower than the invoice — the rep sees it.")
    c.basis_amount, c.basis_note = basis, why
    c.basis_set_by, c.basis_set_at = me.id, datetime.now(UTC)


async def _beneficiary_for(db: AsyncSession, project: Project) -> UUID | None:
    """Whose commission a job is. The rep who owns the customer."""
    cust = await db.get(Customer, project.customer_id) if project.customer_id else None
    return cust.sales_pic_id if cust else None


async def _serialize(db: AsyncSession, c: CommissionClaim) -> dict:
    project = await db.get(Project, c.project_id)
    who = await db.get(User, c.beneficiary_id) if c.beneficiary_id else None
    by = await db.get(User, c.claimed_by) if c.claimed_by else None
    decider = await db.get(User, c.decided_by) if c.decided_by else None
    setter = await db.get(User, c.basis_set_by) if c.basis_set_by else None
    return {
        **(claim_out(c) or {}),
        "project_id": str(c.project_id),
        "project_code": project.code if project else None,
        "project_status": project.status if project else None,
        "beneficiary_id": str(c.beneficiary_id) if c.beneficiary_id else None,
        "beneficiary_name": who.full_name if who else None,
        "claimed_by_name": by.full_name if by else None,
        "decided_by_name": decider.full_name if decider else None,
        "basis_set_by_name": setter.full_name if setter else None,
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


@router.get("/summary")
async def commission_summary(
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
    user_id: UUID | None = None,
    year: int | None = None,
):
    """One rep's whole commission picture, in the order they care about it:
    what can be claimed now, what has been filed and is moving, what has been
    paid.

    A rep reads their own by default; management can read somebody else's by
    naming them. A rep asking for a colleague gets the same refusal the claim
    endpoint gives, because pay is not something colleagues browse.

    `year` narrows the payout history only. Claimable and in-flight figures
    are live state, not history — filtering those by year would hide money
    somebody is owed today because the job started last December.
    """
    role = Role(me.role)
    target = me.id
    if user_id and user_id != me.id:
        if role not in (Role.DIRECTOR, Role.MANAGER, Role.FINANCE):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "You can see your own commission. Somebody else's is "
                "management's to look at.",
            )
        target = user_id

    who = await db.get(User, target)
    rows = (await db.execute(
        select(Project, Customer)
        .join(Customer, Project.customer_id == Customer.id)
        .where(Customer.sales_pic_id == target, Project.is_deleted.is_(False))
        .order_by(Project.created_at.desc())
    )).all()
    by_project = {p.id: (p, c) for p, c in rows}
    ids = list(by_project)

    money = await collected_for_projects(db, ids) if ids else {}
    live = await claims_for_projects(db, ids) if ids else {}

    # Claimable: settled in full, and nothing live standing on it. A refused
    # claim is not live, so its job comes back here — which is what makes
    # "claim again" the ordinary Claim button rather than a second door.
    claimable = []
    for pid in ids:
        project, customer = by_project[pid]
        m = money.get(pid) or {}
        if not m.get("paid_in_full") or live.get(pid) is not None:
            continue
        basis = float(m.get("basis") or 0)
        claimable.append({
            "project_id": str(pid),
            "project_code": project.code,
            "customer_name": customer.company_name,
            "collected": float(m.get("collected") or 0),
            # Before PPN: subtotal less discount.
            "basis": basis,
            "invoices": m.get("invoices", 0),
            "rate_pct": DEFAULT_RATE_PCT,
            "amount": round(basis * DEFAULT_RATE_PCT / 100.0, 2),
        })
    claimable.sort(key=lambda r: r["amount"], reverse=True)

    all_claims = (await db.scalars(
        select(CommissionClaim)
        .where(CommissionClaim.beneficiary_id == target)
        .order_by(CommissionClaim.created_at.desc())
    )).all()
    paid_years = sorted(
        {c.paid_at.year for c in all_claims if c.status == "paid" and c.paid_at},
        reverse=True,
    )

    filed = [c for c in all_claims if c.status in ("pending", "approved", "rejected")]
    paid = [c for c in all_claims if c.status == "paid"]
    if year:
        paid = [c for c in paid if c.paid_at and c.paid_at.year == year]

    async def _rows(claims):
        out = []
        for c in claims:
            row = await _serialize(db, c)
            pc = by_project.get(c.project_id)
            row["customer_name"] = pc[1].company_name if pc else None
            out.append(row)
        return out

    def _sum(claims):
        return round(sum(float(c.amount or 0) for c in claims), 2)

    pending = [c for c in filed if c.status == "pending"]
    approved = [c for c in filed if c.status == "approved"]

    return {
        "beneficiary": {
            "id": str(target),
            "name": who.full_name if who else None,
        },
        "rate_pct": DEFAULT_RATE_PCT,
        "year": year,
        "paid_years": paid_years,
        "totals": {
            "claimable": round(sum(r["amount"] for r in claimable), 2),
            "claimable_jobs": len(claimable),
            "pending": _sum(pending),
            "pending_claims": len(pending),
            "approved": _sum(approved),
            "approved_claims": len(approved),
            "paid": _sum(paid),
            "paid_claims": len(paid),
        },
        "claimable": claimable,
        "filed": await _rows(filed),
        "paid": await _rows(paid),
    }


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

    # Commission is on the sale, not the tax: subtotal less discount.
    basis = float(money.get("basis") or 0)
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

    # Claims filed while commission was still worked out on the money
    # collected — PPN included — are agreed on the figure before tax. Finance
    # may set the real selling price lower than the invoice, with a reason.
    _set_basis(c, float(money.get("basis") or 0), payload.basis_amount, payload.basis_note, me)
    if payload.rate_pct is not None and float(payload.rate_pct) != float(c.rate_pct or 0):
        if Role(me.role) != Role.DIRECTOR:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                "Only the director can settle a different rate — "
                                "approve it at the stated rate, or ask the director.")
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
               "amount": float(c.amount), "invoiced_basis": float(c.invoiced_basis or 0),
               "basis_amount": float(c.basis_amount or 0), "basis_note": c.basis_note},
    )
    return await _serialize(db, c)


@router.post("/{claim_id}/basis")
async def correct_basis(
    claim_id: UUID,
    payload: BasisIn,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(require(Role.DIRECTOR)),
):
    """Correct the real selling price on an approved claim, before it is paid.
    The director's alone once approved; a paid claim is booked and stays."""
    c = await db.get(CommissionClaim, claim_id)
    if not c:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Claim not found")
    if c.status != "approved":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Only an approved, unpaid claim can be corrected — this one is '{c.status}'.")
    before = {"basis_amount": float(c.basis_amount or 0), "amount": float(c.amount or 0),
              "basis_note": c.basis_note}
    invoiced = float(c.invoiced_basis if c.invoiced_basis is not None else c.basis_amount or 0)
    _set_basis(c, invoiced, payload.basis_amount, payload.basis_note, me)
    c.amount = round(float(c.basis_amount or 0) * float(c.rate_pct or 0) / 100.0, 2)
    await audit_record(db, actor=me, action="correct_commission_basis", entity="project",
                       entity_id=c.project_id, before=before,
                       after={"claim_id": str(c.id), "basis_amount": float(c.basis_amount),
                              "amount": float(c.amount), "basis_note": c.basis_note})
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
    payload: PayIn,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(require(Role.FINANCE, Role.DIRECTOR)),
):
    """It has been paid. Finance's to say, because finance is who can see it
    leave — and it is booked as it goes: Beban Komisi Penjualan Sales up, the
    bank (or cash) account it was paid from down, as one journal entry."""
    from datetime import date as date_t

    from app.models.account import Account
    from app.services import journal as journal_svc

    c = await db.get(CommissionClaim, claim_id)
    if not c:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Claim not found")
    if c.status != "approved":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Only an approved claim can be marked paid — this one is "
            f"'{c.status}'.",
        )
    from app.services.ledger import PAYMENT_CASH_DEFAULT
    cash_no = (payload.cash_account_no or PAYMENT_CASH_DEFAULT).strip()
    cash = await db.scalar(select(Account).where(Account.account_no == cash_no))
    if cash is None or cash.account_type not in ("Cash & Bank",):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"{cash_no} isn't a bank or cash account.")
    if not await db.scalar(select(Account).where(Account.account_no == COMMISSION_EXPENSE)):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Account {COMMISSION_EXPENSE} (Beban Komisi Penjualan Sales) "
                            "isn't in the chart of accounts — add it first.")
    try:
        on = date_t.fromisoformat(payload.paid_on) if payload.paid_on else date_t.today()
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "paid_on must be YYYY-MM-DD")
    project = await db.get(Project, c.project_id)
    who = await db.get(User, c.beneficiary_id) if c.beneficiary_id else None
    amount = round(float(c.amount or 0), 2)
    memo = (f"Komisi {who.full_name if who else ''} — {project.code if project else ''}"
            f" ({float(c.rate_pct or 0):g}%)").strip()
    entry = None
    if amount > 0:
        entry = await journal_svc.create_entry(
            db, entry_date=on, memo=memo,
            rows=[{"account_no": COMMISSION_EXPENSE, "debit": amount, "credit": 0, "memo": memo},
                  {"account_no": cash_no, "debit": 0, "credit": amount, "memo": memo}],
            source_type="commission", source_id=c.id,
            source_ref=project.code if project else None,
            created_by=me.id, post=True, posted_by=me.id)
    c.status = "paid"
    c.paid_at = datetime.now(UTC)
    if (payload.notes or "").strip():
        c.decision_notes = ((c.decision_notes or "") + "\n"
                            + payload.notes.strip()).strip()
    await audit_record(
        db, actor=me, action="pay_commission", entity="project",
        entity_id=c.project_id,
        after={"claim_id": str(c.id), "amount": float(c.amount or 0),
               "cash_account_no": cash_no, "journal": entry.number if entry else None},
    )
    out = await _serialize(db, c)
    out["journal_number"] = entry.number if entry else None
    return out

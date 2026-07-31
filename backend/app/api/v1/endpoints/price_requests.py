"""Price requests — the pre-quotation pricing workflow.

    sales lists goods → purchasing fills cost → director sets sell + approves
    → quotation is generated from the approved form (sales never types a price)

Margin protection is baked into serialization:
  • purchasing never sees the customer name or the selling price
  • sales never sees the procurement cost
  • director / manager / admin / finance see everything
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record as audit_record
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.permissions import Role, require_min
from app.models.crm import Customer
from app.models.price_request import PriceRequest
from app.models.user import User
from app.services.numbering import next_price_request_number

# Internal-only (sales tier and up); tier-0 externals (customer/supplier) blocked.
router = APIRouter(dependencies=[Depends(require_min(Role.SALES))])

_PURCHASING = {Role.PURCHASING, Role.DIRECTOR, Role.MANAGER, Role.ADMIN}
_MANAGEMENT = {Role.DIRECTOR, Role.MANAGER, Role.ADMIN, Role.FINANCE}


import re as _re

# Lines starting with a known internal-role tag are side-channel notes
# between staff, never for the customer. Matches only the concrete tags
# we actually write today so a user's own note like "[urgent]" doesn't
# get accidentally scrubbed.
_INTERNAL_TAG_LINE = _re.compile(
    r"^\s*\[(?:purchasing|director|manager|admin|finance|sales)\](?:\s.*)?$",
    _re.IGNORECASE,
)


def strip_internal_notes(text: str | None) -> str | None:
    """Drop internal role-tagged lines from a shared notes blob.

    Purchasing/director/etc. append `[purchasing] …`, `[director] …` (and
    similar) to Price-Request notes as an internal side-channel. Sales
    shouldn't see those on the PR page, and the tags MUST NOT bleed into
    the customer-facing quotation when we copy notes across — the quote's
    notes are printed on the PDF and shown on the customer portal.

    Only strips lines that match a concrete known-internal tag so a
    user-authored line that happens to start with a bracket (e.g. an
    inline reference like "[ref 001] follow up") is preserved.
    """
    if not text:
        return text
    kept = [ln for ln in text.splitlines() if not _INTERNAL_TAG_LINE.match(ln)]
    result = "\n".join(kept).strip()
    return result or None


# ─── Schemas ─────────────────────────────────────────────────────────────────
class ItemIn(BaseModel):
    description: str
    qty: float = 1
    uom: str | None = None
    spec: str | None = None


class PRCreate(BaseModel):
    customer_id: UUID
    items: list[ItemIn] = Field(default_factory=list)
    notes: str | None = None


class PRUpdate(BaseModel):
    items: list[ItemIn] | None = None
    notes: str | None = None
    # The PR number is editable meta (e.g. matching the customer's own RFQ
    # numbering) — allowed at any stage since quotations/projects link by id.
    number: str | None = None


class CostLine(BaseModel):
    line_no: int
    cost_price: float = 0
    # Whether cost_price is entered "per unit" or as the line "total".
    basis: str = "unit"


class PricingIn(BaseModel):
    items: list[CostLine] = Field(default_factory=list)
    notes: str | None = None


class SellLine(BaseModel):
    line_no: int
    sell_price: float = 0
    basis: str = "unit"               # basis for sell_price ("unit" | "total")
    cost_price: float | None = None   # director may also correct the cost
    cost_basis: str = "unit"          # basis for the optional cost correction


class ApproveIn(BaseModel):
    items: list[SellLine] = Field(default_factory=list)
    notes: str | None = None


class DecisionIn(BaseModel):
    notes: str | None = None


# ─── Helpers ─────────────────────────────────────────────────────────────────
def _to_unit(amount: float | None, basis: str | None, qty: float) -> float:
    """Normalise an entered price to a per-unit value.

    Prices are always stored per-unit (the quotation multiplies by qty). If the
    user entered a line *total* instead, divide it back out by the quantity.
    """
    amt = float(amount or 0)
    if (basis or "unit") == "total" and qty:
        return amt / float(qty)
    return amt


def _can_see_cost(role: Role) -> bool:
    return role in (Role.PURCHASING, Role.DIRECTOR, Role.MANAGER, Role.ADMIN, Role.FINANCE)


def _can_see_sell(role: Role) -> bool:
    # Everyone except purchasing (margin is none of their business).
    return role != Role.PURCHASING


def _can_see_customer(role: Role) -> bool:
    return role != Role.PURCHASING


async def _serialize(db: AsyncSession, pr: PriceRequest, role: Role) -> dict:
    cust = await db.get(Customer, pr.customer_id) if pr.customer_id else None
    see_cost, see_sell = _can_see_cost(role), _can_see_sell(role)
    items = []
    for it in (pr.items or []):
        row = {
            "line_no": it.get("line_no"),
            "description": it.get("description"),
            "qty": it.get("qty"),
            "uom": it.get("uom"),
            "spec": it.get("spec"),
        }
        if see_cost:
            row["cost_price"] = it.get("cost_price")
            row["cost_basis"] = it.get("cost_basis") or "unit"
            row["cost_total"] = float(it.get("cost_price") or 0) * float(it.get("qty") or 0)
        if see_sell:
            row["sell_price"] = it.get("sell_price")
            row["sell_basis"] = it.get("sell_basis") or "unit"
            row["line_total"] = float(it.get("sell_price") or 0) * float(it.get("qty") or 0)
        items.append(row)
    # Sales sees only the sales-authored notes; the [purchasing]/[director]
    # role-tagged side-channel lines are filtered out. Purchasing/mgmt see
    # the full blob so their conversation with the director isn't hidden
    # from them.
    notes_for_role = (
        strip_internal_notes(pr.notes) if role == Role.SALES else pr.notes
    )
    out = {
        "id": str(pr.id),
        "number": pr.number,
        "status": pr.status,
        "items": items,
        "notes": notes_for_role,
        "sales_pic_id": str(pr.sales_pic_id) if pr.sales_pic_id else None,
        "quotation_id": str(pr.quotation_id) if pr.quotation_id else None,
        "priced_at": pr.priced_at,
        "approved_at": pr.approved_at,
        "decision_notes": pr.decision_notes,
        "created_at": pr.created_at,
    }
    # Customer identity is hidden from purchasing — they see a neutral code.
    if _can_see_customer(role):
        out["customer_id"] = str(pr.customer_id) if pr.customer_id else None
        out["customer_name"] = cust.company_name if cust else None
    else:
        out["customer_name"] = f"Order {pr.number}"
    if see_sell:
        out["sell_total"] = sum(
            float(i.get("sell_price") or 0) * float(i.get("qty") or 0)
            for i in (pr.items or [])
        )
    return out


def _norm_items(items: list[ItemIn], previous: list[dict] | None = None) -> list[dict]:
    """Renumber the lines, carrying pricing across an edit.

    `previous` matters when a request is edited *after* purchasing has costed
    it — only the director can do that. Rebuilding the lines from scratch would
    silently blank every cost and approved sell price, which is a quiet way to
    lose real work. So a line whose description survives the edit keeps its
    prices, and a new or renamed line starts unpriced, because it is a
    different item and nobody has quoted it yet.

    Matching is on the description alone: prices are stored per unit, so
    changing a quantity, a UoM or a spec note does not invalidate them.
    Duplicate descriptions are paired off in order.
    """
    by_desc: dict[str, list[dict]] = {}
    for old in previous or []:
        by_desc.setdefault((old.get("description") or "").strip().casefold(), []).append(old)

    out = []
    for i, it in enumerate(items):
        pool = by_desc.get((it.description or "").strip().casefold())
        old = pool.pop(0) if pool else None
        out.append({
            "line_no": i + 1,
            "description": it.description,
            "qty": float(it.qty or 0),
            "uom": it.uom,
            "spec": it.spec,
            "cost_price": old.get("cost_price") if old else None,
            "sell_price": old.get("sell_price") if old else None,
        })
    return out


# ─── CRUD + workflow ─────────────────────────────────────────────────────────
@router.post("", status_code=201)
async def create_price_request(
    payload: PRCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if Role(user.role) not in (Role.SALES, Role.DIRECTOR, Role.MANAGER, Role.ADMIN):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only sales, a manager, admin or the director can raise a price request")
    cust = await db.get(Customer, payload.customer_id)
    if not cust:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Customer not found")
    if Role(user.role) == Role.SALES and cust.sales_pic_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your customer")
    pr = PriceRequest(
        number=await next_price_request_number(db),
        customer_id=payload.customer_id,
        sales_pic_id=user.id,
        status="draft",
        items=_norm_items(payload.items),
        notes=payload.notes,
        created_by=user.id, updated_by=user.id,
    )
    db.add(pr)
    await db.flush()
    return await _serialize(db, pr, Role(user.role))


async def _scoped(pr_id: UUID, db: AsyncSession, user: User) -> PriceRequest:
    pr = await db.get(PriceRequest, pr_id)
    if not pr or pr.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Price request not found")
    if Role(user.role) == Role.SALES and pr.sales_pic_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Out of scope")
    return pr


@router.get("")
async def list_price_requests(
    status_eq: str | None = None,
    customer_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    role = Role(user.role)
    stmt = select(PriceRequest).where(PriceRequest.is_deleted.is_(False)).order_by(
        PriceRequest.created_at.desc()
    )
    if role == Role.SALES:
        stmt = stmt.where(PriceRequest.sales_pic_id == user.id)
    elif role == Role.PURCHASING:
        # Purchasing works the costing queue — never sees sales' raw drafts.
        stmt = stmt.where(PriceRequest.status != "draft")
    if status_eq:
        stmt = stmt.where(PriceRequest.status == status_eq)
    if customer_id:
        # Customer-scoped view — used by the customer detail page's PR list
        # so sales sees only the PRs filed against this customer.
        stmt = stmt.where(PriceRequest.customer_id == customer_id)
    rows = (await db.scalars(stmt)).all()
    return [await _serialize(db, pr, role) for pr in rows]


@router.get("/{pr_id}")
async def get_price_request(
    pr_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    pr = await _scoped(pr_id, db, user)
    if Role(user.role) == Role.PURCHASING and pr.status == "draft":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Out of scope")
    return await _serialize(db, pr, Role(user.role))


@router.patch("/{pr_id}")
async def update_price_request(
    pr_id: UUID,
    payload: PRUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    pr = await _scoped(pr_id, db, user)
    # Number is meta and stays editable at any stage (links are by id, so a
    # rename can't orphan the quotation/project). Everything else keeps the
    # draft/rejected gate.
    if payload.number is not None:
        new_number = payload.number.strip()
        if new_number and new_number != pr.number:
            clash = await db.scalar(
                select(PriceRequest).where(
                    PriceRequest.number == new_number,
                    PriceRequest.id != pr.id,
                )
            )
            if clash:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"Price request number '{new_number}' already exists.",
                )
            old = pr.number
            pr.number = new_number
            await audit_record(db, actor=user, action="renumber",
                               entity="price_request", entity_id=pr.id,
                               before={"number": old},
                               after={"number": new_number})
    non_meta = payload.items is not None or payload.notes is not None
    # Past draft/rejected a request is a live commercial document: purchasing
    # has costed it and the director may have approved sell prices off the back
    # of it. The director can still correct one — a customer changes a spec
    # mid-negotiation and somebody has to be able to fix it — but nobody else,
    # and never silently.
    locked = pr.status not in ("draft", "rejected")
    if non_meta and locked and Role(user.role) != Role.DIRECTOR:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Only a draft or rejected request can be edited")

    before_items = list(pr.items or [])
    if payload.items is not None:
        pr.items = _norm_items(payload.items, before_items)
    if payload.notes is not None:
        pr.notes = payload.notes
    pr.updated_by = user.id

    if non_meta and locked:
        # An override on a costed or approved request is exactly the kind of
        # change someone will want to reconstruct later.
        await audit_record(
            db, actor=user, action="override_edit", entity="price_request",
            entity_id=pr.id,
            before={"status": pr.status, "items": before_items},
            after={"items": pr.items},
        )

    await db.flush()
    return await _serialize(db, pr, Role(user.role))


@router.post("/{pr_id}/submit")
async def submit_price_request(
    pr_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    pr = await _scoped(pr_id, db, user)
    if pr.status not in ("draft", "rejected"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Already submitted")
    if not (pr.items or []):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Add at least one line item")
    pr.status = "pending_purchasing"
    await audit_record(db, actor=user, action="submit", entity="price_request",
                       entity_id=pr.id, after={"status": pr.status})
    await db.flush()
    return await _serialize(db, pr, Role(user.role))


@router.post("/{pr_id}/price")
async def fill_pricing(
    pr_id: UUID,
    payload: PricingIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Purchasing fills the procurement cost per line, then it goes to the director."""
    if Role(user.role) not in _PURCHASING:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only purchasing, an admin, manager or the director may fill costs")
    pr = await db.get(PriceRequest, pr_id)
    if not pr or pr.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if pr.status not in ("pending_purchasing", "pending_director"):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Can't cost a request in status '{pr.status}'")
    costs = {c.line_no: c for c in payload.items}
    items = [dict(it) for it in (pr.items or [])]
    for it in items:
        c = costs.get(it.get("line_no"))
        if c is not None:
            qty = float(it.get("qty") or 0)
            it["cost_price"] = _to_unit(c.cost_price, c.basis, qty)
            it["cost_basis"] = c.basis or "unit"
    pr.items = items
    pr.priced_by = user.id
    pr.priced_at = datetime.now(UTC)
    if payload.notes:
        pr.notes = ((pr.notes or "") + f"\n[purchasing] {payload.notes}").strip()
    pr.status = "pending_director"
    await audit_record(db, actor=user, action="price", entity="price_request",
                       entity_id=pr.id, after={"status": pr.status})
    await db.flush()
    return await _serialize(db, pr, Role(user.role))


@router.post("/{pr_id}/approve")
async def approve_price_request(
    pr_id: UUID,
    payload: ApproveIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Director sets the selling price per line (and may correct costs), then approves."""
    if Role(user.role) != Role.DIRECTOR:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the director can approve pricing")
    pr = await db.get(PriceRequest, pr_id)
    if not pr or pr.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if pr.status not in ("pending_director", "pending_purchasing"):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Can't approve a request in status '{pr.status}'")
    sells = {s.line_no: s for s in payload.items}
    items = [dict(it) for it in (pr.items or [])]
    for it in items:
        s = sells.get(it.get("line_no"))
        if s is not None:
            qty = float(it.get("qty") or 0)
            it["sell_price"] = _to_unit(s.sell_price, s.basis, qty)
            it["sell_basis"] = s.basis or "unit"
            if s.cost_price is not None:
                it["cost_price"] = _to_unit(s.cost_price, s.cost_basis, qty)
                it["cost_basis"] = s.cost_basis or "unit"
    pr.items = items
    pr.approved_by = user.id
    pr.approved_at = datetime.now(UTC)
    pr.decision_notes = payload.notes
    pr.status = "approved"
    await audit_record(db, actor=user, action="approve", entity="price_request",
                       entity_id=pr.id, after={"status": "approved"})
    await db.flush()
    return await _serialize(db, pr, Role(user.role))


@router.post("/{pr_id}/reject")
async def reject_price_request(
    pr_id: UUID,
    payload: DecisionIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Send a request back to sales (director or purchasing)."""
    if Role(user.role) not in (Role.DIRECTOR, Role.PURCHASING, Role.MANAGER):
        raise HTTPException(status.HTTP_403_FORBIDDEN)
    pr = await db.get(PriceRequest, pr_id)
    if not pr or pr.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if pr.status == "approved":
        raise HTTPException(status.HTTP_409_CONFLICT, "Already approved")
    pr.status = "rejected"
    pr.decision_notes = payload.notes
    await audit_record(db, actor=user, action="reject", entity="price_request",
                       entity_id=pr.id, after={"status": "rejected", "notes": payload.notes})
    await db.flush()
    return await _serialize(db, pr, Role(user.role))


@router.get("/counts/pending")
async def pending_counts(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Badge counts for the role: what's waiting on me."""
    from sqlalchemy import func
    role = Role(user.role)
    out = {"pending_purchasing": 0, "pending_director": 0}
    if role in _PURCHASING:
        out["pending_purchasing"] = await db.scalar(
            select(func.count(PriceRequest.id)).where(
                PriceRequest.status == "pending_purchasing",
                PriceRequest.is_deleted.is_(False))) or 0
    if role in (Role.DIRECTOR, Role.MANAGER, Role.ADMIN):
        out["pending_director"] = await db.scalar(
            select(func.count(PriceRequest.id)).where(
                PriceRequest.status == "pending_director",
                PriceRequest.is_deleted.is_(False))) or 0
    return out


# ─── Negotiation revisions ───────────────────────────────────────────────────
# A price request that has left draft is a live commercial document, but a
# negotiation moves: the customer trims a quantity, swaps a spec, asks for one
# more line. Sales can propose that change, capped, and the director decides.
#
# The cap counts revisions the director *applied*, not proposals made. A
# rejected proposal changed nothing, so it should not spend the budget — the
# rep would otherwise be punished for the director's decision.

MAX_APPLIED_REVISIONS = 3


class ReviseIn(BaseModel):
    items: list[ItemIn] = Field(default_factory=list)
    notes: str | None = None
    reason: str | None = None


def _applied_revisions(pr: PriceRequest) -> int:
    return len([r for r in (pr.revisions or []) if r.get("status") == "approved"])


def _pending_revision(pr: PriceRequest) -> dict | None:
    return next((r for r in (pr.revisions or []) if r.get("status") == "pending"), None)


@router.post("/{pr_id}/revise")
async def propose_revision(
    pr_id: UUID,
    payload: ReviseIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Propose a change to a submitted request. The director decides."""
    pr = await _scoped(pr_id, db, user)
    if Role(user.role) not in (Role.SALES, Role.MANAGER, Role.ADMIN, Role.DIRECTOR):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Only sales, a manager, admin or the director can revise a request")
    if pr.status in ("draft", "rejected"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This request is still a draft — edit it directly, no approval needed.",
        )
    if _pending_revision(pr):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A revision is already waiting for the director. Wait for that "
            "decision before proposing another.",
        )
    used = _applied_revisions(pr)
    if used >= MAX_APPLIED_REVISIONS:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"This request has already been revised {used} times, the limit. "
            "Raise a new price request instead.",
        )
    if not payload.items:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A revision needs at least one line")

    proposed = _norm_items(payload.items, list(pr.items or []))
    n = len(pr.revisions or []) + 1
    entry = {
        "n": n,
        "status": "pending",
        "requested_by": str(user.id),
        "requested_by_name": user.full_name,
        "requested_at": datetime.now(UTC).isoformat(),
        "reason": (payload.reason or "").strip() or None,
        "before_items": list(pr.items or []),
        "proposed_items": proposed,
        "proposed_notes": payload.notes,
        "before_notes": pr.notes,
    }
    pr.revisions = list(pr.revisions or []) + [entry]

    from app.core.approval import request_approval
    req = await request_approval(
        db,
        target_type="price_request_revision",
        target_id=pr.id,
        requested_by=user.id,
        required_role=Role.DIRECTOR,
        reason=(f"Revision {n} of {pr.number}"
                + (f" — {entry['reason']}" if entry["reason"] else "")),
        payload={"revision_n": n},
    )
    entry["approval_request_id"] = str(req.id)
    pr.revisions = list(pr.revisions)          # re-assign so JSONB is flagged dirty
    await audit_record(db, actor=user, action="propose_revision",
                       entity="price_request", entity_id=pr.id,
                       after={"revision": n, "reason": entry["reason"]})
    await db.flush()
    return {
        "ok": True, "revision": n,
        "revisions_left": MAX_APPLIED_REVISIONS - used,
        "approval_request_id": str(req.id),
        "price_request": await _serialize(db, pr, Role(user.role)),
    }


@router.get("/{pr_id}/revisions")
async def list_revisions(
    pr_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """The negotiation log — every proposal and what came of it."""
    pr = await _scoped(pr_id, db, user)
    role = Role(user.role)
    out = []
    for r in (pr.revisions or []):
        row = {k: r.get(k) for k in
               ("n", "status", "requested_by_name", "requested_at", "reason",
                "decided_by_name", "decided_at", "decision_notes")}
        # Show what actually changed, not two raw item blobs.
        before = {(i.get("description") or "").strip(): i for i in (r.get("before_items") or [])}
        after = {(i.get("description") or "").strip(): i for i in (r.get("proposed_items") or [])}
        changes = []
        for desc, item in after.items():
            old = before.get(desc)
            if old is None:
                changes.append({"kind": "added", "description": desc, "qty": item.get("qty")})
            elif float(old.get("qty") or 0) != float(item.get("qty") or 0):
                changes.append({"kind": "qty", "description": desc,
                                "from": old.get("qty"), "to": item.get("qty")})
        for desc in before:
            if desc not in after:
                changes.append({"kind": "removed", "description": desc})
        row["changes"] = changes
        # Costs and prices are not sales' to see on a request they don't own;
        # the same rule the serializer applies to the live lines.
        if not _can_see_cost(role) and not _can_see_sell(role):
            row.pop("decision_notes", None)
        out.append(row)
    return {"revisions": out, "applied": _applied_revisions(pr),
            "limit": MAX_APPLIED_REVISIONS,
            "left": max(0, MAX_APPLIED_REVISIONS - _applied_revisions(pr))}

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
from app.core.permissions import Role, require_min, sales_may_see, sales_scope
from app.models.crm import Customer
from app.models.inventory import UNITS, normalise_uom
from app.models.price_request import PriceRequest
from app.models.user import User
from app.services.numbering import next_price_request_number

# Internal-only (sales tier and up); tier-0 externals (customer/supplier) blocked.
router = APIRouter(dependencies=[Depends(require_min(Role.SALES))])

# Who fills the buying cost. Admin is deliberately absent: they run the
# customer side of a job and may not see what the goods cost us, so they
# cannot be the ones typing it in either — a write without a read.
_PURCHASING = {Role.PURCHASING, Role.DIRECTOR, Role.MANAGER}
_MANAGEMENT = {Role.DIRECTOR, Role.MANAGER, Role.ADMIN, Role.FINANCE}


import re as _re

# Lines starting with a known internal-role tag are side-channel notes
# between staff, never for the customer. Matches only the concrete tags
# we actually write today so a user's own note like "[urgent]" doesn't
# get accidentally scrubbed.
_INTERNAL_TAG_LINE = _re.compile(
    # The tag is captured so a caller can ask to keep one — sales has to be
    # able to read the note it just wrote.
    r"^\s*\[(purchasing|director|manager|admin|finance|sales)\](?:\s.*)?$",
    _re.IGNORECASE,
)


def strip_internal_notes(text: str | None, keep: set[str] | None = None) -> str | None:
    """Drop internal role-tagged lines from a shared notes blob.

    Purchasing/director/etc. append `[purchasing] …`, `[director] …` (and
    similar) to Price-Request notes as an internal side-channel. Sales
    shouldn't see those on the PR page, and the tags MUST NOT bleed into
    the customer-facing quotation when we copy notes across — the quote's
    notes are printed on the PDF and shown on the customer portal.

    Only strips lines that match a concrete known-internal tag so a
    user-authored line that happens to start with a bracket (e.g. an
    inline reference like "[ref 001] follow up") is preserved.

    `keep` names tags to leave in. It exists for one case: showing sales the
    notes on their own request. Their own `[sales]` lines have to survive, or
    they write a note and watch it disappear. The copy that reaches the
    customer's quotation always uses the default — every tag stripped.
    """
    if not text:
        return text
    keep = {k.lower() for k in (keep or set())}
    kept = []
    for ln in text.splitlines():
        m = _INTERNAL_TAG_LINE.match(ln)
        if m and m.group(1).lower() not in keep:
            continue
        kept.append(ln)
    result = "\n".join(kept).strip()
    return result or None


# ─── Schemas ─────────────────────────────────────────────────────────────────
class ItemIn(BaseModel):
    # The product name. Kept as `description` because that is what every
    # document downstream already reads — the quotation, the customer PO,
    # the delivery order — and renaming the key would orphan every line
    # written before today.
    description: str
    qty: float = 1
    uom: str | None = None
    spec: str | None = None
    # What sales fills in so the part can become a catalogue row on submit.
    # A SKU is optional: leave it blank and one is issued from the same
    # series the purchase orders use, rather than making sales invent a
    # numbering scheme.
    sku: str | None = None
    category: str | None = None
    link: str | None = None


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


class NoteIn(BaseModel):
    text: str


class RepriceLine(BaseModel):
    """One line of a director's correction. Omit a price to leave it alone —
    changing a cost must not require re-typing the selling price, and the
    other way round."""
    line_no: int
    cost_price: float | None = None
    cost_basis: str = "unit"
    sell_price: float | None = None
    sell_basis: str = "unit"


class RepriceIn(BaseModel):
    items: list[RepriceLine] = Field(default_factory=list)
    # Required. This changes a number somebody has already agreed to, and in
    # six months "why is this line 12% dearer than the quote we sent" needs
    # an answer that is written down.
    reason: str


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
    """Everyone with a reason to know what we paid — which is not admin.

    Admin work the customer side: drawings for the customer, logistics,
    delivery, invoicing. Procurement cost is not part of any of that, and it is
    the figure that maps a customer to a vendor's price. Finance keep it —
    they pay the vendor's invoice against it.
    """
    return role in (Role.PURCHASING, Role.DIRECTOR, Role.MANAGER, Role.FINANCE)


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
            # The catalogue side of the line. Visible to everyone who can see
            # the request at all: purchasing needs the SKU to order against
            # the right row and the link to find the part, and neither says
            # anything about price.
            "sku": it.get("sku"),
            "category": it.get("category"),
            "link": it.get("link"),
        }
        if see_cost:
            row["cost_price"] = it.get("cost_price")
            row["cost_basis"] = it.get("cost_basis") or "unit"
            row["cost_total"] = float(it.get("cost_price") or 0) * float(it.get("qty") or 0)
            # Which supplier quote this cost came from, when it came from one
            # (SPR-…). Rides with the cost and is hidden from whoever cannot
            # see the cost — the number is only meaningful next to it.
            row["cost_source"] = it.get("cost_source")
            # ...and which vendor it was. On a job split between suppliers the
            # lines legitimately name different ones, so this is per line and
            # not a property of the request.
            row["cost_supplier"] = it.get("cost_supplier")
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
        strip_internal_notes(pr.notes, keep={"sales"})
        if role == Role.SALES else pr.notes
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
    # Corrections the director made after the fact. Filtered the same way the
    # lines are: purchasing sees costs move but never a selling price, sales
    # the reverse. An entry with nothing left to show is dropped rather than
    # rendered as a mysterious empty row.
    history = []
    for h in (pr.price_history or []):
        lines = []
        for ln in h.get("lines") or []:
            kept = {"line_no": ln.get("line_no"), "description": ln.get("description")}
            if see_cost and "cost_to" in ln:
                kept["cost_from"], kept["cost_to"] = ln.get("cost_from"), ln["cost_to"]
            if see_sell and "sell_to" in ln:
                kept["sell_from"], kept["sell_to"] = ln.get("sell_from"), ln["sell_to"]
            if len(kept) > 2:
                lines.append(kept)
        if lines:
            history.append({
                "at": h.get("at"), "by": h.get("by"),
                "reason": h.get("reason"), "status_then": h.get("status_then"),
                "quotation": h.get("quotation"), "lines": lines,
            })
    out["price_history"] = history
    return out


def _clean_unit(value: str | None) -> str | None:
    """One of the four units, or a refusal that lists them.

    Spellings already in the data ("EA", "pc", "buah", "m") are mapped
    rather than rejected — the point is that one part means one thing, not
    that anybody retypes history. Anything genuinely unrecognised is
    refused, because silently defaulting it to pcs would turn 30 metres of
    cable into 30 pieces.

    Blank survives a draft. Half-written requests are the normal state of a
    request somebody is still assembling, and refusing to save one until
    every field is filled is how people end up keeping the real list in a
    spreadsheet. Submit is where it becomes required — see
    `submit_price_request`, which is also where the catalogue row is created
    and the unit is baked into it.
    """
    if not (value or "").strip():
        return None
    resolved = normalise_uom(value)
    if resolved:
        return resolved
    raise HTTPException(
        status.HTTP_400_BAD_REQUEST,
        f"“{value}” is not a unit we count in. Use one of: {', '.join(UNITS)}.")


def _clean_link(value: str | None) -> str | None:
    """A link that a browser will actually open, or nothing.

    Only http and https. A `javascript:` or `data:` URL in a field that gets
    rendered as an anchor is a way to run something in the next person's
    browser, and no supplier's product page needs either.
    """
    link = (value or "").strip()
    if not link:
        return None
    if not _re.match(r"^https?://\S+$", link, _re.I):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"“{link[:60]}” is not a web address. Paste the full link, "
            "starting with http:// or https://.")
    return link[:1000]


def _carried(incoming: ItemIn, old: dict | None, field: str, clean):
    """What a rebuilt line should hold for a field the caller may not have sent.

    `model_fields_set` is the distinction that matters: a field sent as blank
    is somebody clearing it, and a field not sent at all is a client that
    does not know about it. Treating those the same is how an edit from an
    older form silently erases work.
    """
    if field in incoming.model_fields_set:
        return clean(getattr(incoming, field))
    return old.get(field) if old else None


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
        row = {
            "line_no": i + 1,
            "description": it.description,
            "qty": float(it.qty or 0),
            "uom": _clean_unit(it.uom),
            "spec": it.spec,
            # Carried across an edit unless the caller actually said
            # otherwise. This rebuilds every row from scratch, so a client
            # that does not render a field would erase it — which is how an
            # old edit form quietly wiped the supplier a cost came from. A
            # field explicitly sent as blank still clears it; one simply not
            # mentioned is left alone.
            "category": _carried(it, old, "category",
                                 lambda v: (v or "").strip()[:120] or None),
            "link": _carried(it, old, "link", _clean_link),
            # Blank until submit issues one. Losing the SKU here would let
            # the same part be introduced twice under two numbers.
            "sku": ((it.sku or "").strip()
                    or (old.get("sku") if old else None) or None),
            "cost_price": old.get("cost_price") if old else None,
            "sell_price": old.get("sell_price") if old else None,
        }
        # Carry the surviving line's *provenance* too, not just its numbers.
        # This rebuilds each row from scratch, so anything not named here is
        # dropped — which used to quietly erase which supplier quote a cost
        # came from the first time anybody edited the request.
        for k in ("cost_basis", "cost_source", "cost_supplier"):
            if old and old.get(k) is not None:
                row[k] = old[k]
        # A revision that carries a new cost overrides what was carried across;
        # that is the whole point of purchasing proposing one.
        new_cost = getattr(it, "cost_price", None)
        if new_cost is not None:
            row["cost_price"] = _to_unit(
                float(new_cost), getattr(it, "cost_basis", "unit") or "unit",
                row["qty"])
            row["cost_basis"] = getattr(it, "cost_basis", "unit") or "unit"
        out.append(row)
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
    # The request belongs to whoever runs the account, not to whoever typed
    # it. A director raising one on a rep's customer is doing it *for* that
    # rep — making it the director's left the rep unable to act on their own
    # work. Falls back to the author when the account has nobody on it.
    pr = PriceRequest(
        number=await next_price_request_number(db),
        customer_id=payload.customer_id,
        sales_pic_id=cust.sales_pic_id or user.id,
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
    # Theirs if they raised it, or if the customer is theirs — the director
    # filing a request against a rep's account is the ordinary case, and the
    # rep has to be able to work it.
    cust = await db.get(Customer, pr.customer_id) if pr.customer_id else None
    if not sales_may_see(user, pr.sales_pic_id, cust.sales_pic_id if cust else None):
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
        stmt = sales_scope(user, stmt, PriceRequest.sales_pic_id,
                           PriceRequest.customer_id)
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
    # Every line needs a unit before it leaves sales, because the next thing
    # that happens is a catalogue row being created with that unit on it,
    # and everything downstream counts against it. A default here would turn
    # 30 metres of cable into 30 pieces without anybody typing a wrong
    # character.
    missing = [str(i.get("line_no") or "?") for i in (pr.items or [])
               if not (i.get("uom") or "").strip()]
    if missing:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Line {', '.join(missing)}: say what it is counted in — "
            f"{', '.join(UNITS)}.")
    pr.status = "pending_purchasing"
    # The products join the catalogue here, and only the products. Quantity
    # is not touched: a price request says a customer wants something, not
    # that we have any. Stock arrives when purchasing opens a supplier PO
    # for it, and leaves again on a delivery order.
    from app.services.stock_sync import catalogue_from_price_request
    skus = await catalogue_from_price_request(db, pr, user)
    await audit_record(db, actor=user, action="submit", entity="price_request",
                       entity_id=pr.id,
                       after={"status": pr.status, "catalogued": skus})
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


@router.post("/{pr_id}/note")
async def add_note(
    pr_id: UUID,
    payload: NoteIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Add a note to a price request, at any stage.

    Sales could not do this at all. Notes were only ever written in two
    places — the box on the create form, and the one purchasing and the
    director get while costing or approving — and the moment a request left
    draft the whole document locked, so a rep with something to say about
    their own request had nowhere to put it. (The page did not even show the
    notes back, so the ones typed at creation were write-only.)

    Appended rather than replaced, and tagged with the writer's role. Both
    matter. Replacing would let one person overwrite the running record, and
    for sales it would silently delete the [purchasing] lines they cannot see
    in the first place. The tag is what keeps the internal conversation out
    of the customer's quotation, which copies these notes onto its PDF.
    """
    pr = await _scoped(pr_id, db, user)
    text = " ".join((payload.text or "").split())
    if not text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Write something first")
    if len(text) > 1000:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "That note is too long (max 1000 characters)")
    line = f"[{Role(user.role).value}] {text}"
    pr.notes = f"{(pr.notes or '').rstrip()}\n{line}".strip()
    pr.updated_by = user.id
    await audit_record(db, actor=user, action="note", entity="price_request",
                       entity_id=pr.id, after={"note": line})
    await db.flush()
    return await _serialize(db, pr, Role(user.role))


@router.post("/{pr_id}/reprice")
async def reprice_price_request(
    pr_id: UUID,
    payload: RepriceIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Change a cost or a selling price on a request that is already settled.

    Until now both numbers could only be set on the way through the pipeline:
    purchasing entered the cost before the request reached the director, the
    director set the sell price at the moment of approval, and after that the
    figures were frozen. Real life does not respect that. A supplier revises a
    quote, a rate moves, the director agrees a different price on the phone —
    and the request that everything downstream reads from still says the old
    number.

    So this is the director's alone, works at any stage, and takes each price
    independently: send a cost without a sell price and only the cost moves.

    What it deliberately does NOT do is rewrite documents that have left the
    building. A draft quotation is still ours, and its prices are locked to
    this request by design, so it is brought back into line. One that has been
    sent, approved or won is a statement already made to the customer — that
    is corrected by issuing a revision, not by editing history underneath it.
    The response says which happened.
    """
    if Role(user.role) != Role.DIRECTOR:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Only the director can change a price or a cost")
    pr = await db.get(PriceRequest, pr_id)
    if not pr or pr.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    reason = (payload.reason or "").strip()
    if not reason:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Say why the price is changing")
    if not payload.items:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No lines to change")

    by_line = {r.line_no: r for r in payload.items}
    unknown = sorted(set(by_line) - {it.get("line_no") for it in (pr.items or [])})
    if unknown:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"This request has no line {unknown[0]}")

    before_items = [dict(it) for it in (pr.items or [])]
    items = [dict(it) for it in (pr.items or [])]
    changes: list[dict] = []
    for it in items:
        r = by_line.get(it.get("line_no"))
        if r is None:
            continue
        qty = float(it.get("qty") or 0)
        entry: dict = {"line_no": it["line_no"], "description": it.get("description")}
        if r.cost_price is not None:
            new_cost = _to_unit(r.cost_price, r.cost_basis, qty)
            if new_cost != (it.get("cost_price") or None):
                entry["cost_from"] = it.get("cost_price")
                entry["cost_to"] = new_cost
                it["cost_price"] = new_cost
                it["cost_basis"] = "unit"
        if r.sell_price is not None:
            new_sell = _to_unit(r.sell_price, r.sell_basis, qty)
            if new_sell != (it.get("sell_price") or None):
                entry["sell_from"] = it.get("sell_price")
                entry["sell_to"] = new_sell
                it["sell_price"] = new_sell
                it["sell_basis"] = "unit"
        if len(entry) > 2:                      # something actually moved
            changes.append(entry)

    if not changes:
        # Re-submitting the same numbers is not an event. Saying so beats
        # writing an empty entry into the history nobody can interpret later.
        return {**await _serialize(db, pr, Role(user.role)),
                "changed_lines": 0, "quotation": None}

    pr.items = items
    pr.updated_by = user.id

    # ── bring a still-draft quotation back into line ─────────────────────
    quote_result: dict | None = None
    if pr.quotation_id:
        from app.models.quotation import Quotation, QuotationItem
        q = await db.get(Quotation, pr.quotation_id)
        if q:
            if q.status == "draft":
                q_items = (await db.scalars(
                    select(QuotationItem).where(QuotationItem.quotation_id == q.id)
                )).all()
                moved = 0
                for qi in q_items:
                    src = next((x for x in items
                                if x.get("line_no") == qi.line_no), None)
                    if not src:
                        continue
                    if src.get("sell_price") is not None:
                        if float(qi.unit_price or 0) != float(src["sell_price"]):
                            moved += 1
                        qi.unit_price = float(src["sell_price"])
                    if src.get("cost_price") is not None:
                        qi.cost_estimate = float(src["cost_price"])
                from app.api.v1.endpoints.quotations import _recalc
                _recalc(q, list(q_items))
                q.updated_by = user.id
                quote_result = {"id": str(q.id), "number": q.number,
                                "status": q.status, "action": "updated",
                                "lines_changed": moved}
            else:
                quote_result = {"id": str(q.id), "number": q.number,
                                "status": q.status, "action": "left_alone"}

    stamp = {
        "at": datetime.now(UTC).isoformat(),
        "by": user.full_name,
        "by_id": str(user.id),
        "status_then": pr.status,
        "reason": reason,
        "lines": changes,
        "quotation": quote_result,
    }
    pr.price_history = [*(pr.price_history or []), stamp]

    await audit_record(
        db, actor=user, action="reprice", entity="price_request",
        entity_id=pr.id,
        before={"items": before_items},
        after={"items": items, "reason": reason},
    )
    await db.flush()
    return {**await _serialize(db, pr, Role(user.role)),
            "changed_lines": len(changes), "quotation": quote_result}


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


class ReviseItemIn(ItemIn):
    """A proposed line. Purchasing may also move its cost.

    Sales revise *what is being bought* — a spec changed, the customer wants
    forty metres instead of fifty. Purchasing revise *what it costs us*, which
    is the correction they could not make before: once they had costed a
    request and sent it on, a supplier coming back with a different number left
    them nothing to do but ask somebody else to retype it.
    """
    cost_price: float | None = None
    cost_basis: str = "unit"           # "unit" | "total", as everywhere else


class ReviseIn(BaseModel):
    items: list[ReviseItemIn] = Field(default_factory=list)
    notes: str | None = None
    reason: str | None = None


def _applied_revisions(pr: PriceRequest) -> int:
    """How many *scope* revisions have been approved.

    The cap is on renegotiating the order, which is why purchasing's cost
    corrections are not counted: a supplier moving their price twice must not
    be what stops sales agreeing a quantity with the customer. Revisions filed
    before `kind` existed are scope revisions, which is what they were.
    """
    return len([r for r in (pr.revisions or [])
                if r.get("status") == "approved" and r.get("kind", "scope") != "cost"])


def _pending_revision(pr: PriceRequest) -> dict | None:
    return next((r for r in (pr.revisions or []) if r.get("status") == "pending"), None)


@router.post("/{pr_id}/revise")
async def propose_revision(
    pr_id: UUID,
    payload: ReviseIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Propose a change to a submitted request. The director decides.

    Purchasing get here too. Their edit is a *cost* revision: uncapped, because
    it is not a negotiation with the customer, but never silent — the director
    signs off each one, which is the point. Everyone else's is a scope
    revision, capped at three, exactly as before.
    """
    pr = await _scoped(pr_id, db, user)
    role = Role(user.role)
    if role not in (Role.SALES, Role.MANAGER, Role.ADMIN, Role.DIRECTOR,
                    Role.PURCHASING):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Only sales, purchasing, a manager, admin or the "
                            "director can revise a request")
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
    kind = "cost" if role == Role.PURCHASING else "scope"
    used = _applied_revisions(pr)
    if kind != "cost" and used >= MAX_APPLIED_REVISIONS:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"This request has already been revised {used} times, the limit. "
            "Raise a new price request instead.",
        )
    if not payload.items:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A revision needs at least one line")
    # A cost sent by somebody who cannot see costs would be a write without a
    # read — the property `test_write_read_symmetry` exists to protect.
    if not _can_see_cost(role) and any(i.cost_price is not None for i in payload.items):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Costs aren't yours to set on a price request.")

    proposed = _norm_items(payload.items, list(pr.items or []))
    n = len(pr.revisions or []) + 1
    entry = {
        "n": n,
        "kind": kind,
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
        reason=((f"Cost revision {n} of {pr.number}" if kind == "cost"
                 else f"Revision {n} of {pr.number}")
                + (f" — {entry['reason']}" if entry["reason"] else "")),
        payload={"revision_n": n, "kind": kind},
    )
    entry["approval_request_id"] = str(req.id)
    pr.revisions = list(pr.revisions)          # re-assign so JSONB is flagged dirty
    await audit_record(db, actor=user, action="propose_revision",
                       entity="price_request", entity_id=pr.id,
                       after={"revision": n, "reason": entry["reason"]})
    await db.flush()
    return {
        "ok": True, "revision": n, "kind": kind,
        # A cost revision spends none of the negotiation budget, so reporting
        # one fewer left would be a lie the UI then repeats.
        "revisions_left": (None if kind == "cost"
                           else MAX_APPLIED_REVISIONS - used),
        "approval_request_id": str(req.id),
        "price_request": await _serialize(db, pr, role),
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
        row["kind"] = r.get("kind", "scope")
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
            # A cost that moved is the whole content of a purchasing revision,
            # and invisible in a qty-only diff. Only for eyes that may see cost
            # — for sales this line simply isn't in the log.
            if old is not None and _can_see_cost(role):
                was, now = old.get("cost_price"), item.get("cost_price")
                if (was or 0) != (now or 0):
                    changes.append({"kind": "cost", "description": desc,
                                    "from": was, "to": now})
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

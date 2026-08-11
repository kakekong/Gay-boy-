"""Supplier price requests — what we ask a vendor to charge us.

The buy-side twin of `price_requests.py`. That one runs sell-side:

    sales lists goods → purchasing fills cost → director sets sell price

and the middle step was a black box. Purchasing asked two or three vendors on
WhatsApp, typed the best number into the cost field, and everything else — who
else was asked, what they said, how long each said delivery would take, how
long the price holds — stayed in a phone. When the director asked "why is this
one so expensive", the answer was a memory.

    purchasing asks N suppliers → each answers → one answer becomes the cost

One row per supplier asked, so three vendors on the same job are three rows
side by side. A request may point at the customer price request it serves, in
which case its quoted prices can be *applied* as the cost on that request —
which is the reason to write any of it down. It may also stand alone: keeping
a price list current, or checking a rate before a tender, has no deal behind
it.

**Sales never reaches this router.** Procurement cost is the one thing sales
must not see (`price_requests` hides it from them line by line), and a
document whose entire content is procurement cost cannot be an exception.
"""

from datetime import UTC, date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record as audit_record
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.permissions import Role, require
from app.models.price_request import PriceRequest
from app.models.purchasing import Supplier, SupplierPriceRequest
from app.models.user import User
from app.services.numbering import next_supplier_price_request_number

# Purchasing and management only. Not sales, at any tier — see the module
# docstring — and not the tier-0 portal roles, which `require` excludes by
# listing membership explicitly.
router = APIRouter(dependencies=[Depends(require(
    Role.PURCHASING, Role.DIRECTOR, Role.MANAGER, Role.ADMIN,
))])

_OPEN = ("draft", "sent")


# ─── payloads ────────────────────────────────────────────────────────────────

class ItemIn(BaseModel):
    line_no: int
    description: str
    qty: float = 0
    uom: str | None = None
    note: str | None = None


class CreateIn(BaseModel):
    # One request per supplier, created in one go so "ask these three" is one
    # action rather than three trips through a form.
    supplier_ids: list[UUID]
    price_request_id: UUID | None = None
    # Omitted when price_request_id is given: the lines are copied from it,
    # which is the point — asking about something other than what the customer
    # asked for would compare two different things.
    items: list[ItemIn] = []
    notes: str | None = None
    valid_until: date | None = None
    currency: str = "IDR"


class UpdateIn(BaseModel):
    items: list[ItemIn] | None = None
    notes: str | None = None
    valid_until: date | None = None
    currency: str | None = None


class QuotedLine(BaseModel):
    line_no: int
    quoted_price: float
    # "unit" or "total" — purchasing is given whichever the supplier quoted in
    # and should not have to divide by hand. Stored per unit either way, the
    # same convention `price_requests` uses.
    basis: str = "unit"
    lead_days: int | None = None
    note: str | None = None


class QuoteIn(BaseModel):
    items: list[QuotedLine] = []
    quoted_lead_days: int | None = None
    valid_until: date | None = None
    notes: str | None = None


class CloseIn(BaseModel):
    reason: str | None = None


def _to_unit(value: float, basis: str | None, qty: float) -> float:
    """Normalise a quoted figure to a per-unit price.

    Same rule as the sell-side form: a supplier who quotes "12 juta for the
    lot" and one who quotes "600rb each" have to end up comparable.
    """
    if (basis or "unit") == "total" and qty:
        return float(value) / float(qty)
    return float(value)


def _line_total(it: dict) -> float:
    return float(it.get("quoted_price") or 0) * float(it.get("qty") or 0)


def _out(spr: SupplierPriceRequest, supplier: Supplier | None,
         pr: PriceRequest | None = None) -> dict:
    items = [dict(i) for i in (spr.items or [])]
    quoted = [i for i in items if i.get("quoted_price") is not None]
    return {
        "id": str(spr.id),
        "number": spr.number,
        "status": spr.status,
        "supplier_id": str(spr.supplier_id),
        "supplier_name": supplier.name if supplier else None,
        "price_request_id": str(spr.price_request_id) if spr.price_request_id else None,
        "price_request_number": pr.number if pr else None,
        "requested_by": str(spr.requested_by) if spr.requested_by else None,
        "items": items,
        "notes": spr.notes,
        "currency": spr.currency,
        "valid_until": spr.valid_until,
        "quoted_lead_days": spr.quoted_lead_days,
        "sent_at": spr.sent_at,
        "quoted_at": spr.quoted_at,
        "applied_at": spr.applied_at,
        # What the whole basket comes to at the quoted prices — the number a
        # comparison is actually made on. Only meaningful once every line has
        # an answer, so it says so rather than quietly summing a partial quote.
        "quoted_total": sum(_line_total(i) for i in items) if quoted else None,
        "lines_quoted": len(quoted),
        "lines_total": len(items),
        "created_at": spr.created_at,
    }


async def _load(spr_id: UUID, db: AsyncSession) -> SupplierPriceRequest:
    spr = await db.get(SupplierPriceRequest, spr_id)
    if not spr:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Supplier price request not found")
    return spr


async def _decorate(db: AsyncSession, rows: list[SupplierPriceRequest]) -> list[dict]:
    sup_ids = {r.supplier_id for r in rows}
    pr_ids = {r.price_request_id for r in rows if r.price_request_id}
    sups = {s.id: s for s in (await db.scalars(
        select(Supplier).where(Supplier.id.in_(sup_ids)))).all()} if sup_ids else {}
    prs = {p.id: p for p in (await db.scalars(
        select(PriceRequest).where(PriceRequest.id.in_(pr_ids)))).all()} if pr_ids else {}
    return [_out(r, sups.get(r.supplier_id),
                 prs.get(r.price_request_id) if r.price_request_id else None)
            for r in rows]


# ─── endpoints ───────────────────────────────────────────────────────────────

@router.post("", status_code=201)
async def create_requests(
    payload: CreateIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Ask one or more suppliers what they charge.

    Returns one request per supplier. Asking three vendors is one action here
    because it is one action in life — the same list, sent three times.
    """
    if not payload.supplier_ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Pick at least one supplier")
    if len(set(payload.supplier_ids)) != len(payload.supplier_ids):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "The same supplier is listed twice")

    pr: PriceRequest | None = None
    if payload.price_request_id:
        pr = await db.get(PriceRequest, payload.price_request_id)
        if not pr or pr.is_deleted:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Price request not found")

    # Lines: copied from the customer request when there is one, so the two
    # documents are asking about the same goods and the answer can be applied
    # line for line. Costs and selling prices are NOT copied — this goes to an
    # outside company, and what we charge is none of their business.
    if pr is not None:
        items = [{
            "line_no": it.get("line_no"),
            "description": it.get("description"),
            "qty": float(it.get("qty") or 0),
            "uom": it.get("uom"),
            "spec": it.get("spec") or {},
        } for it in (pr.items or [])]
        if not items:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "That price request has no lines to ask about")
    else:
        if not payload.items:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Add at least one line, or pick a price request")
        items = [{
            "line_no": i.line_no, "description": i.description,
            "qty": float(i.qty or 0), "uom": i.uom, "note": i.note,
        } for i in payload.items]

    created: list[SupplierPriceRequest] = []
    for sid in payload.supplier_ids:
        supplier = await db.get(Supplier, sid)
        if not supplier:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Supplier {sid} not found")
        spr = SupplierPriceRequest(
            number=await next_supplier_price_request_number(db),
            supplier_id=sid,
            price_request_id=pr.id if pr else None,
            requested_by=user.id,
            status="draft",
            items=[dict(i) for i in items],
            notes=payload.notes,
            currency=payload.currency or "IDR",
            valid_until=payload.valid_until,
        )
        db.add(spr)
        # Flushed inside the loop so the next number sees this one — without
        # it, asking three suppliers hands all three the same number and the
        # unique index refuses the second.
        await db.flush()
        created.append(spr)

    await audit_record(db, actor=user, action="create",
                       entity="supplier_price_request", entity_id=created[0].id,
                       after={"numbers": [s.number for s in created],
                              "price_request": pr.number if pr else None})
    return await _decorate(db, created)


@router.get("")
async def list_requests(
    status_filter: str | None = Query(None, alias="status"),
    supplier_id: UUID | None = None,
    price_request_id: UUID | None = None,
    open_only: bool = False,
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(get_current_user),
):
    q = select(SupplierPriceRequest).order_by(SupplierPriceRequest.created_at.desc())
    if status_filter:
        q = q.where(SupplierPriceRequest.status == status_filter)
    if supplier_id:
        q = q.where(SupplierPriceRequest.supplier_id == supplier_id)
    if price_request_id:
        q = q.where(SupplierPriceRequest.price_request_id == price_request_id)
    if open_only:
        q = q.where(SupplierPriceRequest.status.in_(_OPEN))
    return await _decorate(db, list((await db.scalars(q)).all()))


@router.get("/counts/pending")
async def pending_count(
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(get_current_user),
):
    """How many are still out with a supplier — the sidebar badge's number."""
    rows = (await db.scalars(
        select(SupplierPriceRequest.id)
        .where(SupplierPriceRequest.status == "sent")
    )).all()
    return {"pending": len(rows)}


@router.get("/{spr_id}")
async def get_request(
    spr_id: UUID,
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(get_current_user),
):
    spr = await _load(spr_id, db)
    return (await _decorate(db, [spr]))[0]


@router.patch("/{spr_id}")
async def update_request(
    spr_id: UUID,
    payload: UpdateIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Fix the list or the covering note, before the supplier has answered."""
    spr = await _load(spr_id, db)
    if spr.status not in _OPEN:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"A '{spr.status}' request can't be edited — it already has an answer.",
        )
    data = payload.model_dump(exclude_unset=True)
    if "items" in data and data["items"] is not None:
        if not data["items"]:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "A request needs at least one line")
        if spr.price_request_id:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "The lines come from the price request this is costing — "
                "changing them here would compare two different things.",
            )
        spr.items = [{"line_no": i["line_no"], "description": i["description"],
                      "qty": float(i.get("qty") or 0), "uom": i.get("uom"),
                      "note": i.get("note")} for i in data["items"]]
    for field in ("notes", "valid_until", "currency"):
        if field in data:
            setattr(spr, field, data[field])
    await db.flush()
    return (await _decorate(db, [spr]))[0]


@router.post("/{spr_id}/send")
async def mark_sent(
    spr_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Mark it as out with the supplier.

    The sending itself is still email or WhatsApp — this records that it went
    and when, so a request nobody has chased is visible as one.
    """
    spr = await _load(spr_id, db)
    if spr.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Already '{spr.status}'.")
    spr.status = "sent"
    spr.sent_at = datetime.now(UTC)
    await audit_record(db, actor=user, action="send",
                       entity="supplier_price_request", entity_id=spr.id,
                       after={"number": spr.number})
    await db.flush()
    return (await _decorate(db, [spr]))[0]


@router.post("/{spr_id}/quote")
async def record_quote(
    spr_id: UUID,
    payload: QuoteIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Write down what the supplier came back with.

    Callable more than once: a vendor who revises their price mid-negotiation
    is normal, and the last word is the one that counts. Callable on a draft
    too — a price read off a current price list never needed sending.
    """
    spr = await _load(spr_id, db)
    if spr.status in ("closed", "cancelled"):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"A '{spr.status}' request can't take a new quote.")
    quoted = {q.line_no: q for q in payload.items}
    items = [dict(it) for it in (spr.items or [])]
    for it in items:
        q = quoted.get(it.get("line_no"))
        if q is None:
            continue
        qty = float(it.get("qty") or 0)
        it["quoted_price"] = _to_unit(q.quoted_price, q.basis, qty)
        it["quoted_basis"] = q.basis or "unit"
        if q.lead_days is not None:
            it["lead_days"] = q.lead_days
        if q.note is not None:
            it["note"] = q.note
    spr.items = items
    if payload.quoted_lead_days is not None:
        spr.quoted_lead_days = payload.quoted_lead_days
    if payload.valid_until is not None:
        spr.valid_until = payload.valid_until
    if payload.notes:
        spr.notes = ((spr.notes or "") + f"\n[quote] {payload.notes}").strip()
    spr.status = "quoted"
    spr.quoted_at = datetime.now(UTC)
    await audit_record(db, actor=user, action="quote",
                       entity="supplier_price_request", entity_id=spr.id,
                       after={"number": spr.number,
                              "lines": len(quoted)})
    await db.flush()
    return (await _decorate(db, [spr]))[0]


@router.post("/{spr_id}/apply")
async def apply_to_price_request(
    spr_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Make this supplier's quote the cost on the customer price request.

    This is why the record exists. The cost that reaches the director now has
    a document behind it — this supplier, this price, this date — instead of
    being a number somebody remembered, and the quotes that lost are still on
    file next to it.

    Applying a second quote to the same request is allowed and simply
    supersedes the first: a better price arriving late is good news, not an
    error. The one that is current carries `applied_at`.
    """
    spr = await _load(spr_id, db)
    if not spr.price_request_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This request isn't costing anything — it has no price request "
            "behind it.",
        )
    if spr.status != "quoted":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Record the supplier's quote first.")
    pr = await db.get(PriceRequest, spr.price_request_id)
    if not pr or pr.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Price request not found")
    if pr.status not in ("pending_purchasing", "pending_director"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Can't cost a price request in status '{pr.status}'.",
        )

    priced = {i.get("line_no"): i for i in (spr.items or [])
              if i.get("quoted_price") is not None}
    if not priced:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "This quote has no prices on it yet.")

    supplier = await db.get(Supplier, spr.supplier_id)
    items = [dict(it) for it in (pr.items or [])]
    touched = 0
    for it in items:
        q = priced.get(it.get("line_no"))
        if q is None:
            continue
        it["cost_price"] = float(q["quoted_price"])
        it["cost_basis"] = "unit"
        # Where this number came from, on the line itself — the PR page reads
        # its lines, not this table.
        it["cost_source"] = spr.number
        touched += 1
    pr.items = items
    pr.priced_by = user.id
    pr.priced_at = datetime.now(UTC)
    pr.status = "pending_director"
    pr.notes = ((pr.notes or "")
                + f"\n[purchasing] Cost from {spr.number}"
                + (f" ({supplier.name})" if supplier else "")).strip()

    # Only one quote is the live cost. Stand the others down so the page can
    # say which one the price came from without guessing.
    siblings = (await db.scalars(
        select(SupplierPriceRequest).where(
            SupplierPriceRequest.price_request_id == pr.id,
            SupplierPriceRequest.id != spr.id,
        )
    )).all()
    for other in siblings:
        other.applied_at = None
    spr.applied_at = datetime.now(UTC)
    spr.status = "closed"

    await audit_record(db, actor=user, action="apply_quote",
                       entity="price_request", entity_id=pr.id,
                       after={"from": spr.number, "lines": touched,
                              "supplier": supplier.name if supplier else None})
    await db.flush()
    return {"applied_lines": touched, "price_request_status": pr.status,
            "price_request_number": pr.number,
            "supplier_price_request": (await _decorate(db, [spr]))[0]}


@router.post("/{spr_id}/close")
async def close_request(
    spr_id: UUID,
    payload: CloseIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """File it away: they never answered, or somebody else won the job."""
    spr = await _load(spr_id, db)
    # Closing something already closed is a no-op on the status but the reason
    # is still worth having: the usual case is a quote that `apply` closed
    # being annotated afterwards with why a different one won.
    spr.status = "closed"
    if payload.reason:
        spr.notes = ((spr.notes or "") + f"\n[closed] {payload.reason}").strip()
    await audit_record(db, actor=user, action="close",
                       entity="supplier_price_request", entity_id=spr.id,
                       after={"number": spr.number, "reason": payload.reason})
    await db.flush()
    return (await _decorate(db, [spr]))[0]


@router.delete("/{spr_id}", status_code=204)
async def delete_draft(
    spr_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Throw away a draft raised by mistake.

    Drafts only: once a request has been sent or answered it is part of the
    record of how a price was arrived at, and that is not for tidying away.
    Use close instead.
    """
    spr = await _load(spr_id, db)
    if spr.status != "draft":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"A '{spr.status}' request is part of the record — close it instead.",
        )
    await audit_record(db, actor=user, action="delete",
                       entity="supplier_price_request", entity_id=spr.id,
                       after={"number": spr.number})
    await db.delete(spr)
    return None


@router.get("/for-price-request/{pr_id}/compare")
async def compare_for_price_request(
    pr_id: UUID,
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(get_current_user),
):
    """Every vendor asked about one job, side by side.

    Ordered cheapest complete quote first, then the ones still outstanding —
    which is the order the decision is made in.
    """
    pr = await db.get(PriceRequest, pr_id)
    if not pr or pr.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Price request not found")
    rows = (await db.scalars(
        select(SupplierPriceRequest)
        .where(SupplierPriceRequest.price_request_id == pr_id)
    )).all()
    out = await _decorate(db, list(rows))

    def key(r: dict):
        complete = r["lines_quoted"] == r["lines_total"] and r["lines_total"] > 0
        return (0 if complete else 1, r["quoted_total"] if complete else 0)

    out.sort(key=key)
    return {"price_request_number": pr.number, "price_request_status": pr.status,
            "requests": out}

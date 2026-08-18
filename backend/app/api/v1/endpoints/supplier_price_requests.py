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
#
# Admin is out for the same reason sales is: this document's entire content is
# what a vendor charges us, and admin work the customer side of a job. There is
# no version of it they may open.
router = APIRouter(dependencies=[Depends(require(
    Role.PURCHASING, Role.DIRECTOR, Role.MANAGER,
))])

_OPEN = ("draft", "sent")


# ─── payloads ────────────────────────────────────────────────────────────────

class ItemIn(BaseModel):
    line_no: int
    description: str
    qty: float = 0
    uom: str | None = None
    note: str | None = None


class LineRef(BaseModel):
    """One line of one customer price request."""
    price_request_id: UUID
    line_no: int


class Assignment(BaseModel):
    """Which supplier is being asked about which lines.

    This is the shape of "PT A does the chain, PT B does the sprockets": one
    job, split down the line list, each half sent to whoever can make it. An
    empty `lines` means "everything in scope", which is the ordinary
    ask-them-all case written the same way.
    """
    supplier_ids: list[UUID] = []
    supplier_id: UUID | None = None      # convenience for a single vendor
    lines: list[LineRef] = []

    def suppliers(self) -> list[UUID]:
        out = list(self.supplier_ids)
        if self.supplier_id and self.supplier_id not in out:
            out.append(self.supplier_id)
        return out


class CreateIn(BaseModel):
    # The simple path: these suppliers, everything in scope, one request each.
    supplier_ids: list[UUID] = []
    # The split path: this supplier gets these lines, that one gets those.
    # Scenario 1 — several suppliers needed to fill one order.
    assignments: list[Assignment] = []

    # What is in scope. One price request, or several combined into a single
    # ask — scenario 2, one vendor covering several jobs in one shipment.
    price_request_id: UUID | None = None
    price_request_ids: list[UUID] = []
    # A subset of the scope for the simple path. Empty = all of it.
    lines: list[LineRef] = []

    # Standalone: no price request behind it at all.
    items: list[ItemIn] = []

    notes: str | None = None
    valid_until: date | None = None
    currency: str = "IDR"


class UpdateIn(BaseModel):
    # The number is purchasing's own reference on the sheet they send out —
    # editable until it has gone, after which changing it means the vendor
    # is holding a document that no longer matches ours.
    number: str | None = None
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
         pr: PriceRequest | None = None,
         sources: list[dict] | None = None) -> dict:
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
        # Where the lines came from. On a joint request `price_request_id` is
        # NULL and this is the real answer; on a single-source one it is a
        # list of one and says the same thing twice, on purpose, so a caller
        # never has to branch.
        "source_price_requests": sources or [],
        "is_joint": len(sources or []) > 1,
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
    pr_ids: set[UUID] = {r.price_request_id for r in rows if r.price_request_id}
    for r in rows:
        for sid in (r.source_pr_ids or []):
            try:
                pr_ids.add(UUID(str(sid)))
            except (ValueError, TypeError):
                continue
    sups = {s.id: s for s in (await db.scalars(
        select(Supplier).where(Supplier.id.in_(sup_ids)))).all()} if sup_ids else {}
    prs = {p.id: p for p in (await db.scalars(
        select(PriceRequest).where(PriceRequest.id.in_(pr_ids)))).all()} if pr_ids else {}

    out = []
    for r in rows:
        sources = []
        for sid in (r.source_pr_ids or []):
            try:
                pr = prs.get(UUID(str(sid)))
            except (ValueError, TypeError):
                continue
            if pr:
                lines = [i.get("line_no") for i in (r.items or [])
                         if str(i.get("source_pr_id")) == str(sid)]
                sources.append({"id": str(pr.id), "number": pr.number,
                                "status": pr.status, "lines": sorted(
                                    x for x in lines if x is not None)})
        out.append(_out(r, sups.get(r.supplier_id),
                        prs.get(r.price_request_id) if r.price_request_id else None,
                        sources))
    return out


def _scope_prs(payload: "CreateIn") -> list[UUID]:
    """Which customer price requests this call is about, in the order given."""
    ids: list[UUID] = []
    if payload.price_request_id:
        ids.append(payload.price_request_id)
    for x in payload.price_request_ids:
        if x not in ids:
            ids.append(x)
    return ids


def _pr_line(pr: PriceRequest, line_no: int) -> dict | None:
    for it in (pr.items or []):
        if int(it.get("line_no") or 0) == int(line_no):
            return it
    return None


def _copy_line(pr: PriceRequest, it: dict, line_no: int) -> dict:
    """A customer PR line, as a line of something we send to an outside
    company: the goods and nothing about who wants them or what they pay."""
    return {
        "line_no": line_no,
        "description": it.get("description"),
        "qty": float(it.get("qty") or 0),
        "uom": it.get("uom"),
        "spec": it.get("spec") or {},
        # Where it came from. This is the whole trick: it survives being split
        # across suppliers and being combined with other jobs, so a quote can
        # be applied back to exactly the right line of the right request.
        "source_pr_id": str(pr.id),
        "source_pr_number": pr.number,
        "source_line_no": it.get("line_no"),
    }


async def _touching(db: AsyncSession, pr_id: UUID) -> list[SupplierPriceRequest]:
    """Every supplier request that draws a line from this price request.

    Matched on `source_pr_ids` rather than the header link, because a request
    covering three jobs has no single header link and a request covering half
    a job is still about this one.
    """
    return list((await db.scalars(
        select(SupplierPriceRequest)
        .where(or_(
            SupplierPriceRequest.price_request_id == pr_id,
            SupplierPriceRequest.source_pr_ids.contains([str(pr_id)]),
        ))
        .order_by(SupplierPriceRequest.created_at.asc())
    )).all())



# ─── endpoints ───────────────────────────────────────────────────────────────

@router.post("", status_code=201)
async def create_requests(
    payload: CreateIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Ask suppliers what they charge — for everything, or line by line.

    Three shapes, one endpoint, because they are the same act with different
    line lists:

    * **Ask them all.** `supplier_ids` + a price request: one request each,
      every line. What most jobs are.
    * **Split the job.** `assignments`: this vendor gets these lines, that one
      gets those. Nobody makes the whole basket, so nobody is asked to quote
      for the parts they don't make.
    * **Combine the jobs.** `price_request_ids`: several customer requests in
      one ask, because one vendor is filling all of them in one shipment.

    Every line keeps a pointer home either way, so applying a quote later
    lands on the right line of the right request no matter how it was cut.
    """
    scope_ids = _scope_prs(payload)
    prs: dict[UUID, PriceRequest] = {}
    for pid in scope_ids:
        pr = await db.get(PriceRequest, pid)
        if not pr or pr.is_deleted:
            raise HTTPException(status.HTTP_404_NOT_FOUND,
                                f"Price request {pid} not found")
        prs[pid] = pr

    def lines_for(refs: list[LineRef]) -> list[dict]:
        """Resolve line references into copied lines, renumbered 1..n."""
        chosen = refs or [
            LineRef(price_request_id=pid, line_no=int(it.get("line_no") or 0))
            for pid in scope_ids for it in (prs[pid].items or [])
        ]
        out: list[dict] = []
        for ref in chosen:
            pr = prs.get(ref.price_request_id)
            if pr is None:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"Line {ref.line_no} names price request "
                    f"{ref.price_request_id}, which is not in this request.",
                )
            it = _pr_line(pr, ref.line_no)
            if it is None:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"{pr.number} has no line {ref.line_no}.",
                )
            out.append(_copy_line(pr, it, len(out) + 1))
        return out

    # Work out the (supplier, lines) pairs this call creates.
    plan: list[tuple[UUID, list[dict]]] = []
    if payload.assignments:
        for a in payload.assignments:
            sups = a.suppliers()
            if not sups:
                raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                    "An assignment needs a supplier")
            if not scope_ids:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "Splitting lines between suppliers needs a price request "
                    "to split.")
            picked = lines_for(a.lines)
            if not picked:
                raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                    "An assignment needs at least one line")
            for sid in sups:
                plan.append((sid, [dict(x) for x in picked]))
    elif payload.supplier_ids:
        if len(set(payload.supplier_ids)) != len(payload.supplier_ids):
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "The same supplier is listed twice")
        if scope_ids:
            picked = lines_for(payload.lines)
            if not picked:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "Those price requests have no lines to ask about")
        else:
            if not payload.items:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "Add at least one line, or pick a price request")
            picked = [{"line_no": i.line_no, "description": i.description,
                       "qty": float(i.qty or 0), "uom": i.uom, "note": i.note}
                      for i in payload.items]
        for sid in payload.supplier_ids:
            plan.append((sid, [dict(x) for x in picked]))
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Pick at least one supplier")

    # One supplier must not end up with two requests for the same lines from
    # one click — that is a mis-click, not an order.
    seen: set[tuple] = set()
    for sid, items in plan:
        key = (sid, tuple(sorted((i.get("source_pr_id"), i.get("source_line_no"))
                                 for i in items)))
        if key in seen:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "The same supplier is asked the same lines twice")
        seen.add(key)

    created: list[SupplierPriceRequest] = []
    for sid, items in plan:
        supplier = await db.get(Supplier, sid)
        if not supplier:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Supplier {sid} not found")
        srcs = sorted({str(i["source_pr_id"]) for i in items if i.get("source_pr_id")})
        spr = SupplierPriceRequest(
            number=await next_supplier_price_request_number(db),
            supplier_id=sid,
            # The single-source shorthand, and NULL the moment it is joint —
            # a request covering three jobs does not belong to one of them.
            price_request_id=(UUID(srcs[0]) if len(srcs) == 1 else None),
            source_pr_ids=srcs,
            requested_by=user.id,
            status="draft",
            items=items,
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
                              "price_requests": [prs[p].number for p in scope_ids]})
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

    if "number" in data:
        new_num = (data["number"] or "").strip()
        if not new_num:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "The request number can't be empty")
        if spr.status != "draft":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "This has already gone to the supplier — renumbering it now "
                "would leave them holding a different document.",
            )
        if new_num != spr.number:
            clash = await db.scalar(
                select(SupplierPriceRequest).where(
                    SupplierPriceRequest.number == new_num,
                    SupplierPriceRequest.id != spr.id,
                )
            )
            if clash:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"'{new_num}' is already used by another request",
                )
            spr.number = new_num

    if "items" in data and data["items"] is not None:
        if not data["items"]:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "A request needs at least one line")
        # Once it has gone out, the vendor is quoting against the list they
        # were sent. Correcting the list underneath them would mean their
        # answer no longer says what it looks like it says.
        if spr.status != "draft":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "This has already gone to the supplier — they are quoting "
                "against the list they were sent.",
            )
        # A request that costs a customer's price request is measured against
        # it: the comparison across vendors, and the "which lines are covered"
        # accounting, both work off `line_no`. So the *wording* of a line is
        # purchasing's to fix — a typo, a missing UOM, a quantity the customer
        # revised — but the set of lines is not theirs to add to or drop from
        # here. That is what would compare two different things.
        old = {int(i.get("line_no")): dict(i) for i in (spr.items or [])}
        # A joint request has no `price_request_id` — the sources live per
        # line — so ask the lines themselves whether they came from anywhere.
        borrowed = bool(spr.price_request_id) or any(
            i.get("source_pr_id") for i in old.values())
        if borrowed:
            now_ = {int(i["line_no"]) for i in data["items"]}
            if set(old) != now_:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "The lines come from the price request this is costing — "
                    "reword them here, but adding or removing one would "
                    "compare two different things.",
                )
        # Merge rather than replace: a line also carries where it came from
        # and, on a draft priced off a vendor's list, what they charge. This
        # call is about the wording, and must not quietly drop the rest.
        items = []
        for i in data["items"]:
            row = old.get(int(i["line_no"]), {})
            row.update({
                "line_no": i["line_no"],
                "description": i["description"],
                "qty": float(i.get("qty") or 0),
                "uom": i.get("uom"),
                "note": i.get("note") if i.get("note") is not None else row.get("note"),
            })
            items.append(row)
        spr.items = items
    for field in ("notes", "valid_until", "currency"):
        if field in data:
            setattr(spr, field, data[field])
    await audit_record(db, actor=user, action="update",
                       entity="supplier_price_request", entity_id=spr.id,
                       after={"number": spr.number, "fields": sorted(data)})
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
    """Make this supplier's quote the cost on the lines it was asked about.

    This is why the record exists. The cost that reaches the director now has
    a document behind it — this supplier, this price, this date — instead of
    being a number somebody remembered, and the quotes that lost are still on
    file next to it.

    It applies **per line**, which is what makes the two hard cases work. A
    request split between two vendors writes each vendor's half onto its own
    lines. A request covering three jobs writes onto all three. And a customer
    price request only goes to the director once *every* one of its lines has
    a cost — a half-costed job reaching a decision is how a margin gets set on
    a number nobody has.

    Applying again supersedes: a better price arriving late is good news.
    """
    spr = await _load(spr_id, db)
    if not spr.source_pr_ids and not spr.price_request_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This request isn't costing anything — it has no price request "
            "behind it.",
        )
    if spr.status != "quoted":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Record the supplier's quote first.")

    priced = [i for i in (spr.items or []) if i.get("quoted_price") is not None]
    if not priced:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "This quote has no prices on it yet.")

    supplier = await db.get(Supplier, spr.supplier_id)
    results: list[dict] = []
    touched_total = 0

    # Group the priced lines by the request they came from, and write each
    # group home.
    by_pr: dict[str, list[dict]] = {}
    for i in priced:
        src = i.get("source_pr_id") or (str(spr.price_request_id)
                                        if spr.price_request_id else None)
        if src:
            by_pr.setdefault(str(src), []).append(i)
    if not by_pr:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "These lines don't point back at a price request.")

    for pr_id_str, lines in by_pr.items():
        pr = await db.get(PriceRequest, UUID(pr_id_str))
        if not pr or pr.is_deleted:
            results.append({"price_request_id": pr_id_str,
                            "skipped": "price request no longer exists"})
            continue
        if pr.status not in ("pending_purchasing", "pending_director"):
            results.append({"price_request_id": pr_id_str,
                            "price_request_number": pr.number,
                            "skipped": f"status is '{pr.status}'"})
            continue

        want = {int(i.get("source_line_no") or i.get("line_no") or 0):
                float(i["quoted_price"]) for i in lines}
        items = [dict(it) for it in (pr.items or [])]
        touched = 0
        for it in items:
            price = want.get(int(it.get("line_no") or 0))
            if price is None:
                continue
            it["cost_price"] = price
            it["cost_basis"] = "unit"
            # Where this number came from, on the line itself — the PR page
            # reads its lines, not this table. On a split job the lines
            # legitimately name different suppliers, which is the point.
            it["cost_source"] = spr.number
            it["cost_supplier"] = supplier.name if supplier else None
            touched += 1
        pr.items = items
        pr.priced_by = user.id
        pr.priced_at = datetime.now(UTC)
        part = (f" — lines {', '.join(str(k) for k in sorted(want))}"
                if len(want) < len(items) else "")
        pr.notes = ((pr.notes or "")
                    + f"\n[purchasing] Cost from {spr.number}"
                    + (f" ({supplier.name})" if supplier else "")
                    + part).strip()

        # Only a fully-costed request goes up. A split job waits for the other
        # supplier's half rather than reaching the director half-priced.
        missing = [int(it.get("line_no") or 0) for it in items
                   if it.get("cost_price") in (None, "")]
        pr.status = "pending_purchasing" if missing else "pending_director"
        touched_total += touched
        results.append({
            "price_request_id": str(pr.id),
            "price_request_number": pr.number,
            "applied_lines": touched,
            "status": pr.status,
            "lines_still_uncosted": missing,
        })
        await audit_record(db, actor=user, action="apply_quote",
                           entity="price_request", entity_id=pr.id,
                           after={"from": spr.number, "lines": touched,
                                  "supplier": supplier.name if supplier else None,
                                  "still_uncosted": missing})

    # Nothing landed anywhere: that is a refusal, not a success with an empty
    # report. It is the single-request case that used to 409 — an approved
    # price request being re-costed underneath the director — and it has to
    # keep saying so. When *some* of a joint request applied, it is a partial
    # success and the per-request results carry the skips.
    if touched_total == 0:
        why = "; ".join(
            f"{r.get('price_request_number') or r['price_request_id']}: "
            f"{r.get('skipped')}" for r in results if r.get("skipped"))
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Nothing to cost — {why}" if why else "Nothing to cost.",
        )

    # Only one quote per *line* is the live cost — but two suppliers each
    # covering half a job are both live. So the mark is cleared only from
    # requests whose lines this one actually overlaps.
    mine = {(str(i.get("source_pr_id")), i.get("source_line_no")) for i in priced}
    siblings = (await db.scalars(
        select(SupplierPriceRequest).where(
            SupplierPriceRequest.id != spr.id,
            SupplierPriceRequest.applied_at.is_not(None),
        )
    )).all()
    for other in siblings:
        if any((str(i.get("source_pr_id")), i.get("source_line_no")) in mine
               for i in (other.items or [])):
            other.applied_at = None
    spr.applied_at = datetime.now(UTC)
    spr.status = "closed"

    await db.flush()
    first = results[0] if results else {}
    return {
        "applied_lines": touched_total,
        "price_requests": results,
        # Kept flat for the single-request case every existing caller reads.
        "price_request_status": first.get("status"),
        "price_request_number": first.get("price_request_number"),
        "supplier_price_request": (await _decorate(db, [spr]))[0],
    }


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
    which is the order the decision is made in. Finds requests by their
    *lines*, not by the header link, so a vendor asked about half the job and
    a vendor asked about it inside a combined order both show up here.
    """
    pr = await db.get(PriceRequest, pr_id)
    if not pr or pr.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Price request not found")
    rows = await _touching(db, pr_id)
    out = await _decorate(db, rows)

    def key(r: dict):
        complete = r["lines_quoted"] == r["lines_total"] and r["lines_total"] > 0
        return (0 if complete else 1, r["quoted_total"] if complete else 0)

    out.sort(key=key)
    return {"price_request_number": pr.number, "price_request_status": pr.status,
            "requests": out}


@router.get("/for-price-request/{pr_id}/coverage")
async def coverage_for_price_request(
    pr_id: UUID,
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(get_current_user),
):
    """Line by line: who has been asked, who answered, what it cost.

    The question purchasing actually has in front of a split job — *which
    lines still have nobody on them* — and the reason the customer request
    does not go to the director until the answer is "none".
    """
    pr = await db.get(PriceRequest, pr_id)
    if not pr or pr.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Price request not found")
    rows = await _touching(db, pr_id)
    sups = {s.id: s for s in (await db.scalars(
        select(Supplier).where(
            Supplier.id.in_({r.supplier_id for r in rows}))))} if rows else {}

    lines = []
    for it in (pr.items or []):
        no = int(it.get("line_no") or 0)
        asked = []
        for r in rows:
            for i in (r.items or []):
                if str(i.get("source_pr_id")) != str(pr_id):
                    continue
                if int(i.get("source_line_no") or 0) != no:
                    continue
                sup = sups.get(r.supplier_id)
                asked.append({
                    "supplier_price_request_id": str(r.id),
                    "number": r.number,
                    "status": r.status,
                    "supplier_id": str(r.supplier_id),
                    "supplier_name": sup.name if sup else None,
                    "quoted_price": i.get("quoted_price"),
                    "lead_days": i.get("lead_days"),
                    "is_applied": r.applied_at is not None,
                })
        lines.append({
            "line_no": no,
            "description": it.get("description"),
            "qty": it.get("qty"),
            "uom": it.get("uom"),
            "cost_price": it.get("cost_price"),
            "cost_source": it.get("cost_source"),
            "cost_supplier": it.get("cost_supplier"),
            "asked": asked,
            "is_asked": bool(asked),
            "is_quoted": any(a["quoted_price"] is not None for a in asked),
            "is_costed": it.get("cost_price") not in (None, ""),
        })

    return {
        "price_request_id": str(pr.id),
        "price_request_number": pr.number,
        "price_request_status": pr.status,
        "lines": lines,
        "lines_total": len(lines),
        "lines_asked": sum(1 for x in lines if x["is_asked"]),
        "lines_costed": sum(1 for x in lines if x["is_costed"]),
        "uncovered": [x["line_no"] for x in lines if not x["is_costed"]],
        # The whole point in one field: can this go to the director yet.
        "fully_costed": all(x["is_costed"] for x in lines) and bool(lines),
    }

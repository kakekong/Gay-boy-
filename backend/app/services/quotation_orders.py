"""A quotation ordered in batches: how much of each line is ordered, and the
status that follows.

A customer may order a quotation a piece at a time — three lines this week,
the other seven next week, or 60 of 100 metres now and 40 later. Each batch
is its own customer PO and becomes its own project. What ties them together
is the quotation: each PO line names the quotation line it orders
(`line_no`), so summing them per line says what has been ordered and what is
still open.

* `line_orders` — per quotation line: quoted, ordered, still open.
* `check_po_lines` — once a line is partly ordered, a further PO may not
  order more of it than is still open.
* `refresh_status` — once a quotation is won, it reads "partially_won"
  while some of it is open and "won" when everything is ordered, and
  `ordered_total` holds what has been ordered (after discount, PPN in).

POs that were rejected or cancelled don't count; revisions of the quotation
are one deal and share their line numbers.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_DEAD = ("rejected", "cancelled")


async def _family(db: AsyncSession, quotation_id) -> set[UUID]:
    from app.services.customer_po_removal import quote_family_ids
    return await quote_family_ids(db, quotation_id)


async def live_pos(db: AsyncSession, quotation_id, exclude_id=None) -> list:
    """The deal's customer POs that count, oldest first."""
    from app.models.customer_po import CustomerPO
    fam = await _family(db, quotation_id)
    if not fam:
        return []
    stmt = select(CustomerPO).where(CustomerPO.quotation_id.in_(fam),
                                    CustomerPO.status.notin_(_DEAD))
    if exclude_id:
        stmt = stmt.where(CustomerPO.id != exclude_id)
    return list((await db.scalars(stmt.order_by(CustomerPO.created_at.asc()))).all())


async def sent_back_po(db: AsyncSession, quotation_id):
    """A PO on the deal the director rejected, if any — it is fixed and
    resubmitted rather than filed again."""
    from app.models.customer_po import CustomerPO
    fam = await _family(db, quotation_id)
    if not fam:
        return None
    return (await db.scalars(select(CustomerPO).where(
        CustomerPO.quotation_id.in_(fam), CustomerPO.status == "rejected")
        .order_by(CustomerPO.created_at.asc()).limit(1))).first()


async def line_orders(db: AsyncSession, q, exclude_po_id=None) -> dict[int, dict]:
    """{line_no: {description, uom, unit_price, quoted, ordered, open, pos}}."""
    out: dict[int, dict] = {}
    for it in sorted(q.items or [], key=lambda x: int(x.line_no or 0)):
        no = int(it.line_no or 0)
        out[no] = {"line_no": no, "description": it.description, "uom": it.uom,
                   "unit_price": float(it.unit_price or 0), "quoted": float(it.qty or 0),
                   "ordered": 0.0, "open": float(it.qty or 0), "pos": []}
    for po in await live_pos(db, q.id, exclude_id=exclude_po_id):
        for ln in (po.items or []):
            if not isinstance(ln, dict) or ln.get("line_no") in (None, ""):
                continue
            row = out.get(int(ln["line_no"]))
            if row is None:
                continue
            qty = float(ln.get("qty") or 0)
            row["ordered"] = round(row["ordered"] + qty, 6)
            row["pos"].append({"po_id": str(po.id), "number": po.number,
                               "status": po.status, "qty": qty})
    for row in out.values():
        row["open"] = round(max(row["quoted"] - row["ordered"], 0.0), 6)
    return out


async def check_po_lines(db: AsyncSession, q, items: list[dict], exclude_po_id=None) -> None:
    """Refuse a PO that orders more of a line than is still open — and, once
    the deal already has a PO, one whose lines don't name the quotation lines
    they order (the batch can't be tracked otherwise)."""
    others = await live_pos(db, q.id, exclude_id=exclude_po_id)
    orders = await line_orders(db, q, exclude_po_id=exclude_po_id)
    if others and any(it.get("line_no") in (None, "") for it in items):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"This quotation already has customer PO {others[0].number}. A further batch "
            "has to be picked from the quotation's lines, so the system can tell what "
            "is still open — use \"Submit customer PO\" on the quotation.")
    # An earlier PO typed in by hand can't say what it ordered, so nothing
    # can be known to be open after it.
    untracked = next((po for po in others if not any(
        isinstance(ln, dict) and ln.get("line_no") not in (None, "") for ln in (po.items or []))), None)
    if untracked is not None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Customer PO {untracked.number} on this quotation was typed in by hand, so the "
            "system can't tell which lines are still open. Redo that PO from the quotation's "
            "lines first, then file this one.")
    asked: dict[int, float] = {}
    for it in items:
        if it.get("line_no") in (None, ""):
            continue
        no = int(it["line_no"])
        if no not in orders:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"{q.number} has no line {no}.")
        asked[no] = asked.get(no, 0.0) + float(it.get("qty") or 0)
    for no, qty in asked.items():
        row = orders[no]
        # The first PO to order a line may differ from the quotation — the
        # customer orders 130 of a quoted 100, and the deal check flags it as
        # it always did. Once a line is partly on another PO, a further batch
        # may only take what is left: that is what catches the same PO filed
        # twice, and a batch that would order the line over.
        if row["pos"] and qty > row["open"] + 1e-6:
            done = f"{row['ordered']:g} already on {', '.join(p['number'] for p in row['pos'])}" \
                if row["pos"] else "none ordered yet"
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Line {no} ({row['description']}): {qty:g} {row['uom'] or ''} is more than is "
                f"still open — {row['quoted']:g} quoted, {done}, {row['open']:g} left.")


async def is_fully_ordered(db: AsyncSession, q, orders: dict[int, dict] | None = None) -> bool:
    """Everything on the quotation ordered — or no way to tell: no PO that
    picked its lines from the quotation (none at all, or lines typed in
    fresh). Then the whole quotation counts as ordered, as a single Won
    always did; only POs that name quotation lines can leave some open."""
    if orders is None:
        orders = await line_orders(db, q)
    tracked = any(isinstance(ln, dict) and ln.get("line_no") not in (None, "")
                  for po in await live_pos(db, q.id) for ln in (po.items or []))
    if not tracked:
        return True
    return bool(orders) and all(r["open"] <= 1e-6 for r in orders.values())


def _gross(q, net: float) -> float:
    """A pre-discount amount as the quotation would charge it: less the
    quotation's discount in proportion, plus its PPN."""
    sub = float(q.subtotal or 0)
    disc = float(q.discount_amount or 0)
    after = net - (disc * min(1.0, net / sub) if sub > 0 and disc > 0 else 0.0)
    return round(after * (1 + float(q.tax_pct or 0) / 100.0), 2)


async def refresh_status(db: AsyncSession, q) -> str:
    """Bring a won quotation's status and ordered value up to its POs."""
    from app.models.quotation import WON_STATES
    orders = await line_orders(db, q)
    everything = await is_fully_ordered(db, q, orders)
    if everything:
        q.ordered_total = q.total or 0
    else:
        net = sum(min(r["ordered"], r["quoted"]) * r["unit_price"] for r in orders.values())
        q.ordered_total = _gross(q, net)
    if q.status in WON_STATES:
        q.status = "won" if everything else "partially_won"
    await db.flush()
    return q.status

"""Bringing the shelf back in line with the paperwork.

Stock in this system is a ledger, not a number. Every change is written as an
`InventoryMovement` carrying the document that caused it, and `current_stock`
is a running total of those movements kept on the item for speed. The rule is
in `stock_sync`'s docstring and it is the whole design: *never a bare edit to
the running total*.

Things predate that rule. Items were typed in with an opening figure and no
movement behind it. Quantities were set directly on the row. Orders went
through mechanisms that have since been replaced. The result is a count that
no longer follows from anything you can read, which is the state where people
stop trusting the number and start keeping their own list.

This puts it back, and it does three separate things because they are three
separate faults:

**Drift.** `current_stock` disagrees with the sum of the item's own movements.
The movements are the record — they each name a document and a reason — so the
total is what is wrong, and it is set to what its own history says. No
movement is written for this: the existing ones already justify the figure, and
adding one would change the sum it was reconciled to.

**Stock with no history.** An item holding a quantity with no movements at all
is not drift; it is an opening balance somebody typed before the ledger
existed. The figure is probably right and the explanation is missing, so the
explanation is written — an `opening` movement for exactly what is there. The
count does not move. Erasing these because no document justifies them would
throw away real stock on a technicality.

**Documents that never landed.** A supplier order that is open but whose goods
were never counted in: the shelf is short by an order somebody placed. The
order is replayed through the ordinary path, so it lands as `po_in` against its
own number and is indistinguishable from one that worked first time.

What this deliberately does **not** do is decide that undocumented stock is
wrong. A hand adjustment after a physical count is a legitimate movement with
no order behind it, and a reconciliation that "corrects" those is one that
silently deletes the stocktake. Only the three faults above are touched.

Everything is a dry run first. The report and the fix compute the same thing;
`apply=False` returns it without writing, so what you approve is what runs.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inventory import InventoryItem, InventoryMovement
from app.models.purchasing import SupplierPO
from app.models.user import User

# A PO in one of these states should have its goods counted in.
#
# The list is short on purpose and matches `stock_sync` exactly. `draft` has
# not been placed and `cancelled` has been withdrawn. `pending_approval` is the
# interesting exclusion: an order the director has not released may never be
# placed at all, and counting it would put goods on the shelf that no supplier
# was ever told to send — the same reason the ordinary path waits for `open`.
#
# Anything outside this list is left alone rather than guessed at. A status
# nobody here recognises is not evidence that goods arrived.
LIVE_PO_STATES = ("open", "received")

OPENING_REASON = "opening"
OPENING_REF = "reconcile:opening-balance"


async def _ledger_totals(db: AsyncSession) -> dict:
    """Sum of every movement, per item. One pass, not one query per item."""
    rows = (await db.execute(
        select(InventoryMovement.item_id,
               func.coalesce(func.sum(InventoryMovement.delta), 0),
               func.count(InventoryMovement.id))
        .group_by(InventoryMovement.item_id)
    )).all()
    return {r[0]: (float(r[1] or 0), int(r[2] or 0)) for r in rows}


async def reconcile(db: AsyncSession, *, apply: bool = False,
                    user: User | None = None) -> dict:
    """Report what disagrees, and optionally fix it.

    With `apply=False` nothing is written and the return value is the report.
    With `apply=True` the same findings are acted on and the return value says
    what was done. The two paths compute identically on purpose: a preview that
    is a separate implementation from the fix is a preview that eventually
    stops matching it.
    """
    items = (await db.scalars(select(InventoryItem))).all()
    totals = await _ledger_totals(db)

    drift: list[dict] = []
    openings: list[dict] = []

    for item in items:
        stored = float(item.current_stock or 0)
        ledger, moves = totals.get(item.id, (0.0, 0))

        if moves == 0:
            # Nothing has ever been written down for this part. A non-zero
            # figure here is an opening balance, not an error.
            if abs(stored) > 1e-9:
                openings.append({
                    "id": str(item.id), "sku": item.sku, "name": item.name,
                    "qty": stored,
                })
                if apply:
                    db.add(InventoryMovement(
                        item_id=item.id, delta=stored, reason=OPENING_REASON,
                        reference=OPENING_REF,
                        user_id=user.id if user else None,
                        notes="Opening balance — the figure predates the "
                              "movement ledger and had nothing explaining it.",
                    ))
            continue

        if abs(stored - ledger) > 1e-9:
            drift.append({
                "id": str(item.id), "sku": item.sku, "name": item.name,
                "was": stored, "now": ledger, "delta": ledger - stored,
                "movements": moves,
            })
            if apply:
                # The movements are the record; the total is the cache. No
                # movement is written — the ones on file already add to this.
                item.current_stock = ledger

    replayed = await _replay_missing_pos(db, apply=apply, user=user)

    if apply:
        await db.flush()

    return {
        "applied": apply,
        "checked_items": len(items),
        "drift": drift,
        "opening_balances": openings,
        "replayed_orders": replayed,
        "summary": {
            "totals_corrected": len(drift),
            "opening_balances_written": len(openings),
            "orders_counted_in": len(replayed),
            "nothing_to_do": not (drift or openings or replayed),
        },
    }


async def _receipted_quantities(db: AsyncSession, po) -> dict[int, float]:
    """What the goods receipts on this order say actually turned up, per line.

    Receipts accumulate — a second delivery is a second receipt, not an edit of
    the first — and each one carries the running total for the lines it covers,
    so the latest mention of a line wins. Same rule the receiving screen uses to
    pre-fill the form, and it has to be the same or the two disagree about what
    has arrived.
    """
    from app.models.purchasing import GoodsReceipt

    receipts = (await db.scalars(
        select(GoodsReceipt).where(GoodsReceipt.po_id == po.id)
        .order_by(GoodsReceipt.created_at.asc())
    )).all()
    out: dict[int, float] = {}
    for gr in receipts:
        for row in (gr.items or []):
            try:
                out[int(row.get("line_no"))] = float(row.get("qty") or 0)
            except (TypeError, ValueError):
                continue
    return out


async def _replay_missing_pos(db: AsyncSession, *, apply: bool,
                              user: User | None) -> list[dict]:
    """Supplier orders that are live but whose goods were never counted in.

    `_already_moved` is the same test the ordinary path uses before adding an
    order's goods, so an order this finds is exactly one that path would accept
    — which is why replaying goes through `receive_purchase_order` rather than
    writing movements here. A second mechanism for putting goods on a shelf is
    a second mechanism to keep in step.

    **Then the receipts are re-applied on top.** Replaying alone puts back what
    was *ordered*, and for an order that was only partly delivered that is the
    wrong number — it would overwrite a receipt saying five arrived with the
    ten somebody asked for, and do it while claiming to be a reconciliation.
    So if there are goods receipts on file, the same correction the receiving
    screen makes is made here: the shelf ends at what the receipts say, not at
    what the order asked for.
    """
    from app.services.stock_sync import (
        _already_moved, receive_purchase_order, sync_received,
    )

    pos = (await db.scalars(
        select(SupplierPO).where(SupplierPO.status.in_(LIVE_PO_STATES))
        .order_by(SupplierPO.created_at.asc())
    )).all()

    out: list[dict] = []
    for po in pos:
        if not (po.number or "").strip():
            continue
        if await _already_moved(db, po.number, "po_in"):
            continue
        lines = [i for i in (po.items or [])
                 if float(i.get("qty") or 0) > 0
                 and ((i.get("description") or i.get("name") or "").strip())]
        if not lines:
            # An order with nothing countable on it is not missing anything.
            continue

        ordered = sum(float(i.get("qty") or 0) for i in lines)
        receipted = await _receipted_quantities(db, po)
        # What the shelf will hold afterwards: the receipts where a line has
        # one, the ordered figure where it does not (nothing has been said
        # about that line yet, which is not the same as "none arrived").
        landing = sum(
            receipted.get(idx, float(line.get("qty") or 0))
            for idx, line in enumerate(po.items or [], start=1)
            if float(line.get("qty") or 0) > 0
            and ((line.get("description") or line.get("name") or "").strip())
        )
        out.append({
            "po_id": str(po.id), "number": po.number, "status": po.status,
            "lines": len(lines),
            "qty": landing,
            "ordered": ordered,
            "receipted_lines": len(receipted),
        })
        if apply:
            await receive_purchase_order(db, po, user)
            if receipted:
                await sync_received(db, po, receipted, user)
    return out

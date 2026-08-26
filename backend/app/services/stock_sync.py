"""Stock that follows the paperwork.

Asked for, across the inventory screen: *"Every purchasing PO: item become SKU
(number auto generate); Qty Order Become stock add; every Delivery order minus
the stock."*

Until now the inventory was a list somebody typed and then stopped typing.
Fifteen items, every one of them reading zero, while purchase orders and
delivery orders went past it all day carrying the actual quantities. A stock
figure nobody maintains is worse than no stock figure: people check it once,
find it wrong, and stop checking — and the page that says "check what's in
stock before promising delivery" is then a page that helps you promise wrong.

So the two documents that move goods move the number:

* an **open supplier PO** puts its lines into stock, creating the item — with
  a generated SKU — the first time a part is ordered;
* a **delivery order** takes them out again.

Two decisions worth stating.

**Stock rises when the PO is open, not when it is typed.** A PO a non-director
files sits at `pending_approval` until the director releases it, and may be
cancelled instead. Counting goods from an order nobody approved would put
stock on the shelf that no supplier was ever told to send.

**Nothing is invented on the way back.** Cancelling a PO or withdrawing a
delivery order reverses exactly the movements that reference it, so a
document that never happened leaves the count where it found it. That is why
every change is written as a movement with the document's number on it, and
never as a bare edit to the running total.

Matching is by name, normalised for case and spacing, because that is what
the two documents actually share — a PO line and an inventory item are both
"ATTACHMENT ; CHAIN 09061 ; 152X107X57MM", typed by different people on
different days.
"""

from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inventory import InventoryItem, InventoryMovement
from app.models.user import User

# Where a generated SKU series starts when there is nothing to continue from.
# Six digits from 100001 matches the numbering already in the company's list
# (100036, 100062, 100174 …) so generated and hand-entered items sit in one
# series rather than two.
_SKU_START = 100_000


def _key(name: str | None) -> str:
    """A part's name, as the thing to match two documents on."""
    return re.sub(r"\s+", " ", (name or "").strip()).lower()


async def _next_sku(db: AsyncSession) -> str:
    """One past the highest numeric SKU in use.

    Reads the maximum rather than counting rows: a count walks backwards the
    moment an item is deleted and hands the next part a SKU that is still on
    somebody's shelf label.
    """
    rows = (await db.scalars(select(InventoryItem.sku))).all()
    highest = _SKU_START
    for s in rows:
        digits = (s or "").strip()
        if digits.isdigit():
            highest = max(highest, int(digits))
    return str(highest + 1)


async def _item_for(db: AsyncSession, *, name: str, uom: str | None,
                    unit_cost: float | None, category: str | None = None,
                    supplier_hint: str | None = None) -> InventoryItem:
    """The inventory item this line is about, creating it if it is new."""
    key = _key(name)
    for it in (await db.scalars(select(InventoryItem))).all():
        if _key(it.name) == key:
            # A later order at a different price is the current price. Zero
            # means "not stated on this line", which must not wipe a price
            # somebody already knows.
            if unit_cost:
                it.unit_cost = float(unit_cost)
            if uom and not it.uom:
                it.uom = uom
            return it
    item = InventoryItem(
        sku=await _next_sku(db),
        name=(name or "").strip()[:255],
        category=category,
        uom=(uom or "pcs")[:20],
        unit_cost=float(unit_cost or 0),
        current_stock=0,
        supplier_hint=supplier_hint,
        is_active=True,
    )
    db.add(item)
    await db.flush()
    return item


async def _move(db: AsyncSession, item: InventoryItem, *, delta: float,
                reason: str, reference: str, user: User | None,
                notes: str | None = None) -> None:
    item.current_stock = float(item.current_stock or 0) + float(delta)
    db.add(InventoryMovement(
        item_id=item.id, delta=float(delta), reason=reason,
        reference=reference, user_id=user.id if user else None, notes=notes,
    ))


async def _already_moved(db: AsyncSession, reference: str, reason: str) -> bool:
    """Whether this document's effect on stock is currently standing.

    Not simply "has it ever moved stock": a PO that was cancelled and then
    reopened has both its original movements and their reversals on file, and
    the goods are back on order. Counting only the originals would refuse to
    put them back on the shelf and leave the count permanently short.
    """
    # One pass over the document's own movements rather than two counts of
    # the whole table. Both halves are the same narrow index lookup, so
    # asking for them together is a single seek instead of two scans.
    row = (await db.execute(
        select(
            func.count(func.nullif(InventoryMovement.reason != reason, True)),
            func.count(func.nullif(
                InventoryMovement.reason != f"{reason}_reversed", True)),
        ).where(InventoryMovement.reference == reference,
                InventoryMovement.reason.in_((reason, f"{reason}_reversed")))
    )).first()
    done, undone = (row[0] or 0, row[1] or 0) if row else (0, 0)
    return done > undone


async def receive_purchase_order(db: AsyncSession, po, user: User | None = None) -> list[str]:
    """Put an open supplier PO's lines into stock. Returns the SKUs touched."""
    ref = po.number
    if await _already_moved(db, ref, "po_in"):
        return []
    touched: list[str] = []
    changed = False
    lines = [dict(i) for i in (po.items or [])]
    for line in lines:
        qty = float(line.get("qty") or 0)
        name = line.get("description") or line.get("name")
        if qty <= 0 or not (name or "").strip():
            continue
        item = await _item_for(
            db, name=name, uom=line.get("uom"),
            unit_cost=line.get("unit_price") or line.get("unit_cost"),
        )
        await _move(db, item, delta=qty, reason="po_in", reference=ref,
                    user=user, notes=f"Ordered on {ref}")
        # The line now says which part of the catalogue it is, so the PO can
        # be read against the shelf without matching strings a second time.
        if line.get("sku") != item.sku:
            line["sku"] = item.sku
            changed = True
        touched.append(item.sku)
    if changed:
        po.items = lines
    await db.flush()
    return touched


async def issue_delivery_order(db: AsyncSession, do, user: User | None = None) -> list[str]:
    """Take a delivery order's lines back out of stock.

    Only for parts the catalogue already knows: a delivery order is not where
    a part is introduced, and creating an item here to immediately drive it
    negative would fill the list with entries nobody ordered.
    """
    ref = do.number
    if await _already_moved(db, ref, "do_out"):
        return []
    touched: list[str] = []
    items = (await db.scalars(select(InventoryItem))).all()
    by_key = {_key(i.name): i for i in items}
    for line in (do.items or []):
        qty = float(line.get("qty") or 0)
        item = by_key.get(_key(line.get("description")))
        if qty <= 0 or item is None:
            continue
        await _move(db, item, delta=-qty, reason="do_out", reference=ref,
                    user=user, notes=f"Delivered on {ref}")
        touched.append(item.sku)
    await db.flush()
    return touched


async def reverse(db: AsyncSession, reference: str, reason: str,
                  user: User | None = None) -> int:
    """Undo what a document did to the count, exactly.

    Applies the inverse of every movement carrying this document's number and
    writes each one down as its own movement, so the ledger reads as what
    happened rather than as a number that quietly changed.
    """
    if not await _already_moved(db, reference, reason):
        # Already reversed, or never applied. Reversing twice would take the
        # goods off the shelf a second time on a document that only moved
        # them once.
        return 0
    rows = (await db.scalars(
        select(InventoryMovement).where(
            InventoryMovement.reference == reference,
            InventoryMovement.reason == reason,
        )
    )).all()
    if not rows:
        return 0
    # Only the most recent application: a PO cancelled, reopened and
    # cancelled again has two sets of movements, and this cancel undoes one.
    per_item: dict = {}
    for m in rows:
        per_item[m.item_id] = m
    rows = list(per_item.values())
    done = 0
    for m in rows:
        item = await db.get(InventoryItem, m.item_id)
        if not item:
            continue
        await _move(db, item, delta=-float(m.delta), reason=f"{reason}_reversed",
                    reference=reference, user=user,
                    notes=f"Reversed — {reference} withdrawn")
        done += 1
    await db.flush()
    return done


async def stock_snapshot(db: AsyncSession, item_id: UUID) -> float:
    item = await db.get(InventoryItem, item_id)
    return float(item.current_stock or 0) if item else 0.0

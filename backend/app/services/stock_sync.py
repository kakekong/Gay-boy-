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

Three documents, three different jobs:

* a **submitted price request** puts the *product* in the catalogue and no
  quantity at all — a customer wanting something is not us having it;
* an **open supplier PO** puts its lines into stock, creating the item — with
  a generated SKU — if the price request has not already;
* a **delivery order** takes them out again.

Three decisions worth stating.

**A price request introduces the part; it never moves the count.** That split
is the point: quantity has exactly one source on the way in, the purchase
order, so there is never a question of whether a number was counted twice.

**Stock rises when the PO is open, not when it is typed.** A PO a non-director
files sits at `pending_approval` until the director releases it, and may be
cancelled instead. Counting goods from an order nobody approved would put
stock on the shelf that no supplier was ever told to send.

**Nothing is invented on the way back.** Cancelling a PO or withdrawing a
delivery order reverses exactly the movements that reference it, so a
document that never happened leaves the count where it found it. That is why
every change is written as a movement with the document's number on it, and
never as a bare edit to the running total.

Matching is by SKU where the line carries one, and by name where it does not.
The SKU is the exact answer — it is written onto the price request line when
the catalogue row is created, and travels from there onto the purchase order
and the delivery order. The name match is the fallback for everything typed
before that chain existed, or typed by hand: a PO line and an inventory item
are both "ATTACHMENT ; CHAIN 09061 ; 152X107X57MM", written by different
people on different days, and normalising case and spacing is all they share.
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
                    supplier_hint: str | None = None, sku: str | None = None,
                    link: str | None = None) -> InventoryItem:
    """The inventory item this line is about, creating it if it is new.

    A stated SKU wins over the name: it is the identifier somebody chose,
    and once a price request has put a part in the catalogue under one, that
    is what the later documents are about. The name match stays as the
    fallback, because a supplier PO typed by hand still only has the name.
    """
    wanted = (sku or "").strip()
    items = (await db.scalars(select(InventoryItem))).all()
    found = None
    if wanted:
        found = next((i for i in items if (i.sku or "").strip() == wanted), None)
    if found is None:
        key = _key(name)
        found = next((i for i in items if _key(i.name) == key), None)
    if found is not None:
        # A later order at a different price is the current price. Zero
        # means "not stated on this line", which must not wipe a price
        # somebody already knows.
        if unit_cost:
            found.unit_cost = float(unit_cost)
        if uom and not found.uom:
            found.uom = uom
        # Same for the details a price request supplies and a purchase order
        # does not: fill a gap, never overwrite an answer.
        if category and not found.category:
            found.category = category[:120]
        if link and not found.link:
            found.link = link[:1000]
        return found
    item = InventoryItem(
        sku=wanted[:40] or await _next_sku(db),
        name=(name or "").strip()[:255],
        category=(category or None) and category[:120],
        uom=(uom or "pcs")[:20],
        unit_cost=float(unit_cost or 0),
        current_stock=0,
        supplier_hint=supplier_hint,
        link=(link or None) and link[:1000],
        is_active=True,
    )
    db.add(item)
    await db.flush()
    return item


async def catalogue_from_price_request(db: AsyncSession, pr,
                                       user: User | None = None) -> list[str]:
    """Put a submitted price request's products into the catalogue — no stock.

    Asked for: *"when a price request is submitted put the product in the
    price request into the inventory and not the quantity. For quantity it
    comes from the purchasing PR."*

    That split is the whole design. A price request says a customer wants
    something; it does not say we have any. So this creates the item and
    writes **no movement at all** — the count stays where it was, which for
    a new part is zero. Stock arrives later, when purchasing opens a supplier
    PO for it, and leaves again on a delivery order. A price request that
    added quantity would put goods on the shelf that nobody has bought.

    The SKU is written back onto the request's own line, so from here on the
    request, the purchase order and the delivery order are all talking about
    the same catalogue row by identifier rather than by matching strings.
    """
    touched: list[str] = []
    lines = [dict(i) for i in (pr.items or [])]
    changed = False
    for line in lines:
        name = (line.get("description") or "").strip()
        if not name:
            continue
        item = await _item_for(
            db, name=name, uom=line.get("uom"), unit_cost=None,
            category=line.get("category"), sku=line.get("sku"),
            link=line.get("link"),
        )
        if line.get("sku") != item.sku:
            line["sku"] = item.sku
            changed = True
        touched.append(item.sku)
    if changed:
        pr.items = lines
    await db.flush()
    return touched


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
            category=line.get("category"), sku=line.get("sku"),
            link=line.get("link"),
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
    by_sku = {(i.sku or "").strip(): i for i in items if (i.sku or "").strip()}
    for line in (do.items or []):
        qty = float(line.get("qty") or 0)
        # By SKU where the line carries one — it came from the price request
        # that created the catalogue row, so it is the exact answer. The name
        # match stays for lines that predate a SKU or were typed by hand.
        item = by_sku.get((line.get("sku") or "").strip()) \
            or by_key.get(_key(line.get("description")))
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

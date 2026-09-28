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

Four documents, four different jobs:

* a **submitted price request** puts the *product* in the catalogue and no
  quantity at all — a customer wanting something is not us having it;
* an **open supplier PO** registers its lines in the catalogue, creating the
  item — with a generated SKU — if the price request has not already, and
  moves **no quantity**;
* **receiving** — the receiving work order — puts what actually turned up
  into stock: order ten, five arrive, and the shelf gains five. That is the
  moment the goods exist here, against the goods receipt that says so, and it
  is the moment the supplier is owed for them (utang usaha — see
  `record_receiving`);
* a **delivery order** takes them out again.

**Stock rises on receiving, not on ordering.** It used to rise when the PO
opened, so the count read "what we have plus what is on its way" and receiving
corrected it. That was asked to change: goods go into inventory when they are
received, against the paperwork of receiving, and a delivery order takes them
out. Existing stock was re-based once to what the receipts say
(`rebase_to_receipts`).

Three decisions worth stating.

**A price request introduces the part; it never moves the count.** That split
is the point: quantity has exactly one source on the way in, the purchase
order, so there is never a question of whether a number was counted twice.

**Stock rises when the PO is open, not when it is typed.** A PO a non-director
files sits at `pending_approval` until the director releases it, and may be
cancelled instead. Counting goods from an order nobody approved would put
stock on the shelf that no supplier was ever told to send.

**An open order is a commitment, and receiving is the correction.** The count
therefore reads "what we have plus what is on its way", which is the figure
somebody promising a delivery date actually needs. What it must never do is
stay at ten when five arrived, so receiving moves each line to the quantity in
the building — a correction against the same PO number, never a second
addition on top of the order's own.

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


def po_money(po) -> tuple[str, float | None]:
    """The currency a PO's prices are in, and its rupiah rate."""
    cur = (getattr(po, "currency", None) or "IDR").upper()
    if cur == "IDR":
        return "IDR", None
    rate = float(getattr(po, "fx_rate", None) or 0) or None
    return cur, rate


async def _item_for(db: AsyncSession, *, name: str, uom: str | None,
                    unit_cost: float | None, category: str | None = None,
                    supplier_hint: str | None = None, sku: str | None = None,
                    link: str | None = None, currency: str | None = None,
                    fx_rate: float | None = None) -> InventoryItem:
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
            # The price and its currency travel together — an RMB price must
            # never be left labelled as rupiah.
            found.cost_currency = (currency or "IDR").upper()
            found.cost_fx_rate = fx_rate if found.cost_currency != "IDR" else None
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
        cost_currency=(currency or "IDR").upper() if unit_cost else "IDR",
        cost_fx_rate=(fx_rate if unit_cost and (currency or "IDR").upper() != "IDR" else None),
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


async def receive_purchase_order(db: AsyncSession, po, user: User | None = None,
                                 *, move_stock: bool = False) -> list[str]:
    """Register an open supplier PO's lines in the catalogue. Returns the SKUs.

    Moves no quantity by default: goods enter stock when they are received
    (`sync_received`), not when they are ordered. `move_stock=True` keeps the
    old behaviour for anything that still needs it.
    """
    ref = po.number
    if move_stock and await _already_moved(db, ref, "po_in"):
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
            currency=po_money(po)[0], fx_rate=po_money(po)[1],
        )
        if move_stock:
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


async def po_contribution(db: AsyncSession, po) -> dict[UUID, float]:
    """What this purchase order currently contributes to each item's count.

    The net of every movement carrying the PO's number — the original `po_in`,
    any reversal, and every receiving correction since. Reading the net rather
    than tracking a separate figure is what makes syncing idempotent: run it
    twice and the second run computes a delta of zero, because the first run's
    movement is already part of the answer.
    """
    rows = (await db.execute(
        select(InventoryMovement.item_id,
               func.coalesce(func.sum(InventoryMovement.delta), 0))
        .where(InventoryMovement.reference == po.number)
        .group_by(InventoryMovement.item_id)
    )).all()
    return {r[0]: float(r[1] or 0) for r in rows}


async def sync_received(db: AsyncSession, po, received: dict[int, float],
                        user: User | None = None) -> list[dict]:
    """Put what actually turned up into stock.

    `received` maps a PO line number to the quantity now in the building for
    that line (a running total, not this delivery alone), and this moves each
    item to exactly that: `delta = received − whatever this PO has contributed
    so far`. Nothing has been contributed before the first receipt, so the
    first receipt adds everything that arrived; a second delivery adds the
    rest; a corrected count moves the difference either way. Running it twice
    moves nothing the second time.

    Lines absent from `received` are left alone — that is the difference
    between "five arrived" and "nothing has been said about this line yet", and
    conflating them would zero out every line somebody has not got to yet.

    Returns one row per line touched, saying what it did, because the caller
    has to show a person why their stock figure changed.
    """
    contribution = await po_contribution(db, po)
    lines = [dict(i) for i in (po.items or [])]
    out: list[dict] = []
    changed = False

    for idx, line in enumerate(lines, start=1):
        if idx not in received:
            continue
        qty_in = float(received[idx] or 0)
        if qty_in < 0:
            continue
        name = line.get("description") or line.get("name")
        if not (name or "").strip():
            continue
        item = await _item_for(
            db, name=name, uom=line.get("uom"),
            unit_cost=line.get("unit_price") or line.get("unit_cost"),
            category=line.get("category"), sku=line.get("sku"),
            link=line.get("link"),
            currency=po_money(po)[0], fx_rate=po_money(po)[1],
        )
        # A line whose part the PO has not moved yet contributes nothing, which
        # is the right starting point: the delta is then the whole receipt.
        have = contribution.get(item.id, 0.0)
        delta = qty_in - have
        if abs(delta) > 1e-9:
            await _move(
                db, item, delta=delta, reason="gr_sync", reference=po.number,
                user=user,
                notes=(f"Received {qty_in:g} of {float(line.get('qty') or 0):g} "
                       f"on {po.number}"),
            )
            # Keep the running figure right for a second line pointing at the
            # same part — two lines of the same item on one order is ordinary.
            contribution[item.id] = qty_in
        if line.get("sku") != item.sku:
            line["sku"] = item.sku
            changed = True
        out.append({
            "line_no": idx, "sku": item.sku, "name": item.name,
            "ordered": float(line.get("qty") or 0), "received": qty_in,
            "delta": delta, "stock_now": float(item.current_stock or 0),
        })

    if changed:
        po.items = lines
    await db.flush()
    return out


async def rebase_to_receipts(db: AsyncSession, user: User | None = None) -> dict:
    """Re-base every order's stock contribution on its goods receipts.

    The one-off move from "stock rises when the PO opens" to "stock rises
    when it is received". Every order ends contributing exactly what its
    receipts say arrived — nothing for an order with no receipt, however long
    it has been open — written as movements against the order's number like
    every other change, so the ledger shows the re-basing rather than a
    number that jumped.
    """
    from app.models.purchasing import GoodsReceipt, SupplierPO

    pos = (await db.scalars(select(SupplierPO))).all()
    changed_pos = moved = 0
    for po in pos:
        if not (po.number or "").strip():
            continue
        receipts = (await db.scalars(
            select(GoodsReceipt).where(GoodsReceipt.po_id == po.id)
            .order_by(GoodsReceipt.created_at.asc()))).all()
        received: dict[int, float] = {}
        for gr in receipts:
            for row in (gr.items or []):
                try:
                    received[int(row.get("line_no"))] = float(row.get("qty") or 0)
                except (TypeError, ValueError):
                    continue
        target: dict = {}
        if po.status != "cancelled":
            for idx, line in enumerate(po.items or [], start=1):
                name = line.get("description") or line.get("name")
                if not (name or "").strip():
                    continue
                qty_in = received.get(idx, 0.0)
                item = await _item_for(
                    db, name=name, uom=line.get("uom"),
                    unit_cost=line.get("unit_price") or line.get("unit_cost"),
                    category=line.get("category"), sku=line.get("sku"),
                    link=line.get("link"),
                    currency=po_money(po)[0], fx_rate=po_money(po)[1],
                )
                target[item.id] = target.get(item.id, 0.0) + qty_in
        have = await po_contribution(db, po)
        touched = False
        for item_id in set(have) | set(target):
            delta = target.get(item_id, 0.0) - have.get(item_id, 0.0)
            if abs(delta) < 1e-9:
                continue
            item = await db.get(InventoryItem, item_id)
            if item is None:
                continue
            await _move(db, item, delta=delta, reason="gr_sync", reference=po.number,
                        user=user,
                        notes=f"Re-based to received on {po.number} — stock "
                              "now enters on receiving, not on ordering")
            moved += 1
            touched = True
        changed_pos += touched
    await db.flush()
    return {"orders": changed_pos, "movements": moved}


async def withdraw_purchase_order(db: AsyncSession, po,
                                  user: User | None = None) -> int:
    """Take back everything this order put on the shelf — however much arrived.

    Cancelling used to reverse the `po_in` movements alone, which was exact
    while an order's only effect was its ordered quantity. It is not any more:
    order ten, receive five, cancel, and reversing the ten against a shelf
    holding five drives the count to minus five.

    So this reverses the *net*: whatever the order currently contributes, it
    contributes nothing afterwards. Written as its own movement per item, like
    everything else here, so the ledger says the order was withdrawn rather
    than the number quietly changing.

    Reopening the order re-adds the ordered quantity (`receive_purchase_order`)
    and not the receiving corrections, which are a fact about a delivery rather
    than about the order. Syncing receiving again restores them — it computes
    its delta from the net, so it lands on the right figure from wherever it
    starts.
    """
    contribution = await po_contribution(db, po)
    done = 0
    for item_id, net in contribution.items():
        if abs(net) < 1e-9:
            continue
        item = await db.get(InventoryItem, item_id)
        if item is None:
            continue
        await _move(db, item, delta=-net, reason="po_in_reversed",
                    reference=po.number, user=user,
                    notes=f"Reversed — {po.number} withdrawn")
        done += 1
    await db.flush()
    return done


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


async def backfill_item_currency(db: AsyncSession) -> int:
    """Label existing items with the currency their price was bought in.

    Items priced off a foreign-currency order before the currency was kept
    carry that order's number as a bare "rupiah" figure. Each item takes the
    currency and rate of the latest supplier PO line naming it (by SKU, else
    by name) whose price is the one the item holds.
    """
    from app.models.purchasing import SupplierPO

    pos = (await db.scalars(
        select(SupplierPO).where(SupplierPO.currency != "IDR")
        .order_by(SupplierPO.created_at.asc()))).all()
    if not pos:
        return 0
    items = (await db.scalars(select(InventoryItem))).all()
    by_sku = {(i.sku or "").strip(): i for i in items if (i.sku or "").strip()}
    by_name = {_key(i.name): i for i in items}
    fixed = 0
    for po in pos:                         # oldest first: the latest order wins
        cur, rate = po_money(po)
        for line in (po.items or []):
            item = by_sku.get((line.get("sku") or "").strip()) \
                or by_name.get(_key(line.get("description") or line.get("name")))
            price = float(line.get("unit_price") or line.get("unit_cost") or 0)
            if item is None or not price:
                continue
            if abs(float(item.unit_cost or 0) - price) < 0.005 \
                    and (item.cost_currency or "IDR") == "IDR":
                item.cost_currency = cur
                item.cost_fx_rate = rate
                fixed += 1
    await db.flush()
    return fixed

"""Merging duplicate catalogue items — preview first, then the merge.

The catalogue gains a row for every part a price request or purchase order
names, matched by SKU or by name. Before the price request suggested parts
already on file, the same part typed two ways ("BEARING 6205" and
"Bearing-6205") became two rows, each with part of the stock and part of the
history. This finds those, shows exactly what merging them would change, and
does it:

* every stock movement of a duplicate moves onto the kept item, so its
  history page shows one unbroken story, and the stock is added together;
* every document line that names a duplicate — by its SKU, or by its name on
  a line with no SKU — is rewritten to the kept item's SKU: price requests,
  quotations, customer POs, supplier price requests, purchase requests,
  supplier POs, goods receipts and delivery orders;
* blanks on the kept item (category, link, location, a cost, a reorder
  point…) are filled from the duplicate, never overwritten;
* the duplicate's SKU and name are kept as aliases on the kept item, so a
  line typed later from an old label or spelling still lands on it;
* the duplicate is deleted, and a zero movement on the kept item records the
  merge in its history.

`plan()` computes all of that without writing anything; `apply()` runs the
same computation and writes it. The preview is therefore the merge.
"""

from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inventory import InventoryItem, InventoryMovement
from app.services.stock_sync import _key, loose_key

# (model path, label, how to link to it)
_DOCS = (
    ("app.models.price_request:PriceRequest", "Price request",
     lambda d: f"/price-requests?open={d.id}"),
    ("app.models.customer_po:CustomerPO", "Customer PO",
     lambda d: f"/customer-pos/{d.id}"),
    ("app.models.purchasing:SupplierPriceRequest", "Supplier price request",
     lambda d: f"/purchasing/price-requests/{d.id}"),
    ("app.models.purchasing:PurchaseRequest", "Purchase request", lambda d: None),
    ("app.models.purchasing:SupplierPO", "Supplier PO",
     lambda d: f"/purchase-orders/{d.id}"),
    ("app.models.purchasing:GoodsReceipt", "Goods receipt",
     lambda d: f"/purchase-orders/{d.po_id}"),
    ("app.models.operation:DeliveryOrder", "Delivery order",
     lambda d: f"/deliveries/{d.id}"),
)

# Filled on the kept item when it has nothing and the duplicate has something.
_FILL = ("category", "link", "location", "supplier_hint", "notes")


def _model(path: str):
    mod, name = path.split(":")
    return getattr(__import__(mod, fromlist=[name]), name)


def _row(i: InventoryItem, moves: int) -> dict:
    return {"id": str(i.id), "sku": i.sku, "name": i.name, "category": i.category,
            "uom": i.uom, "current_stock": float(i.current_stock or 0),
            "movements": moves,
            "created_at": i.created_at.isoformat() if i.created_at else None}


async def _move_counts(db: AsyncSession, ids) -> dict:
    if not ids:
        return {}
    return dict((await db.execute(
        select(InventoryMovement.item_id, func.count(InventoryMovement.id))
        .where(InventoryMovement.item_id.in_(list(ids)))
        .group_by(InventoryMovement.item_id))).all())


async def find_duplicates(db: AsyncSession) -> list[dict]:
    """Active items whose names are the same once case, spacing and
    punctuation are ignored. The suggested item to keep is the one with the
    most history (then the oldest) — it is the one people have been using."""
    items = (await db.scalars(
        select(InventoryItem).where(InventoryItem.is_active.is_(True)))).all()
    groups: dict[str, list[InventoryItem]] = defaultdict(list)
    for i in items:
        k = loose_key(i.name)
        if k:
            groups[k].append(i)
    dupes = [g for g in groups.values() if len(g) > 1]
    moves = await _move_counts(db, [i.id for g in dupes for i in g])
    out = []
    for g in dupes:
        g.sort(key=lambda i: (-moves.get(i.id, 0), i.created_at or 0))
        out.append({"keep_id": str(g[0].id),
                    "items": [_row(i, moves.get(i.id, 0)) for i in g]})
    out.sort(key=lambda x: x["items"][0]["name"].lower())
    return out


class MergeError(ValueError):
    pass


async def _load(db: AsyncSession, keep_id: UUID, merge_ids: list[UUID]):
    ids = [m for m in dict.fromkeys(merge_ids) if m != keep_id]
    if not ids:
        raise MergeError("Pick at least one item to merge into the one being kept.")
    keep = await db.get(InventoryItem, keep_id)
    if keep is None:
        raise MergeError("The item to keep no longer exists.")
    dups = [await db.get(InventoryItem, m) for m in ids]
    if any(d is None for d in dups):
        raise MergeError("One of the items to merge no longer exists — refresh and try again.")
    return keep, dups


async def _document_changes(db: AsyncSession, keep: InventoryItem,
                            dups: list[InventoryItem], *, write: bool) -> list[dict]:
    """Every document line naming a duplicate, rewritten to the kept SKU."""
    skus = {(d.sku or "").strip() for d in dups if (d.sku or "").strip()}
    names = {_key(d.name) for d in dups} - {_key(keep.name)}
    changed: list[dict] = []

    def fix(line: dict) -> bool:
        s = (line.get("sku") or "").strip()
        if s and s in skus:
            line["sku"] = keep.sku
            return True
        if not s and _key(line.get("description") or line.get("name")) in names:
            line["sku"] = keep.sku
            return True
        return False

    for path, label, link in _DOCS:
        M = _model(path)
        for doc in (await db.scalars(select(M))).all():
            lines = [dict(x) for x in (doc.items or []) if isinstance(x, dict)]
            n = sum(1 for ln in lines if fix(ln))
            if not n:
                continue
            if write:
                doc.items = lines
            number = getattr(doc, "number", None)
            if number is None and path.endswith("GoodsReceipt"):
                from app.models.purchasing import SupplierPO
                po = await db.get(SupplierPO, doc.po_id)
                number = f"receipt for {po.number}" if po else "receipt"
            changed.append({"type": label, "number": number or str(doc.id)[:8],
                            "link": link(doc), "lines": n})

    # Quotation lines keep their SKU in a column, not a JSON list.
    from app.models.quotation import Quotation, QuotationItem
    q_lines = (await db.scalars(select(QuotationItem))).all()
    by_quote: dict = defaultdict(int)
    for it in q_lines:
        s = (it.sku or "").strip()
        if (s and s in skus) or (not s and _key(it.description) in names):
            by_quote[it.quotation_id] += 1
            if write:
                it.sku = keep.sku
    for qid, n in by_quote.items():
        q = await db.get(Quotation, qid)
        changed.append({"type": "Quotation", "number": q.number if q else str(qid)[:8],
                        "link": f"/quotations/{qid}", "lines": n})
    return changed


async def plan(db: AsyncSession, keep_id: UUID, merge_ids: list[UUID],
               *, write: bool = False, user=None) -> dict:
    """What merging `merge_ids` into `keep_id` changes. With `write`, does it."""
    keep, dups = await _load(db, keep_id, merge_ids)
    moves = await _move_counts(db, [keep.id, *[d.id for d in dups]])
    stock_after = float(keep.current_stock or 0) + sum(float(d.current_stock or 0) for d in dups)

    fills: dict[str, object] = {}
    for f in _FILL:
        if not getattr(keep, f):
            v = next((getattr(d, f) for d in dups if getattr(d, f)), None)
            if v:
                fills[f] = v
    if not float(keep.unit_cost or 0):
        src = next((d for d in dups if float(d.unit_cost or 0)), None)
        if src:
            fills["unit_cost"] = float(src.unit_cost)
            fills["cost_currency"] = src.cost_currency
            fills["cost_fx_rate"] = float(src.cost_fx_rate) if src.cost_fx_rate else None
    for f in ("reorder_point", "reorder_qty"):
        if not float(getattr(keep, f) or 0):
            v = max((float(getattr(d, f) or 0) for d in dups), default=0)
            if v:
                fills[f] = v

    warnings = []
    units = {(x.uom or "").lower() for x in [keep, *dups]}
    if len(units) > 1:
        warnings.append(
            f"The units differ ({', '.join(sorted(units))}). Stock is added as it "
            f"stands and counted in {keep.uom} — check these are the same part "
            "counted the same way.")
    cats = {x.category for x in [keep, *dups] if x.category}
    if len(cats) > 1:
        warnings.append(f"The categories differ ({', '.join(sorted(cats))}); "
                        f"the kept item stays {keep.category or 'uncategorised'}.")

    documents = await _document_changes(db, keep, dups, write=write)
    aliases = list(keep.aliases or [])
    for d in dups:
        aliases.append({"sku": d.sku, "name": d.name})
        aliases.extend(d.aliases or [])

    result = {
        "keep": _row(keep, moves.get(keep.id, 0)),
        "merge": [_row(d, moves.get(d.id, 0)) for d in dups],
        "after": {"sku": keep.sku, "name": keep.name, "uom": keep.uom,
                  "current_stock": round(stock_after, 4),
                  "movements": sum(moves.get(i, 0) for i in [keep.id, *[d.id for d in dups]]) + 1,
                  "fills": fills,
                  "aliases": [a for a in aliases if a.get("sku") or a.get("name")]},
        "documents": documents,
        "warnings": warnings,
    }
    if not write:
        return result

    await db.execute(update(InventoryMovement)
                     .where(InventoryMovement.item_id.in_([d.id for d in dups]))
                     .values(item_id=keep.id))
    for f, v in fills.items():
        setattr(keep, f, v)
    keep.current_stock = stock_after
    keep.aliases = result["after"]["aliases"]
    note = "Merged into this item: " + "; ".join(
        f"{d.sku} {d.name} (stock {float(d.current_stock or 0):g}, "
        f"{moves.get(d.id, 0)} movements)" for d in dups)
    db.add(InventoryMovement(item_id=keep.id, delta=0, reason="merge",
                             reference=keep.sku, user_id=user.id if user else None,
                             notes=note[:2000]))
    for d in dups:
        await db.delete(d)
    await db.flush()
    return result

"""Utang usaha for orders received before receiving started posting it.

Receiving a purchasing PO now posts what arrived as owed (Persediaan up,
Utang Usaha up) and adds it to the order's `payable_amount`. Orders received
before that have goods receipts on file and nothing owed on them, so the
payables list would show them as not received. This brings them in line
once: each such order gets the value of what its receipts say arrived, posted
to the ledger on the date of its latest receipt, exactly as a receipt today
would have done.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def backfill_payables(db: AsyncSession) -> dict:
    from app.models.purchasing import GoodsReceipt, Supplier, SupplierPO
    from app.services.ledger import post_goods_receipt

    pos = (await db.scalars(
        select(SupplierPO).where(SupplierPO.status != "cancelled",
                                 SupplierPO.payable_amount == 0))).all()
    done = 0
    total = 0.0
    for po in pos:
        receipts = (await db.scalars(
            select(GoodsReceipt).where(GoodsReceipt.po_id == po.id)
            .order_by(GoodsReceipt.created_at.asc()))).all()
        if not receipts:
            continue
        received: dict[int, float] = {}
        last: date | None = None
        for gr in receipts:
            last = gr.received_at or last
            for row in (gr.items or []):
                try:
                    received[int(row.get("line_no"))] = float(row.get("qty") or 0)
                except (TypeError, ValueError):
                    continue
        rate = 1.0
        if (po.currency or "IDR").upper() != "IDR":
            rate = float(po.fx_rate or 0) or 1.0
        lines = list(po.items or [])
        value = 0.0
        for line_no, qty in received.items():
            if 1 <= line_no <= len(lines):
                ln = lines[line_no - 1]
                value += qty * float(ln.get("unit_price") or ln.get("unit_cost") or 0) * rate
        value = round(value, 2)
        if value <= 0:
            continue
        sup = await db.get(Supplier, po.supplier_id) if po.supplier_id else None
        po.payable_amount = value
        await post_goods_receipt(
            db, value=value, entry_date=last or date.today(), po_number=po.number,
            supplier_name=sup.name if sup else None, receipt_id=receipts[-1].id)
        done += 1
        total += value
    await db.flush()
    return {"orders": done, "value": round(total, 2)}

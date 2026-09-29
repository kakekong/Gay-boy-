"""Goods arriving: stock in, a goods receipt filed, the supplier owed.

One path for every way goods are recorded as arrived — the receiving panel,
completing the receiving work order, and a job reaching a stage that cannot
happen without the goods (QC or later). The last is also how existing jobs
are brought in line: a project already past receiving whose orders were
never received gets them received now (`sync_past_receiving`).
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

# A job at any of these stages has had its goods in the building: QC checks
# them, packaging boxes them, delivery ships them.
PAST_RECEIVING = ("qc", "packaging", "delivered", "invoiced", "paid", "closed")


async def pos_for_project(db: AsyncSession, project_id: UUID) -> list:
    """Every supplier PO feeding this job — single-job and shared alike."""
    from app.models.purchasing import SupplierPO

    rows = (await db.scalars(
        select(SupplierPO).where(SupplierPO.project_id == project_id)
    )).all()
    seen = {p.id for p in rows}
    # A vendor order covering several jobs names them all in `project_ids`; it
    # still has to appear on each one's receiving list, or half a shipment
    # becomes invisible to the job waiting for it.
    shared = (await db.scalars(
        select(SupplierPO).where(
            SupplierPO.project_ids.contains([str(project_id)])
        )
    )).all()
    return list(rows) + [p for p in shared if p.id not in seen]


def receipt_value(po, moved: list[dict]) -> float:
    """Rupiah value of what this receipt changed: Σ delta × unit price × rate."""
    rate = 1.0
    if (po.currency or "IDR").upper() != "IDR":
        rate = float(po.fx_rate or 0) or 1.0
    lines = list(po.items or [])
    total = 0.0
    for m in moved:
        idx = int(m.get("line_no") or 0) - 1
        if not (0 <= idx < len(lines)):
            continue
        unit = float(lines[idx].get("unit_price") or lines[idx].get("unit_cost") or 0)
        total += float(m.get("delta") or 0) * unit * rate
    return round(total, 2)


async def receive_goods(db: AsyncSession, po, received: dict[int, float],
                         when, user: User):
    """Record a receipt: stock in, a goods receipt filed, utang usaha owed.

    The one path goods take into the building — the receiving panel and
    completing the receiving work order both come through here.
    """
    from datetime import date as date_t

    from app.models.purchasing import GoodsReceipt
    from app.services.stock_sync import sync_received

    moved = await sync_received(db, po, received, user)
    gr = GoodsReceipt(
        po_id=po.id,
        received_at=when or date_t.today(),
        items=[{"line_no": m["line_no"], "sku": m["sku"], "name": m["name"],
                "ordered": m["ordered"], "qty": m["received"]} for m in moved],
        status="received",
    )
    db.add(gr)
    # The board should show the order has started arriving. A partial delivery
    # is still an arrival — what is outstanding is visible on the lines.
    if po.status in ("open", "pending_approval"):
        po.status = "received"
    await db.flush()

    # Received goods are owed for: utang usaha, for the value of what arrived
    # (the quantity that moved × the line's price, in rupiah). It lands in
    # finance's payables list and the ledger — Persediaan up, Utang Usaha up.
    payable = receipt_value(po, moved)
    if abs(payable) >= 0.005:
        from app.models.purchasing import Supplier
        from app.services.ledger import post_goods_receipt
        sup = await db.get(Supplier, po.supplier_id) if po.supplier_id else None
        po.payable_amount = round(float(po.payable_amount or 0) + payable, 2)
        await post_goods_receipt(
            db, value=payable, entry_date=gr.received_at or date_t.today(),
            po_number=po.number, supplier_name=sup.name if sup else None,
            receipt_id=gr.id, created_by=user.id if user else None)
        await db.flush()
    return moved, gr, payable


async def receive_rest(db: AsyncSession, project_id, user: User | None,
                       when: date | None = None) -> list[dict]:
    """Completing the receiving work order receives what nobody recorded.

    The receiving panel is where a short delivery gets counted line by line.
    But ticking the receiving work order complete says "the goods are in",
    and until now it moved nothing — so an order for 200 that was ticked off
    here never reached the shelf, and the delivery order that shipped 100 of
    it had nothing to come out of. Every line on this job's supplier orders
    with no receipt yet is received at its ordered quantity; lines somebody
    already counted are left exactly as they were counted.
    """
    from app.services.stock_reconcile import _receipted_quantities

    out = []
    for po in await pos_for_project(db, project_id):
        if po.status in ("cancelled", "draft", "pending_approval"):
            continue
        have = await _receipted_quantities(db, po)
        rest = {idx: float(line.get("qty") or 0)
                for idx, line in enumerate(po.items or [], start=1)
                if idx not in have and float(line.get("qty") or 0) > 0
                and (line.get("project_id") in (None, str(project_id)))}
        if not rest:
            continue
        moved, gr, payable = await receive_goods(db, po, rest, when, user)
        out.append({"po_number": po.number, "lines": len(rest),
                    "payable_added": round(payable, 2)})
    return out




async def receive_if_past(db: AsyncSession, project, user: User | None) -> list[dict]:
    """A job that has reached QC or later has had its goods in: receive
    whatever on its supplier orders nobody recorded. A no-op otherwise, and
    a no-op the second time — lines with a receipt are never touched."""
    if project is None or (project.status or "") not in PAST_RECEIVING:
        return []
    return await receive_rest(db, project.id, user)


async def sync_past_receiving(db: AsyncSession) -> dict:
    """Bring existing jobs in line: every project already past receiving —
    at QC or later, or with its receiving work order ticked complete — gets
    the supplier-order lines nobody recorded received now, at their ordered
    quantity: into stock, and owed to the supplier. Receipts are dated when
    the receiving work order was completed where there is one."""
    from app.models.operation import Project, WorkOrder

    done_wo = {w.project_id: w.completed_at for w in (await db.scalars(
        select(WorkOrder).where(WorkOrder.stage == "receiving",
                                WorkOrder.completed_at.is_not(None)))).all()}
    projects = (await db.scalars(select(Project).where(
        Project.is_deleted.is_(False),
        (Project.status.in_(PAST_RECEIVING)) | (Project.id.in_(list(done_wo) or [None]))
    ))).all()
    orders = lines_value = 0
    for p in projects:
        when = done_wo.get(p.id)
        got = await receive_rest(db, p.id, None, when.date() if when else None)
        orders += len(got)
        lines_value += sum(x["payable_added"] for x in got)
    await db.flush()
    return {"projects": len(projects), "orders_received": orders,
            "owed_added": round(lines_value, 2)}

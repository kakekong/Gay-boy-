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


async def receive_po_rest(db: AsyncSession, po, user: User | None,
                          when: date | None = None) -> dict | None:
    """Receive every line of one order that has no receipt yet, at its
    ordered quantity. For an order marked received (or closed) by hand, and
    for orders with no project — which have no receiving work order to go
    through. Lines already counted are left as counted."""
    from app.services.stock_reconcile import _receipted_quantities

    if po.status in ("cancelled", "draft"):
        return None
    have = await _receipted_quantities(db, po)
    rest = {idx: float(line.get("qty") or 0)
            for idx, line in enumerate(po.items or [], start=1)
            if idx not in have and float(line.get("qty") or 0) > 0}
    if not rest:
        return None
    moved, gr, payable = await receive_goods(db, po, rest, when, user)
    return {"po_number": po.number, "lines": len(rest),
            "payable_added": round(payable, 2)}


async def sync_orders_marked_received(db: AsyncSession) -> dict:
    """Orders set to received/closed by hand, with lines never received —
    receive those lines, once. Their status said the goods were in; the
    stock and utang usaha now say so too."""
    from app.models.purchasing import SupplierPO

    pos = (await db.scalars(select(SupplierPO).where(
        SupplierPO.status.in_(("received", "closed"))))).all()
    n, owed = 0, 0.0
    for po in pos:
        got = await receive_po_rest(db, po, None)
        if got:
            n += 1
            owed += got["payable_added"]
    await db.flush()
    return {"orders": n, "owed_added": round(owed, 2)}


async def receive_by_description(db: AsyncSession, po, items: list[dict],
                                 when: date | None, user: User | None):
    """The purchasing "Receive goods" form: lines named by description (or
    SKU) with the quantity that arrived *this time*. Matched to the order's
    lines and added on top of what was already received, then recorded
    through the same path as everything else."""
    import re

    from app.services.stock_reconcile import _receipted_quantities

    def key(x) -> str:
        return re.sub(r"\s+", " ", (x or "").strip()).lower()

    lines = list(po.items or [])
    have = await _receipted_quantities(db, po)
    received: dict[int, float] = {}
    for it in items or []:
        qty = float(it.get("qty") or 0)
        if qty <= 0:
            continue
        want_sku = (it.get("sku") or "").strip()
        want = key(it.get("description"))
        idx = next((i for i, ln in enumerate(lines, start=1)
                    if (want_sku and (ln.get("sku") or "").strip() == want_sku)
                    or key(ln.get("description") or ln.get("name")) == want), None)
        if idx is None:
            continue
        base = received.get(idx, have.get(idx, 0.0))
        received[idx] = base + qty
    if not received:
        return None
    return await receive_goods(db, po, received, when, user)


async def po_status_changed(db: AsyncSession, po, was_status: str | None,
                            user: User | None) -> dict | None:
    """What a supplier PO's status change does to stock and utang usaha —
    one place for the director's direct edit and an approved request, which
    used to disagree (an approved cancellation left the goods on the shelf).

    * cancelled → whatever the order put on the shelf comes off it;
    * reopened from cancelled / released → its parts are (re)registered;
    * set to received or closed by hand → every line nobody received is
      received now, so the status and the stock and the money agree.
    """
    from app.services.stock_sync import receive_purchase_order, withdraw_purchase_order

    now = po.status
    if now == was_status:
        return None
    if now == "cancelled":
        await withdraw_purchase_order(db, po, user)
        return {"withdrawn": True}
    if now == "open" and was_status in ("cancelled", "pending_approval"):
        await receive_purchase_order(db, po, user)
        return {"registered": True}
    if now in ("received", "closed"):
        return await receive_po_rest(db, po, user)
    return None


async def sync_delivery_stock(db: AsyncSession) -> dict:
    """Delivery orders whose goods never came off the shelf — raised by the
    older endpoint with no lines, or whose lines didn't match an item before
    part codes were filled in. Take them out now, matched by part code."""
    from app.models.operation import DeliveryOrder, Project
    from app.services.item_codes import fill_item_codes
    from app.services.stock_sync import _already_moved, issue_delivery_order

    dos = (await db.scalars(select(DeliveryOrder))).all()
    n = 0
    for d in dos:
        if not (d.items or []) or await _already_moved(db, d.number, "do_out"):
            continue
        p = await db.get(Project, d.project_id) if d.project_id else None
        d.items = await fill_item_codes(db, list(d.items), p, by_position=False)
        if await issue_delivery_order(db, d, None):
            n += 1
    await db.flush()
    return {"delivery_orders": n}

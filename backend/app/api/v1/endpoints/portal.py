"""Customer + Supplier portals.

Customers see their own quotations, projects, invoices, and can approve
drawings via this scoped portal — no access to the rest of the system.

Suppliers see purchase requests / RFQs / supplier POs addressed to them,
and can upload invoice / drawing / bill / delivery (landing) documents
that flow back to internal staff.
"""

from datetime import UTC, date, datetime
from uuid import UUID
import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.permissions import Role
from app.models.attachment import Attachment
from app.models.crm import Customer
from app.models.finance import Invoice
from app.models.operation import (
    DeliveryOrder,
    Drawing,
    Project,
    advance_project_status,
)
from app.models.purchasing import PurchaseRequest, RFQ, SupplierPO
from app.models.quotation import Quotation
from app.models.user import User
from app.services import storage

router = APIRouter()


# ─── Customer portal ─────────────────────────────────────────────────────────

def _require_customer(me: User) -> UUID:
    if Role(me.role) != Role.CUSTOMER:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Customer portal only")
    if not me.linked_customer_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "This customer account has no linked customer record")
    return me.linked_customer_id


@router.get("/customer/me")
async def customer_me(
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    cid = _require_customer(me)
    c = await db.get(Customer, cid)
    if not c:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return {
        "id": str(c.id), "company_name": c.company_name, "industry": c.industry,
        "pic_name": c.pic_name, "phone": c.phone, "email": c.email,
        "delivery_address": c.delivery_address,
    }


@router.get("/customer/quotations")
async def customer_quotations(
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    cid = _require_customer(me)
    rows = (await db.scalars(
        select(Quotation).where(Quotation.customer_id == cid)
        .order_by(Quotation.created_at.desc())
    )).all()
    return [
        {
            "id": str(q.id), "number": q.number, "status": q.status,
            "variant": q.variant, "total": float(q.total or 0),
            "discount_pct": float(q.discount_pct or 0),
            "valid_until": q.valid_until, "created_at": q.created_at,
        }
        for q in rows
    ]


@router.get("/customer/projects")
async def customer_projects(
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    cid = _require_customer(me)
    projects = (await db.scalars(
        select(Project).where(Project.customer_id == cid, Project.is_deleted.is_(False))
        .order_by(Project.created_at.desc())
    )).all()
    out = []
    for p in projects:
        deliveries = (await db.scalars(
            select(DeliveryOrder).where(DeliveryOrder.project_id == p.id)
        )).all()
        drawings = (await db.scalars(
            select(Drawing).where(Drawing.project_id == p.id)
            .order_by(Drawing.revision.desc())
        )).all()
        invoices = (await db.scalars(
            select(Invoice).where(Invoice.project_id == p.id)
        )).all()
        out.append({
            "id": str(p.id), "code": p.code, "status": p.status,
            "po_number": p.po_number, "po_value": float(p.po_value or 0),
            "target_delivery": p.target_delivery,
            "actual_delivery": p.actual_delivery,
            "is_import": p.is_import,
            "origin_location": p.origin_location,
            "est_ship_from_origin": p.est_ship_from_origin,
            "act_ship_from_origin": p.act_ship_from_origin,
            "est_arrive_our_warehouse": p.est_arrive_our_warehouse,
            "act_arrive_our_warehouse": p.act_arrive_our_warehouse,
            "est_arrive_customer": p.est_arrive_customer,
            "act_arrive_customer": p.act_arrive_customer,
            "deliveries": [
                {"id": str(d.id), "number": d.number, "status": d.status,
                 "tracking_no": d.tracking_no, "courier": d.courier,
                 "delivered_at": d.delivered_at}
                for d in deliveries
            ],
            "drawings": [
                {"id": str(d.id), "revision": d.revision, "status": d.status,
                 "file_url": d.file_url, "customer_decision_at": d.customer_decision_at}
                for d in drawings
            ],
            "invoices": [
                {"id": str(i.id), "number": i.number, "due_date": i.due_date,
                 "total": float(i.total or 0), "status": i.status}
                for i in invoices
            ],
        })
    return out


@router.post("/customer/drawings/{drawing_id}/decide")
async def customer_decide_drawing(
    drawing_id: UUID,
    decision: str,                 # 'approve' | 'request_revision'
    notes: str | None = None,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    cid = _require_customer(me)
    d = await db.get(Drawing, drawing_id)
    if not d:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    project = await db.get(Project, d.project_id)
    if not project or project.customer_id != cid:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your drawing")
    if decision == "approve":
        d.status = "approved"
        # The customer's sign-off is the source of truth for the drawing
        # review — staff (director included) can't change it. Reflect it in
        # the project's read-only status by advancing it to drawing_approved.
        advance_project_status(project, "drawing_approved")
    elif decision == "request_revision":
        d.status = "revision_requested"
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "decision must be approve|request_revision")
    now = datetime.now(UTC)
    d.customer_decision_at = now
    d.decided_by = me.id
    d.decided_at = now
    if notes:
        d.notes = ((d.notes or "") + f"\n[{me.full_name}] {notes}").strip()
    return {"ok": True, "drawing_id": str(d.id), "status": d.status}


# ─── Supplier portal ─────────────────────────────────────────────────────────

def _require_supplier(me: User) -> UUID:
    if Role(me.role) != Role.SUPPLIER:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Supplier portal only")
    if not me.linked_supplier_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "This supplier account has no linked supplier record")
    return me.linked_supplier_id


@router.get("/supplier/me")
async def supplier_me(
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    sid = _require_supplier(me)
    from app.models.purchasing import Supplier
    s = await db.get(Supplier, sid)
    if not s:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return {
        "id": str(s.id), "name": s.name, "category": s.category,
        "rating": float(s.rating or 0),
        "lead_time_days_avg": float(s.lead_time_days_avg or 0),
        "qc_fail_rate": float(s.qc_fail_rate or 0),
    }


@router.get("/supplier/orders")
async def supplier_orders(
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    sid = _require_supplier(me)
    rfqs = (await db.scalars(
        select(RFQ).where(RFQ.supplier_id == sid)
        .order_by(RFQ.created_at.desc())
    )).all()
    pos = (await db.scalars(
        select(SupplierPO).where(SupplierPO.supplier_id == sid)
        .order_by(SupplierPO.created_at.desc())
    )).all()

    # Pre-load each PO's project so we can show the warehouse ETA + drawing
    # status without N+1 round trips.
    proj_ids = {p.project_id for p in pos if p.project_id}
    projects: dict[UUID, Project] = {}
    if proj_ids:
        rows = (await db.scalars(
            select(Project).where(Project.id.in_(proj_ids))
        )).all()
        projects = {p.id: p for p in rows}

    # Has the supplier already uploaded a drawing for this PO?
    drawing_po_ids: set[UUID] = set()
    if pos:
        att_rows = (await db.execute(
            select(Attachment.owner_id, Attachment.description)
            .where(
                Attachment.owner_type == "supplier_po",
                Attachment.owner_id.in_([p.id for p in pos]),
            )
        )).all()
        for owner_id, desc in att_rows:
            if desc and desc.startswith("[drawing]"):
                drawing_po_ids.add(owner_id)

    po_out = []
    for p in pos:
        proj = projects.get(p.project_id) if p.project_id else None
        po_out.append({
            "id": str(p.id), "number": p.number, "status": p.status,
            "po_date": p.po_date, "quoted_lead_days": p.quoted_lead_days,
            "total": float(p.total or 0), "items": p.items,
            "created_at": p.created_at,
            "project_id": str(p.project_id) if p.project_id else None,
            "project_code": proj.code if proj else None,
            # Warehouse ETA = when the supplier expects goods at our warehouse
            "est_arrive_our_warehouse": proj.est_arrive_our_warehouse if proj else None,
            "act_arrive_our_warehouse": proj.act_arrive_our_warehouse if proj else None,
            "act_ship_from_origin": proj.act_ship_from_origin if proj else None,
            "has_drawing": p.id in drawing_po_ids,
        })
    return {
        "rfqs": [
            {"id": str(r.id), "status": r.status,
             "quoted_lead_days": r.quoted_lead_days,
             "quoted_lines": r.quoted_lines,
             "created_at": r.created_at}
            for r in rfqs
        ],
        "purchase_orders": po_out,
    }


class SupplierEtaIn(BaseModel):
    est_arrive_our_warehouse: date | None = None
    act_ship_from_origin: date | None = None
    act_arrive_our_warehouse: date | None = None


@router.post("/supplier/po/{po_id}/eta")
async def supplier_set_eta(
    po_id: UUID,
    payload: SupplierEtaIn,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    """Supplier updates shipping dates for the project linked to a PO.

    These dates flow straight to the customer's portal via the project's
    shipping timeline — no internal step required.
    """
    sid = _require_supplier(me)
    po = await db.get(SupplierPO, po_id)
    if not po or po.supplier_id != sid:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your PO")
    if not po.project_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This PO is not linked to a project yet — ask the buyer to attach one.",
        )
    proj = await db.get(Project, po.project_id)
    if not proj:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project missing")
    if payload.est_arrive_our_warehouse is not None:
        proj.est_arrive_our_warehouse = payload.est_arrive_our_warehouse
        # Auto-derive the customer's expected arrival from the warehouse ETA
        # so the customer sees a forecast immediately, without waiting for
        # an internal-team step. Uses a default 7-day internal-handling
        # buffer; ops can override on the project later.
        if not proj.est_arrive_customer:
            from datetime import timedelta as _td
            proj.est_arrive_customer = (
                payload.est_arrive_our_warehouse + _td(days=7)
            )
    if payload.act_ship_from_origin is not None:
        proj.act_ship_from_origin = payload.act_ship_from_origin
    if payload.act_arrive_our_warehouse is not None:
        proj.act_arrive_our_warehouse = payload.act_arrive_our_warehouse
    await db.flush()
    return {
        "ok": True,
        "project_id": str(proj.id),
        "est_arrive_our_warehouse": proj.est_arrive_our_warehouse,
        "est_arrive_customer": proj.est_arrive_customer,
        "act_ship_from_origin": proj.act_ship_from_origin,
        "act_arrive_our_warehouse": proj.act_arrive_our_warehouse,
    }


ALLOWED_UPLOAD_KINDS = {"invoice", "drawing", "bill", "delivery"}


@router.post("/supplier/upload", status_code=201)
async def supplier_upload(
    po_id: UUID = Form(...),
    kind: str = Form(...),
    description: str | None = Form(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    sid = _require_supplier(me)
    if kind not in ALLOWED_UPLOAD_KINDS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"kind must be one of: {', '.join(sorted(ALLOWED_UPLOAD_KINDS))}")
    po = await db.get(SupplierPO, po_id)
    if not po or po.supplier_id != sid:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your PO")
    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty file")
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Max 20 MB")

    safe = "".join(ch if (ch.isalnum() or ch in "._- ") else "_"
                   for ch in (file.filename or "file"))[:200]
    storage_path = await storage.save(data, filename=safe, label=kind,
                                      owner_type="supplier_po", owner_id=po.id)

    a = Attachment(
        owner_type="supplier_po", owner_id=po.id,
        filename=safe, content_type=file.content_type, size=len(data),
        storage_path=storage_path,
        description=f"[{kind}] {description or ''}".strip(),
        uploaded_by=me.id,
    )
    db.add(a)
    await db.flush()

    # When the supplier uploads a drawing on a project-linked PO, mirror it
    # into the project's Drawing list so the customer can see (and approve)
    # it from their portal without an internal-team round-trip.
    if kind == "drawing" and po.project_id:
        prior = (await db.scalars(
            select(Drawing).where(Drawing.project_id == po.project_id)
        )).all()
        next_rev = (max((d.revision for d in prior), default=0) or 0) + 1
        drw = Drawing(
            project_id=po.project_id,
            revision=next_rev,
            file_url=f"/api/v1/attachments/{a.id}/download",
            status="submitted",
            uploaded_by=me.id,
        )
        db.add(drw)
        await db.flush()
    return {
        "id": str(a.id), "po_id": str(po.id), "kind": kind,
        "filename": a.filename, "size": a.size,
    }


@router.get("/supplier/attachments")
async def supplier_attachments(
    po_id: UUID,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    sid = _require_supplier(me)
    po = await db.get(SupplierPO, po_id)
    if not po or po.supplier_id != sid:
        raise HTTPException(status.HTTP_403_FORBIDDEN)
    rows = (await db.scalars(
        select(Attachment).where(
            Attachment.owner_type == "supplier_po",
            Attachment.owner_id == po_id,
        ).order_by(Attachment.created_at.desc())
    )).all()
    return [
        {
            "id": str(a.id), "filename": a.filename, "size": a.size,
            "description": a.description,
            "content_type": a.content_type,
            "uploaded_at": a.created_at,
            "download_url": f"/api/v1/attachments/{a.id}/download",
        }
        for a in rows
    ]

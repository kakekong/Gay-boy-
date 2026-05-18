"""Customer + Supplier portals.

Customers see their own quotations, projects, invoices, and can approve
drawings via this scoped portal — no access to the rest of the system.

Suppliers see purchase requests / RFQs / supplier POs addressed to them,
and can upload invoice / drawing / bill / delivery (landing) documents
that flow back to internal staff.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4
import os
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.permissions import Role
from app.models.attachment import Attachment
from app.models.crm import Customer
from app.models.finance import Invoice
from app.models.operation import DeliveryOrder, Drawing, Project
from app.models.purchasing import PurchaseRequest, RFQ, SupplierPO
from app.models.quotation import Quotation
from app.models.user import User

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
    elif decision == "request_revision":
        d.status = "revision_requested"
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "decision must be approve|request_revision")
    d.customer_decision_at = datetime.now(UTC)
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
    return {
        "rfqs": [
            {"id": str(r.id), "status": r.status,
             "quoted_lead_days": r.quoted_lead_days,
             "quoted_lines": r.quoted_lines,
             "created_at": r.created_at}
            for r in rfqs
        ],
        "purchase_orders": [
            {"id": str(p.id), "number": p.number, "status": p.status,
             "po_date": p.po_date, "quoted_lead_days": p.quoted_lead_days,
             "total": float(p.total or 0), "items": p.items,
             "created_at": p.created_at}
            for p in pos
        ],
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

    now = datetime.now(UTC)
    root = Path(settings.STORAGE_LOCAL_DIR) / "attachments" / str(now.year) / f"{now.month:02d}"
    root.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch if (ch.isalnum() or ch in "._- ") else "_"
                   for ch in (file.filename or "file"))[:200]
    path = root / f"{uuid4().hex}_{kind}_{safe}"
    path.write_bytes(data)

    a = Attachment(
        owner_type="supplier_po", owner_id=po.id,
        filename=safe, content_type=file.content_type, size=len(data),
        storage_path=str(path),
        description=f"[{kind}] {description or ''}".strip(),
        uploaded_by=me.id,
    )
    db.add(a)
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

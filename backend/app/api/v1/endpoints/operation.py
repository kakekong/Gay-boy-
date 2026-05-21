"""Operation: projects, work orders, drawings, deliveries."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.crm import Customer
from app.models.finance import Invoice
from app.models.operation import DeliveryOrder, Drawing, Project, WorkOrder
from app.models.purchasing import PurchaseRequest
from app.models.quotation import Quotation
from app.models.user import User

router = APIRouter()


@router.get("/projects")
async def list_projects(db: AsyncSession = Depends(get_db),
                        _user: User = Depends(get_current_user)):
    rows = (await db.scalars(
        select(Project).where(Project.is_deleted.is_(False)).order_by(Project.created_at.desc())
    )).all()
    return [
        {
            "id": str(p.id), "code": p.code, "customer_id": str(p.customer_id),
            "status": p.status, "po_value": float(p.po_value),
            "target_delivery": p.target_delivery, "actual_delivery": p.actual_delivery,
            "margin_estimate": float(p.margin_estimate), "margin_actual": float(p.margin_actual),
        } for p in rows
    ]


@router.get("/projects/{project_id}")
async def get_project(project_id: UUID,
                      db: AsyncSession = Depends(get_db),
                      _user: User = Depends(get_current_user)):
    p = await db.get(Project, project_id)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    customer = await db.get(Customer, p.customer_id) if p.customer_id else None
    quotation = await db.get(Quotation, p.quotation_id) if p.quotation_id else None
    return {
        "id": str(p.id), "code": p.code, "status": p.status,
        "po_number": p.po_number, "po_date": p.po_date,
        "po_value": float(p.po_value or 0),
        "start_date": p.start_date,
        "target_delivery": p.target_delivery,
        "actual_delivery": p.actual_delivery,
        "margin_estimate": float(p.margin_estimate or 0),
        "margin_actual": float(p.margin_actual or 0),
        "customer": {
            "id": str(customer.id), "company_name": customer.company_name,
            "industry": customer.industry, "stage": customer.stage,
        } if customer else None,
        "quotation": {
            "id": str(quotation.id), "number": quotation.number,
            "status": quotation.status, "total": float(quotation.total or 0),
        } if quotation else None,
        "created_at": p.created_at,
    }


@router.get("/projects/{project_id}/full")
async def project_full(project_id: UUID,
                       db: AsyncSession = Depends(get_db),
                       _user: User = Depends(get_current_user)):
    """Project + all related records, used by the project detail page."""
    p = await db.get(Project, project_id)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

    customer = await db.get(Customer, p.customer_id) if p.customer_id else None
    quotation = await db.get(Quotation, p.quotation_id) if p.quotation_id else None

    work_orders = (await db.scalars(
        select(WorkOrder).where(WorkOrder.project_id == project_id)
        .order_by(WorkOrder.created_at.asc())
    )).all()
    drawings = (await db.scalars(
        select(Drawing).where(Drawing.project_id == project_id)
        .order_by(Drawing.revision.desc())
    )).all()
    deliveries = (await db.scalars(
        select(DeliveryOrder).where(DeliveryOrder.project_id == project_id)
        .order_by(DeliveryOrder.split_index.asc())
    )).all()
    invoices = (await db.scalars(
        select(Invoice).where(Invoice.project_id == project_id)
        .order_by(Invoice.issue_date.asc().nullslast())
    )).all()
    purchase_requests = (await db.scalars(
        select(PurchaseRequest).where(PurchaseRequest.project_id == project_id)
        .order_by(PurchaseRequest.created_at.desc())
    )).all()

    return {
        "project": {
            "id": str(p.id), "code": p.code, "status": p.status,
            "po_number": p.po_number, "po_date": p.po_date,
            "po_value": float(p.po_value or 0),
            "start_date": p.start_date,
            "target_delivery": p.target_delivery,
            "actual_delivery": p.actual_delivery,
            "margin_estimate": float(p.margin_estimate or 0),
            "margin_actual": float(p.margin_actual or 0),
            "created_at": p.created_at,
        },
        "customer": {
            "id": str(customer.id), "company_name": customer.company_name,
            "industry": customer.industry, "stage": customer.stage,
        } if customer else None,
        "quotation": {
            "id": str(quotation.id), "number": quotation.number,
            "status": quotation.status, "total": float(quotation.total or 0),
        } if quotation else None,
        "work_orders": [
            {
                "id": str(w.id), "code": w.code, "stage": w.stage, "notes": w.notes,
                "started_at": w.started_at, "completed_at": w.completed_at,
            } for w in work_orders
        ],
        "drawings": [
            {
                "id": str(d.id), "revision": d.revision, "file_url": d.file_url,
                "status": d.status, "notes": d.notes,
                "customer_decision_at": d.customer_decision_at,
                "created_at": d.created_at,
            } for d in drawings
        ],
        "deliveries": [
            {
                "id": str(do.id), "number": do.number, "split_index": do.split_index,
                "courier": do.courier, "tracking_no": do.tracking_no,
                "delivered_at": do.delivered_at, "status": do.status,
                "items": do.items,
            } for do in deliveries
        ],
        "invoices": [
            {
                "id": str(i.id), "number": i.number, "type": i.type,
                "termin_index": i.termin_index, "issue_date": i.issue_date,
                "due_date": i.due_date, "amount": float(i.amount or 0),
                "tax_amount": float(i.tax_amount or 0), "total": float(i.total or 0),
                "status": i.status,
            } for i in invoices
        ],
        "purchase_requests": [
            {
                "id": str(pr.id), "number": pr.number, "status": pr.status,
                "items": pr.items, "created_at": pr.created_at,
            } for pr in purchase_requests
        ],
    }


# ─── Mutations ───────────────────────────────────────────────────────────────

class ProjectPatch(BaseModel):
    status: str | None = None
    po_number: str | None = None
    start_date: str | None = None
    target_delivery: str | None = None
    actual_delivery: str | None = None
    margin_estimate: float | None = None
    margin_actual: float | None = None
    # Shipping timeline
    est_ship_from_origin: str | None = None
    act_ship_from_origin: str | None = None
    est_arrive_our_warehouse: str | None = None
    act_arrive_our_warehouse: str | None = None
    est_arrive_customer: str | None = None
    act_arrive_customer: str | None = None
    origin_location: str | None = None
    is_import: bool | None = None


@router.patch("/projects/{project_id}")
async def update_project(project_id: UUID,
                         payload: ProjectPatch,
                         db: AsyncSession = Depends(get_db),
                         _user: User = Depends(get_current_user)):
    p = await db.get(Project, project_id)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    # exclude_unset alone isn't enough: the frontend often sends an explicit
    # null for the date fields it isn't editing. Drop those nulls for date
    # columns so we never wipe an existing date by accident. Setting
    # is_import=False or origin_location=null is still respected (they're
    # not in the protected set).
    DATE_FIELDS_PROTECTED = {
        "start_date", "target_delivery", "actual_delivery",
        "est_ship_from_origin", "act_ship_from_origin",
        "est_arrive_our_warehouse", "act_arrive_our_warehouse",
        "est_arrive_customer", "act_arrive_customer",
    }
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        if v is None and k in DATE_FIELDS_PROTECTED:
            continue
        setattr(p, k, v)
    return {"ok": True, "id": str(p.id)}


class WorkOrderIn(BaseModel):
    code: str
    stage: str = "receiving"
    notes: str | None = None


@router.post("/projects/{project_id}/work-orders", status_code=201)
async def add_work_order(project_id: UUID, payload: WorkOrderIn,
                         db: AsyncSession = Depends(get_db),
                         _user: User = Depends(get_current_user)):
    p = await db.get(Project, project_id)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    w = WorkOrder(project_id=project_id, code=payload.code,
                  stage=payload.stage, notes=payload.notes)
    db.add(w)
    await db.flush()
    return {"id": str(w.id), "code": w.code, "stage": w.stage}


@router.patch("/work-orders/{wo_id}")
async def update_work_order(wo_id: UUID, stage: str | None = None,
                            notes: str | None = None, completed: bool = False,
                            db: AsyncSession = Depends(get_db),
                            _user: User = Depends(get_current_user)):
    w = await db.get(WorkOrder, wo_id)
    if not w:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if stage is not None:  w.stage = stage
    if notes is not None:  w.notes = notes
    if completed and not w.completed_at:
        w.completed_at = datetime.now(UTC)
    return {"ok": True, "id": str(w.id), "stage": w.stage,
            "completed_at": w.completed_at}


class DeliveryIn(BaseModel):
    number: str
    split_index: int = 1
    courier: str | None = None
    tracking_no: str | None = None


@router.post("/projects/{project_id}/delivery", status_code=201)
async def create_delivery(project_id: UUID, payload: DeliveryIn,
                          db: AsyncSession = Depends(get_db),
                          _user: User = Depends(get_current_user)):
    p = await db.get(Project, project_id)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    d = DeliveryOrder(
        project_id=project_id, number=payload.number,
        split_index=payload.split_index, courier=payload.courier,
        tracking_no=payload.tracking_no, status="pending",
    )
    db.add(d)
    await db.flush()
    return {"id": str(d.id), "number": d.number}


@router.patch("/deliveries/{do_id}/delivered")
async def mark_delivered(do_id: UUID,
                         db: AsyncSession = Depends(get_db),
                         _user: User = Depends(get_current_user)):
    d = await db.get(DeliveryOrder, do_id)
    if not d:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    d.status = "delivered"
    d.delivered_at = datetime.now(UTC)
    return {"ok": True, "delivered_at": d.delivered_at}


@router.get("/projects/{project_id}/timeline")
async def project_timeline(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    p = await db.get(Project, project_id)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    # Stages in chronological order; "completed" if act date is set.
    stages = [
        {
            "key": "ship_from_origin",
            "label": "Shipped from origin" + (f" ({p.origin_location})" if p.origin_location else ""),
            "est": p.est_ship_from_origin,
            "actual": p.act_ship_from_origin,
        },
        {
            "key": "arrive_our_warehouse",
            "label": "Arrived at our warehouse",
            "est": p.est_arrive_our_warehouse,
            "actual": p.act_arrive_our_warehouse,
        },
        {
            "key": "arrive_customer",
            "label": "Arrived at customer's warehouse",
            "est": p.est_arrive_customer,
            "actual": p.act_arrive_customer,
        },
    ]
    # Mark the current stage as the first one without an actual date
    current_idx = next((i for i, s in enumerate(stages) if not s["actual"]), len(stages))
    for i, s in enumerate(stages):
        s["status"] = (
            "completed" if s["actual"]
            else "current" if i == current_idx
            else "future"
        )
    return {
        "project_id": str(p.id),
        "code": p.code,
        "is_import": bool(p.is_import),
        "origin_location": p.origin_location,
        "stages": stages,
    }

"""Operation: projects, work orders, drawings, deliveries."""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approval import request_approval
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.permissions import Role, require_min
from app.models.crm import Customer
from app.models.finance import Invoice
from app.models.operation import DeliveryOrder, Drawing, Project, WorkOrder
from app.models.purchasing import PurchaseRequest
from app.models.quotation import Quotation
from app.models.user import User

# Operations data (projects, work orders, deliveries) is internal-only.
# External portal users (customer/supplier) get their scoped views via the
# portal router, never the raw operation endpoints. require_min(SALES) admits
# every internal employee (sales tier and up) and blocks the tier-0 externals.
router = APIRouter(dependencies=[Depends(require_min(Role.SALES))])


def _can_see_project_money(user: User) -> bool:
    """Whether this user may see a project's deal economics.

    Purchasing works the procurement side — items requested, suppliers,
    goods receipt, QC — and has no business reason to see PO value,
    margins, or invoice amounts. Everyone else (sales on their own
    customers, admin, finance, manager, director) may. We blank the
    numbers to None rather than dropping the keys so the API shape stays
    stable for the frontend.
    """
    return Role(user.role) != Role.PURCHASING


@router.get("/projects")
async def list_projects(db: AsyncSession = Depends(get_db),
                        user: User = Depends(get_current_user)):
    stmt = (
        select(Project)
        .where(Project.is_deleted.is_(False))
        .order_by(Project.created_at.desc())
    )
    # Sales only sees projects belonging to their own customers
    if Role(user.role) == Role.SALES:
        stmt = stmt.join(Customer, Project.customer_id == Customer.id).where(
            Customer.sales_pic_id == user.id
        )
    rows = (await db.scalars(stmt)).all()
    # Batch-load customer names so the Projects list can show "Customer"
    # column without an N+1 fetch per row.
    cust_ids = {p.customer_id for p in rows if p.customer_id}
    customer_names: dict = {}
    if cust_ids:
        for c in (await db.scalars(
            select(Customer).where(Customer.id.in_(cust_ids))
        )).all():
            customer_names[c.id] = c.company_name
    show_money = _can_see_project_money(user)
    return [
        {
            "id": str(p.id), "code": p.code, "customer_id": str(p.customer_id),
            "customer_name": customer_names.get(p.customer_id),
            "status": p.status,
            "po_value": float(p.po_value) if show_money else None,
            "target_delivery": p.target_delivery, "actual_delivery": p.actual_delivery,
            "margin_estimate": float(p.margin_estimate) if show_money else None,
            "margin_actual": float(p.margin_actual) if show_money else None,
        } for p in rows
    ]


@router.get("/projects/{project_id}")
async def get_project(project_id: UUID,
                      db: AsyncSession = Depends(get_db),
                      user: User = Depends(get_current_user)):
    p = await db.get(Project, project_id)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    customer = await db.get(Customer, p.customer_id) if p.customer_id else None
    quotation = await db.get(Quotation, p.quotation_id) if p.quotation_id else None
    if Role(user.role) == Role.SALES and (
        not customer or customer.sales_pic_id != user.id
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN)
    show_money = _can_see_project_money(user)
    return {
        "id": str(p.id), "code": p.code, "status": p.status,
        "po_number": p.po_number, "po_date": p.po_date,
        "po_value": float(p.po_value or 0) if show_money else None,
        "start_date": p.start_date,
        "target_delivery": p.target_delivery,
        "actual_delivery": p.actual_delivery,
        "margin_estimate": float(p.margin_estimate or 0) if show_money else None,
        "margin_actual": float(p.margin_actual or 0) if show_money else None,
        "customer": {
            "id": str(customer.id), "company_name": customer.company_name,
            "industry": customer.industry, "stage": customer.stage,
        } if customer else None,
        "quotation": {
            "id": str(quotation.id), "number": quotation.number,
            "status": quotation.status,
            "total": float(quotation.total or 0) if show_money else None,
        } if quotation else None,
        "created_at": p.created_at,
    }


@router.get("/projects/{project_id}/full")
async def project_full(project_id: UUID,
                       db: AsyncSession = Depends(get_db),
                       user: User = Depends(get_current_user)):
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

    show_money = _can_see_project_money(user)
    # The approved price request behind this project — so purchasing can see
    # exactly what to source. Costs are always shown (purchasing needs them);
    # the selling price is gated to money-viewers (hidden from purchasing).
    price_request = None
    if p.price_request_id:
        from app.models.price_request import PriceRequest
        pr = await db.get(PriceRequest, p.price_request_id)
        if pr:
            pr_items = []
            for it in (pr.items or []):
                row = {
                    "line_no": it.get("line_no"), "description": it.get("description"),
                    "qty": it.get("qty"), "uom": it.get("uom"), "spec": it.get("spec"),
                    "cost_price": it.get("cost_price"),
                }
                if show_money:
                    row["sell_price"] = it.get("sell_price")
                pr_items.append(row)
            price_request = {"id": str(pr.id), "number": pr.number, "items": pr_items}
    # Sales rep in charge (the customer's account owner) so the detail page can
    # show who owns the deal.
    sales_rep = None
    if customer and customer.sales_pic_id:
        rep = await db.get(User, customer.sales_pic_id)
        if rep:
            sales_rep = {"id": str(rep.id), "name": rep.full_name}
    return {
        "project": {
            "id": str(p.id), "code": p.code, "status": p.status,
            "po_number": p.po_number, "po_date": p.po_date,
            "po_value": float(p.po_value or 0) if show_money else None,
            "start_date": p.start_date,
            "target_delivery": p.target_delivery,
            "actual_delivery": p.actual_delivery,
            "margin_estimate": float(p.margin_estimate or 0) if show_money else None,
            "margin_actual": float(p.margin_actual or 0) if show_money else None,
            "created_at": p.created_at,
        },
        "price_request": price_request,
        "logistics": _logistics_payload(p),
        "sales_pic_id": sales_rep["id"] if sales_rep else None,
        "sales_pic_name": sales_rep["name"] if sales_rep else None,
        "customer": {
            "id": str(customer.id), "company_name": customer.company_name,
            "industry": customer.industry, "stage": customer.stage,
        } if customer else None,
        "quotation": {
            "id": str(quotation.id), "number": quotation.number,
            "status": quotation.status,
            "total": float(quotation.total or 0) if show_money else None,
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
                "due_date": i.due_date,
                "amount": float(i.amount or 0) if show_money else None,
                "tax_amount": float(i.tax_amount or 0) if show_money else None,
                "total": float(i.total or 0) if show_money else None,
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


DATE_FIELDS_PROTECTED = {
    "start_date", "target_delivery", "actual_delivery",
    "est_ship_from_origin", "act_ship_from_origin",
    "est_arrive_our_warehouse", "act_arrive_our_warehouse",
    "est_arrive_customer", "act_arrive_customer",
}
# Shipping / delivery dates that customers see — changes are director-gated.
SHIPPING_FIELDS = {
    "target_delivery", "actual_delivery",
    "est_ship_from_origin", "act_ship_from_origin",
    "est_arrive_our_warehouse", "act_arrive_our_warehouse",
    "est_arrive_customer", "act_arrive_customer",
}


def _apply_project_changes(p: Project, data: dict) -> None:
    # exclude_unset alone isn't enough: the frontend often sends an explicit
    # null for the date fields it isn't editing. Drop those nulls for date
    # columns so we never wipe an existing date by accident.
    for k, v in data.items():
        if v is None and k in DATE_FIELDS_PROTECTED:
            continue
        if hasattr(p, k):
            setattr(p, k, v)


@router.patch("/projects/{project_id}")
async def update_project(project_id: UUID,
                         payload: ProjectPatch,
                         db: AsyncSession = Depends(get_db),
                         user: User = Depends(get_current_user)):
    p = await db.get(Project, project_id)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    data = payload.model_dump(exclude_unset=True)

    # Changing a shipping/delivery date is director-gated: a non-director's
    # edit is filed for approval (with the whole patch) and applied only when
    # the director signs off. Director edits apply immediately.
    touches_shipping = any(k in SHIPPING_FIELDS for k in data)
    if touches_shipping and Role(user.role) != Role.DIRECTOR:
        # Don't queue a null that would only clear a protected date.
        queued = {k: v for k, v in data.items()
                  if not (v is None and k in DATE_FIELDS_PROTECTED)}
        await request_approval(
            db,
            target_type="project",
            target_id=p.id,
            requested_by=user.id,
            required_role=Role.DIRECTOR,
            reason=f"Shipping update for {p.code}: {', '.join(sorted(queued))}",
            payload={"action": "update", "changes": queued},
        )
        return {"ok": True, "id": str(p.id), "pending_approval": True}

    _apply_project_changes(p, data)
    return {"ok": True, "id": str(p.id), "pending_approval": False}


# ─── Post-drawing logistics (purchasing) ─────────────────────────────────────
# Which import documents each delivery mode requires. Two weeks before the
# estimated delivery, purchasing must have these collected.
DOC_LABELS = {
    "invoice": "Invoice",
    "packing_list": "Packing list",
    "form_e": "Form E",
    "bill_of_lading": "Bill of Lading",
    "agent": "Agent details",
}
REQUIRED_DOCS = {
    "local":         ["invoice", "packing_list"],
    "direct_import": ["invoice", "packing_list", "form_e", "bill_of_lading"],
    "agent":         ["invoice", "packing_list", "agent"],
}
_LOGISTICS_ROLES = {Role.PURCHASING, Role.DIRECTOR, Role.MANAGER, Role.ADMIN}
DOCS_DUE_WINDOW_DAYS = 14


def _logistics_payload(p: Project) -> dict:
    mode = p.delivery_mode or "local"
    required = REQUIRED_DOCS.get(mode, REQUIRED_DOCS["local"])
    docs = p.import_docs or {}
    rows = []
    for key in required:
        d = docs.get(key) or {}
        rows.append({
            "key": key,
            "label": DOC_LABELS.get(key, key),
            "collected": bool(d.get("collected")),
            "attachment_id": d.get("attachment_id"),
            "note": d.get("note"),
        })
    all_collected = all(r["collected"] for r in rows) if rows else True
    days_to = (p.est_delivery_date - date.today()).days if p.est_delivery_date else None
    return {
        "delivery_mode": mode,
        "est_delivery_date": p.est_delivery_date,
        "delivery_confirmed_at": p.delivery_confirmed_at,
        "required_docs": rows,
        "docs_complete": all_collected,
        "days_to_delivery": days_to,
        # Documents are "due" once we're within the window and not yet complete.
        "docs_due": (
            days_to is not None and days_to <= DOCS_DUE_WINDOW_DAYS and not all_collected
        ),
    }


async def _has_approved_drawing(db: AsyncSession, project_id: UUID) -> bool:
    d = await db.scalar(
        select(Drawing).where(
            Drawing.project_id == project_id, Drawing.status == "approved"
        ).limit(1)
    )
    return d is not None


class LogisticsPatch(BaseModel):
    delivery_mode: str | None = None
    est_delivery_date: date | None = None


@router.patch("/projects/{project_id}/logistics")
async def update_logistics(project_id: UUID, payload: LogisticsPatch,
                           db: AsyncSession = Depends(get_db),
                           user: User = Depends(get_current_user)):
    """Purchasing sets the delivery mode + estimated delivery date once the
    drawing is approved."""
    if Role(user.role) not in _LOGISTICS_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Purchasing/management only")
    p = await db.get(Project, project_id)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if not await _has_approved_drawing(db, project_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Set logistics only after the drawing is approved.",
        )
    if payload.delivery_mode is not None:
        if payload.delivery_mode not in REQUIRED_DOCS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"delivery_mode must be one of {list(REQUIRED_DOCS)}")
        p.delivery_mode = payload.delivery_mode
    if payload.est_delivery_date is not None:
        p.est_delivery_date = payload.est_delivery_date
    await db.flush()
    return _logistics_payload(p)


class ImportDocPatch(BaseModel):
    key: str
    collected: bool = True
    attachment_id: str | None = None
    note: str | None = None


@router.patch("/projects/{project_id}/import-docs")
async def update_import_doc(project_id: UUID, payload: ImportDocPatch,
                            db: AsyncSession = Depends(get_db),
                            user: User = Depends(get_current_user)):
    """Mark an import document collected (optionally attach the file)."""
    if Role(user.role) not in _LOGISTICS_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Purchasing/management only")
    p = await db.get(Project, project_id)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if payload.key not in DOC_LABELS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Unknown document '{payload.key}'")
    docs = dict(p.import_docs or {})
    docs[payload.key] = {
        "collected": payload.collected,
        "attachment_id": payload.attachment_id,
        "note": payload.note,
    }
    p.import_docs = docs
    await db.flush()
    return _logistics_payload(p)


@router.post("/projects/{project_id}/confirm-delivery")
async def confirm_delivery(project_id: UUID,
                           db: AsyncSession = Depends(get_db),
                           user: User = Depends(get_current_user)):
    """Confirm the delivery date — this spawns the receiving work order on the
    operations board (idempotent)."""
    if Role(user.role) not in _LOGISTICS_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Purchasing/management only")
    p = await db.get(Project, project_id)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if not p.est_delivery_date:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Set the estimated delivery date first.")
    p.delivery_confirmed_at = datetime.now(UTC)
    # Spawn the receiving WO if the operations board doesn't have one yet.
    existing = await db.scalar(
        select(WorkOrder).where(
            WorkOrder.project_id == project_id, WorkOrder.stage == "receiving"
        ).limit(1)
    )
    created_wo = None
    if not existing:
        wo = WorkOrder(project_id=project_id, code=f"WO-{p.code}-RCV", stage="receiving")
        db.add(wo)
        await db.flush()
        created_wo = {"id": str(wo.id), "code": wo.code}
    return {"ok": True, "delivery_confirmed_at": p.delivery_confirmed_at,
            "receiving_work_order": created_wo,
            "logistics": _logistics_payload(p)}


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


@router.get("/work-orders")
async def list_work_orders(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
    stage: str | None = None,
    completed: bool | None = None,
    project_id: UUID | None = None,
):
    """List work orders, optionally scoped to a stage / completion / project.

    Used by the Operation board's per-stage screens — pass ?stage=receiving
    to render a focused view of just that column."""
    from app.models.crm import Customer
    stmt = select(WorkOrder).order_by(WorkOrder.created_at.desc())
    if stage:
        stmt = stmt.where(WorkOrder.stage == stage)
    if project_id:
        stmt = stmt.where(WorkOrder.project_id == project_id)
    if completed is True:
        stmt = stmt.where(WorkOrder.completed_at.is_not(None))
    elif completed is False:
        stmt = stmt.where(WorkOrder.completed_at.is_(None))
    rows = (await db.scalars(stmt)).all()

    # Batch-load project + customer info for the table view.
    project_ids = {w.project_id for w in rows if w.project_id}
    projects: dict[UUID, Project] = {}
    if project_ids:
        for p in (await db.scalars(
            select(Project).where(Project.id.in_(project_ids))
        )).all():
            projects[p.id] = p
    customer_ids = {p.customer_id for p in projects.values() if p.customer_id}
    customers: dict[UUID, Customer] = {}
    if customer_ids:
        for c in (await db.scalars(
            select(Customer).where(Customer.id.in_(customer_ids))
        )).all():
            customers[c.id] = c

    out = []
    for w in rows:
        proj = projects.get(w.project_id) if w.project_id else None
        cust = customers.get(proj.customer_id) if proj else None
        out.append({
            "id": str(w.id),
            "code": w.code,
            "stage": w.stage,
            "notes": w.notes,
            "started_at": w.started_at,
            "completed_at": w.completed_at,
            "created_at": w.created_at,
            "project_id": str(w.project_id) if w.project_id else None,
            "project_code": proj.code if proj else None,
            "project_status": proj.status if proj else None,
            "project_target_delivery": proj.target_delivery if proj else None,
            "customer_id": str(cust.id) if cust else None,
            "customer_name": cust.company_name if cust else None,
        })
    return out


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
        "target_delivery": p.target_delivery,
        "actual_delivery": p.actual_delivery,
        "stages": stages,
    }

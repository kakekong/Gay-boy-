from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approval import evaluate_data_change, request_approval
from app.core.audit import record as audit_record
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.permissions import Role, can_view_customer, filter_to_role_scope
from app.core.stage_tasks import (
    ensure_stage_tasks,
    stage_tasks_for,
    stage_task_kind,
)
from app.models.crm import Activity, Customer, Reminder
from app.models.finance import Invoice, Payment
from app.models.operation import Project
from app.models.quotation import Quotation
from app.models.user import User
from app.schemas.common import Page
from app.schemas.customer import CustomerCreate, CustomerOut, CustomerUpdate

router = APIRouter()


@router.get("", response_model=Page[CustomerOut])
async def list_customers(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    q: str | None = None,
    stage: str | None = None,
    industry: str | None = None,
):
    base = select(Customer).where(Customer.is_deleted.is_(False))
    base = filter_to_role_scope(user, base, Customer.sales_pic_id)
    if q:
        base = base.where(Customer.company_name.ilike(f"%{q}%"))
    if stage:
        base = base.where(Customer.stage == stage)
    if industry:
        base = base.where(Customer.industry == industry)

    total = await db.scalar(
        select(func.count()).select_from(base.subquery())
    ) or 0
    rows = (await db.scalars(
        base.order_by(Customer.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )).all()
    return Page(data=[CustomerOut.model_validate(r) for r in rows],
                page=page, page_size=page_size, total=total)


@router.post("", response_model=CustomerOut, status_code=201)
async def create_customer(
    payload: CustomerCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if Role(user.role) == Role.SALES:
        sales_pic = user.id
    else:
        sales_pic = payload.sales_pic_id
    obj = Customer(
        **payload.model_dump(exclude={"sales_pic_id"}),
        sales_pic_id=sales_pic,
        created_by=user.id, updated_by=user.id,
    )
    db.add(obj)
    await db.flush()
    await ensure_stage_tasks(db, obj, obj.stage)
    return obj


@router.get("/{customer_id}", response_model=CustomerOut)
async def get_customer(customer_id: UUID,
                       db: AsyncSession = Depends(get_db),
                       user: User = Depends(get_current_user)):
    obj = await db.get(Customer, customer_id)
    if not obj or obj.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if not can_view_customer(user, obj.sales_pic_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Out of scope")
    return obj


@router.patch("/{customer_id}", response_model=CustomerOut)
async def update_customer(
    customer_id: UUID,
    payload: CustomerUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    obj = await db.get(Customer, customer_id)
    if not obj or obj.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if Role(user.role) == Role.SALES and obj.sales_pic_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sales can only edit own customers")

    rule = evaluate_data_change(Role(user.role))
    changes = payload.model_dump(exclude_unset=True)

    if rule.required_role is None:
        before = {k: getattr(obj, k) for k in changes.keys()}
        prev_stage = obj.stage
        for k, v in changes.items():
            setattr(obj, k, v)
        obj.updated_by = user.id
        await audit_record(db, actor=user, action="update", entity="customer",
                           entity_id=obj.id, before=before, after=changes)
        if "stage" in changes and changes["stage"] != prev_stage:
            await ensure_stage_tasks(db, obj, changes["stage"])
        return obj

    # admin role -> needs manager approval; record request, do not mutate
    await request_approval(
        db,
        target_type="customer",
        target_id=obj.id,
        requested_by=user.id,
        required_role=rule.required_role,
        reason=rule.reason,
        payload={"changes": changes},
    )
    raise HTTPException(status.HTTP_202_ACCEPTED, "Change requested; awaiting approval")


# ─── Activities ──────────────────────────────────────────────────────────────

class ActivityIn(BaseModel):
    type: str  # call, presentation, technical_meeting, follow_up, note, ...
    direction: str = "internal"
    notes: str | None = None
    occurred_at: datetime | None = None
    meta: dict = {}


@router.get("/{customer_id}/activities")
async def list_activities(
    customer_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    limit: int = 50,
):
    obj = await db.get(Customer, customer_id)
    if not obj or obj.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if not can_view_customer(user, obj.sales_pic_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Out of scope")
    rows = (await db.scalars(
        select(Activity).where(Activity.customer_id == customer_id)
        .order_by(Activity.occurred_at.desc()).limit(limit)
    )).all()
    return [
        {
            "id": str(a.id),
            "type": a.type,
            "direction": a.direction,
            "notes": a.notes,
            "occurred_at": a.occurred_at,
            "user_id": str(a.user_id) if a.user_id else None,
            "meta": a.meta,
        }
        for a in rows
    ]


@router.post("/{customer_id}/activities", status_code=201)
async def create_activity(
    customer_id: UUID,
    payload: ActivityIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    obj = await db.get(Customer, customer_id)
    if not obj or obj.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if not can_view_customer(user, obj.sales_pic_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Out of scope")
    a = Activity(
        customer_id=customer_id,
        user_id=user.id,
        type=payload.type,
        direction=payload.direction,
        occurred_at=payload.occurred_at or datetime.now(UTC),
        notes=payload.notes,
        meta=payload.meta or {},
    )
    db.add(a)
    await db.flush()
    return {"id": str(a.id), "ok": True}


# ─── Aggregated summary + export ─────────────────────────────────────────────

async def _build_summary(db: AsyncSession, c: Customer) -> dict:
    """Aggregate everything we know about this customer for the detail page."""
    # Quotations
    quotes = (await db.scalars(
        select(Quotation).where(Quotation.customer_id == c.id)
        .order_by(Quotation.created_at.desc())
    )).all()
    won  = [q for q in quotes if q.status == "won"]
    lost = [q for q in quotes if q.status == "lost"]
    open_states = ("draft", "pending_approval", "approved", "sent")
    open_q = [q for q in quotes if q.status in open_states]
    decided = len(won) + len(lost)
    total_quoted = float(sum(float(q.total or 0) for q in quotes))
    won_revenue  = float(sum(float(q.total or 0) for q in won))
    pipeline_val = float(sum(float(q.total or 0) for q in open_q))

    # Projects
    projects = (await db.scalars(
        select(Project).where(
            Project.customer_id == c.id, Project.is_deleted.is_(False)
        ).order_by(Project.created_at.desc())
    )).all()
    active_p = [p for p in projects if p.status not in ("closed", "paid")]
    completed_p = [p for p in projects if p.status in ("closed", "paid")]

    # Invoices + payments
    invoices = (await db.scalars(
        select(Invoice).where(Invoice.customer_id == c.id)
        .order_by(Invoice.issue_date.asc().nullslast())
    )).all()
    inv_ids = [i.id for i in invoices]
    payments = []
    if inv_ids:
        payments = (await db.scalars(
            select(Payment).where(Payment.invoice_id.in_(inv_ids))
            .order_by(Payment.paid_at.desc().nullslast())
        )).all()
    total_invoiced = float(sum(float(i.total or 0) for i in invoices))
    total_paid     = float(sum(float(p.amount or 0) for p in payments))
    outstanding    = float(sum(
        float(i.total or 0) for i in invoices
        if i.status in ("issued", "partial", "overdue")
    ))
    overdue_count = sum(1 for i in invoices if i.status == "overdue")

    # Activities
    activities = (await db.scalars(
        select(Activity).where(Activity.customer_id == c.id)
        .order_by(Activity.occurred_at.desc())
        .limit(100)
    )).all()
    last_activity = activities[0].occurred_at if activities else None
    first_quote_at = quotes[-1].created_at if quotes else None
    days_known = ((datetime.now(UTC) - c.created_at).days
                  if c.created_at else 0)

    return {
        "customer": {
            "id": str(c.id),
            "company_name": c.company_name,
            "industry": c.industry,
            "pic_name": c.pic_name,
            "pic_position": c.pic_position,
            "phone": c.phone,
            "whatsapp": c.whatsapp,
            "email": c.email,
            "company_address": c.company_address,
            "delivery_address": c.delivery_address,
            "stage": c.stage,
            "lifetime_value": float(c.lifetime_value or 0),
            "lost_reason": c.lost_reason,
            "payment_terms": c.payment_terms,
            "sales_pic_id": str(c.sales_pic_id) if c.sales_pic_id else None,
            "created_at": c.created_at,
        },
        "stats": {
            "total_quotations": len(quotes),
            "open_quotations": len(open_q),
            "won": len(won),
            "lost": len(lost),
            "win_rate": round(len(won) / decided, 3) if decided else 0,
            "total_quoted": total_quoted,
            "won_revenue": won_revenue,
            "pipeline_value": pipeline_val,
            "active_projects": len(active_p),
            "completed_projects": len(completed_p),
            "total_invoiced": total_invoiced,
            "total_paid": total_paid,
            "outstanding_ar": outstanding,
            "overdue_invoices": overdue_count,
            "activities_logged": len(activities),
            "last_activity_at": last_activity,
            "first_quotation_at": first_quote_at,
            "days_known": days_known,
        },
        "projects": [
            {
                "id": str(p.id), "code": p.code, "status": p.status,
                "po_number": p.po_number, "po_value": float(p.po_value or 0),
                "target_delivery": p.target_delivery,
                "actual_delivery": p.actual_delivery,
                "margin_estimate": float(p.margin_estimate or 0),
                "margin_actual":   float(p.margin_actual or 0),
            }
            for p in projects
        ],
        "quotations": [
            {
                "id": str(q.id), "number": q.number, "status": q.status,
                "variant": q.variant, "discount_pct": float(q.discount_pct or 0),
                "total": float(q.total or 0),
                "valid_until": q.valid_until, "created_at": q.created_at,
            }
            for q in quotes
        ],
        "invoices": [
            {
                "id": str(i.id), "number": i.number, "type": i.type,
                "issue_date": i.issue_date, "due_date": i.due_date,
                "amount": float(i.amount or 0),
                "tax_amount": float(i.tax_amount or 0),
                "total": float(i.total or 0), "status": i.status,
            }
            for i in invoices
        ],
        "payments": [
            {
                "id": str(p.id), "invoice_id": str(p.invoice_id),
                "paid_at": p.paid_at, "amount": float(p.amount or 0),
                "method": p.method, "reference": p.reference,
            }
            for p in payments
        ],
        "activities": [
            {
                "id": str(a.id), "type": a.type, "direction": a.direction,
                "occurred_at": a.occurred_at, "notes": a.notes,
            }
            for a in activities
        ],
    }


# ─── Stage checklist ─────────────────────────────────────────────────────────


@router.get("/{customer_id}/stage-tasks")
async def list_stage_tasks(
    customer_id: UUID,
    stage: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return the stage checklist for a customer.

    Defaults to the customer's current stage. Sales sees only their own
    customers; HR/manager/director see all.
    """
    c = await db.get(Customer, customer_id)
    if not c or c.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if Role(user.role) == Role.SALES and c.sales_pic_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN)
    # Make sure tasks for the current stage exist before returning them
    if (stage or c.stage) == c.stage:
        await ensure_stage_tasks(db, c, c.stage)
    rows = await stage_tasks_for(db, c, stage)
    return {"stage": stage or c.stage, "items": rows}


@router.post("/{customer_id}/stage-tasks/{task_key}/complete")
async def complete_stage_task(
    customer_id: UUID,
    task_key: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    c = await db.get(Customer, customer_id)
    if not c or c.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if Role(user.role) == Role.SALES and c.sales_pic_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN)
    k = stage_task_kind(c.stage, task_key)
    r = await db.scalar(
        select(Reminder).where(
            Reminder.customer_id == c.id,
            Reminder.kind == k,
        )
    )
    if not r:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stage task not found")
    r.status = "done"
    await audit_record(db, actor=user, action="complete", entity="stage_task",
                       entity_id=r.id, before={"status": "pending"},
                       after={"status": "done", "kind": k})
    return {"id": str(r.id), "status": r.status, "kind": k}


@router.post("/{customer_id}/stage-tasks/{task_key}/reopen")
async def reopen_stage_task(
    customer_id: UUID,
    task_key: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    c = await db.get(Customer, customer_id)
    if not c or c.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if Role(user.role) == Role.SALES and c.sales_pic_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN)
    k = stage_task_kind(c.stage, task_key)
    r = await db.scalar(
        select(Reminder).where(
            Reminder.customer_id == c.id,
            Reminder.kind == k,
        )
    )
    if not r:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stage task not found")
    r.status = "pending"
    return {"id": str(r.id), "status": r.status, "kind": k}


@router.get("/{customer_id}/summary")
async def customer_summary(
    customer_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    c = await db.get(Customer, customer_id)
    if not c or c.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if not can_view_customer(user, c.sales_pic_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Out of scope")
    return await _build_summary(db, c)


def _csv_quote(v) -> str:
    if v is None:
        return ""
    s = str(v).replace('\r', ' ').replace('\n', ' ')
    if any(ch in s for ch in [',', '"', '\n']):
        s = '"' + s.replace('"', '""') + '"'
    return s


def _csv_row(values) -> str:
    return ",".join(_csv_quote(v) for v in values)


def _fmt_idr(n) -> str:
    """Indonesian-style: dots for thousands, comma for decimal."""
    try:
        n = float(n or 0)
    except (TypeError, ValueError):
        return ""
    sign = "-" if n < 0 else ""
    s = f"{abs(n):,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{sign}Rp {s}"


@router.get("/{customer_id}/export.csv")
async def export_customer_csv(
    customer_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Single CSV with sectioned headers; opens cleanly in Excel/Sheets/Numbers."""
    c = await db.get(Customer, customer_id)
    if not c or c.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if not can_view_customer(user, c.sales_pic_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Out of scope")

    s = await _build_summary(db, c)
    stats = s["stats"]
    cust = s["customer"]
    today = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    lines: list[str] = []

    def section(name: str):
        lines.append("")
        lines.append(f"# {name}")

    # Header
    lines.append(_csv_row(["IndustriaCRM — Customer report"]))
    lines.append(_csv_row(["Generated", today, "by", user.full_name or user.email]))

    # Profile
    section("CUSTOMER PROFILE")
    lines.append(_csv_row(["Field", "Value"]))
    lines.append(_csv_row(["Company name",     cust["company_name"]]))
    lines.append(_csv_row(["Industry",         cust["industry"]]))
    lines.append(_csv_row(["Stage",            cust["stage"]]))
    lines.append(_csv_row(["PIC name",         cust["pic_name"] or ""]))
    lines.append(_csv_row(["PIC position",     cust["pic_position"] or ""]))
    lines.append(_csv_row(["Phone",            cust["phone"] or ""]))
    lines.append(_csv_row(["WhatsApp",         cust["whatsapp"] or ""]))
    lines.append(_csv_row(["Email",            cust["email"] or ""]))
    lines.append(_csv_row(["Company address",  cust["company_address"] or ""]))
    lines.append(_csv_row(["Delivery address", cust["delivery_address"] or ""]))
    lines.append(_csv_row(["Customer since",   cust["created_at"]]))
    lines.append(_csv_row(["Payment terms",    str(cust["payment_terms"] or "")]))
    if cust.get("lost_reason"):
        lines.append(_csv_row(["Lost reason",  cust["lost_reason"]]))

    # Financial summary
    section("FINANCIAL SUMMARY")
    lines.append(_csv_row(["Metric", "Value"]))
    lines.append(_csv_row(["Lifetime value",          _fmt_idr(cust["lifetime_value"])]))
    lines.append(_csv_row(["Total quoted (all-time)", _fmt_idr(stats["total_quoted"])]))
    lines.append(_csv_row(["Won revenue",             _fmt_idr(stats["won_revenue"])]))
    lines.append(_csv_row(["Pipeline (open quotes)",  _fmt_idr(stats["pipeline_value"])]))
    lines.append(_csv_row(["Total invoiced",          _fmt_idr(stats["total_invoiced"])]))
    lines.append(_csv_row(["Total paid",              _fmt_idr(stats["total_paid"])]))
    lines.append(_csv_row(["Outstanding AR",          _fmt_idr(stats["outstanding_ar"])]))

    # Counts
    section("ENGAGEMENT")
    lines.append(_csv_row(["Metric", "Value"]))
    lines.append(_csv_row(["Quotations · total",  stats["total_quotations"]]))
    lines.append(_csv_row(["Quotations · open",   stats["open_quotations"]]))
    lines.append(_csv_row(["Quotations · won",    stats["won"]]))
    lines.append(_csv_row(["Quotations · lost",   stats["lost"]]))
    lines.append(_csv_row(["Win rate",            f"{stats['win_rate'] * 100:.1f}%"]))
    lines.append(_csv_row(["Projects · active",     stats["active_projects"]]))
    lines.append(_csv_row(["Projects · completed",  stats["completed_projects"]]))
    lines.append(_csv_row(["Overdue invoices",      stats["overdue_invoices"]]))
    lines.append(_csv_row(["Activities logged",     stats["activities_logged"]]))
    lines.append(_csv_row(["Last activity at",      stats["last_activity_at"] or ""]))
    lines.append(_csv_row(["First quotation at",    stats["first_quotation_at"] or ""]))
    lines.append(_csv_row(["Days known",            stats["days_known"]]))

    # Quotations table
    section("QUOTATIONS")
    lines.append(_csv_row(["Number", "Status", "Variant", "Discount %", "Total", "Valid until", "Created"]))
    for q in s["quotations"]:
        lines.append(_csv_row([
            q["number"], q["status"], q["variant"],
            f"{q['discount_pct']:.1f}", _fmt_idr(q["total"]),
            q["valid_until"] or "", q["created_at"],
        ]))

    # Projects table
    section("PROJECTS")
    lines.append(_csv_row([
        "Code", "Status", "PO Number", "PO Value", "Target delivery",
        "Actual delivery", "Margin est", "Margin actual",
    ]))
    for p in s["projects"]:
        lines.append(_csv_row([
            p["code"], p["status"], p["po_number"] or "",
            _fmt_idr(p["po_value"]),
            p["target_delivery"] or "", p["actual_delivery"] or "",
            f"{p['margin_estimate']*100:.1f}%", f"{p['margin_actual']*100:.1f}%",
        ]))

    # Invoices table
    section("INVOICES")
    lines.append(_csv_row([
        "Number", "Type", "Issue date", "Due date", "Amount", "Tax", "Total", "Status",
    ]))
    for i in s["invoices"]:
        lines.append(_csv_row([
            i["number"], i["type"], i["issue_date"] or "", i["due_date"] or "",
            _fmt_idr(i["amount"]), _fmt_idr(i["tax_amount"]),
            _fmt_idr(i["total"]), i["status"],
        ]))

    # Payments table
    section("PAYMENTS")
    lines.append(_csv_row(["Invoice", "Paid at", "Amount", "Method", "Reference"]))
    inv_map = {i["id"]: i["number"] for i in s["invoices"]}
    for p in s["payments"]:
        lines.append(_csv_row([
            inv_map.get(p["invoice_id"], p["invoice_id"]),
            p["paid_at"] or "", _fmt_idr(p["amount"]),
            p["method"] or "", p["reference"] or "",
        ]))

    # Activities table
    section("ACTIVITIES (latest 100)")
    lines.append(_csv_row(["When", "Type", "Direction", "Notes"]))
    for a in s["activities"]:
        lines.append(_csv_row([
            a["occurred_at"], a["type"], a["direction"], a["notes"] or "",
        ]))

    body = "\n".join(lines) + "\n"
    # UTF-8 BOM so Excel opens with the right encoding
    safe_name = "".join(ch if ch.isalnum() else "_"
                        for ch in cust["company_name"])[:60]
    filename = f"{safe_name}_customer-report.csv"
    return Response(
        content="﻿" + body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

from datetime import UTC, date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approval import evaluate_data_change, request_approval
from app.core.audit import record as audit_record
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.permissions import Role, can_view_customer, filter_to_role_scope, require_min
from app.core.stage_playbook import is_forward_skip
from app.core.stage_tasks import (
    ensure_stage_tasks,
    stage_tasks_for,
    stage_task_kind,
)
from app.models.crm import Activity, Customer, CustomerContact, Reminder
from app.models.finance import Invoice, OUTSTANDING_INVOICE_STATUSES, Payment
from app.models.operation import Project
from app.models.quotation import Quotation
from app.models.user import User
from app.services import storage
from app.schemas.common import Page
from app.schemas.customer import CustomerCreate, CustomerOut, CustomerUpdate

router = APIRouter(
    # Internal-only surface. External portal accounts (customer /
    # supplier, hierarchy tier 0) must never reach the CRM, pricing,
    # calendar or notification data — they have /portal/* instead.
    dependencies=[Depends(require_min(Role.SALES))]
)


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
    # Batch-load sales rep names so the list view can show "Sales rep"
    # column without N+1 round-trips.
    sales_ids = {r.sales_pic_id for r in rows if r.sales_pic_id}
    sales_names: dict = {}
    if sales_ids:
        for u in (await db.scalars(
            select(User).where(User.id.in_(sales_ids))
        )).all():
            sales_names[u.id] = u.full_name
    out: list[CustomerOut] = []
    for r in rows:
        c = CustomerOut.model_validate(r)
        c.sales_pic_name = sales_names.get(r.sales_pic_id) if r.sales_pic_id else None
        out.append(c)
    return Page(data=out, page=page, page_size=page_size, total=total)


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
        **payload.model_dump(exclude={"sales_pic_id", "contacts"}),
        sales_pic_id=sales_pic,
        created_by=user.id, updated_by=user.id,
    )
    db.add(obj)
    await db.flush()
    # Multi-PIC: persist any extra contacts submitted with the wizard.
    for c in payload.contacts:
        name = (c.name or "").strip()
        if not name:
            continue
        db.add(CustomerContact(
            customer_id=obj.id,
            name=name,
            position=c.position,
            phone=c.phone,
            whatsapp=c.whatsapp,
            email=c.email,
            is_primary=c.is_primary,
            notes=c.notes,
        ))
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

    # Lazy sync: bump the customer's deal-pipeline stage forward to whatever
    # their projects imply (post-PO stages mirror the project's status). Keeps
    # the pipeline card on the customer page from going stale as work happens.
    from app.core.stage_playbook import sync_customer_stage_from_projects
    from app.models.operation import Project
    proj_statuses = (await db.scalars(
        select(Project.status).where(
            Project.customer_id == customer_id, Project.is_deleted.is_(False)
        )
    )).all()
    if sync_customer_stage_from_projects(obj, list(proj_statuses)):
        # Entering a new stage retires the previous stage's leftovers, which
        # otherwise stay pending forever (the checklist only renders the
        # CURRENT stage, so they could never be ticked) and keep firing in
        # the bell, calendar and AI queue.
        await ensure_stage_tasks(db, obj, obj.stage)
        await db.flush()
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

    # Stage transitions are sensitive — every move along the pipeline needs
    # a manager or director to sign off. Managers and directors can move
    # freely (they hold the approval authority); everyone else queues a
    # request that either a manager or a director can clear.
    stage_change = "stage" in changes and changes["stage"] != obj.stage
    # The pipeline must be walked in order — no skipping a stage forward.
    if stage_change and is_forward_skip(obj.stage, changes["stage"]):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Can't skip from '{obj.stage}' straight to '{changes['stage']}'. "
            "Move one stage at a time — each stage must be approved before "
            "the next.",
        )
    can_approve_stage = Role(user.role) in (Role.MANAGER, Role.DIRECTOR)
    needs_approval_for_stage = stage_change and not can_approve_stage

    if rule.required_role is None and not needs_approval_for_stage:
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

    # Either a sensitive data change (admin role) or a stage transition.
    required_role = Role.MANAGER if needs_approval_for_stage else rule.required_role
    reason = (
        f"Stage move {obj.stage} → {changes['stage']} needs manager/director approval"
        if needs_approval_for_stage else rule.reason
    )
    await request_approval(
        db,
        target_type="customer",
        target_id=obj.id,
        requested_by=user.id,
        required_role=required_role,
        reason=reason,
        payload={"changes": changes},
    )
    # Return (don't raise) — raising would roll back the session in get_db's
    # exception handler and discard the approval request we just filed.
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"status": "pending_approval",
                 "message": "Change requested; awaiting approval"},
    )


# ─── Activities ──────────────────────────────────────────────────────────────

class ActivityIn(BaseModel):
    type: str  # call, presentation, technical_meeting, follow_up, note, ...
    direction: str = "internal"
    notes: str | None = None
    occurred_at: datetime | None = None
    meta: dict = {}


# ─── Additional contacts (multiple PICs per customer) ───────────────────────


class ContactIn(BaseModel):
    name: str
    position: str | None = None
    phone: str | None = None
    whatsapp: str | None = None
    email: str | None = None
    is_primary: bool = False
    notes: str | None = None


def _contact_out(c: CustomerContact) -> dict:
    return {
        "id": str(c.id),
        "customer_id": str(c.customer_id),
        "name": c.name,
        "position": c.position,
        "phone": c.phone,
        "whatsapp": c.whatsapp,
        "email": c.email,
        "is_primary": c.is_primary,
        "notes": c.notes,
        "created_at": c.created_at,
    }


@router.get("/{customer_id}/contacts")
async def list_contacts(
    customer_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    c = await db.get(Customer, customer_id)
    if not c or c.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found")
    if Role(user.role) == Role.SALES and c.sales_pic_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN)
    rows = (await db.scalars(
        select(CustomerContact)
        .where(CustomerContact.customer_id == customer_id)
        .order_by(CustomerContact.is_primary.desc(), CustomerContact.created_at.asc())
    )).all()
    return [_contact_out(x) for x in rows]


@router.post("/{customer_id}/contacts", status_code=201)
async def create_contact(
    customer_id: UUID,
    payload: ContactIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    c = await db.get(Customer, customer_id)
    if not c or c.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found")
    if Role(user.role) == Role.SALES and c.sales_pic_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN)
    if not payload.name.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Name required")
    contact = CustomerContact(
        customer_id=customer_id,
        name=payload.name.strip(),
        position=payload.position,
        phone=payload.phone,
        whatsapp=payload.whatsapp,
        email=payload.email,
        is_primary=payload.is_primary,
        notes=payload.notes,
    )
    db.add(contact)
    await db.flush()
    return _contact_out(contact)


@router.patch("/{customer_id}/contacts/{contact_id}")
async def update_contact(
    customer_id: UUID,
    contact_id: UUID,
    payload: ContactIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    c = await db.get(Customer, customer_id)
    if not c or c.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found")
    if Role(user.role) == Role.SALES and c.sales_pic_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN)
    contact = await db.get(CustomerContact, contact_id)
    if not contact or contact.customer_id != customer_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(contact, k, v)
    return _contact_out(contact)


@router.delete("/{customer_id}/contacts/{contact_id}", status_code=204)
async def delete_contact(
    customer_id: UUID,
    contact_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    c = await db.get(Customer, customer_id)
    if not c or c.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found")
    if Role(user.role) == Role.SALES and c.sales_pic_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN)
    contact = await db.get(CustomerContact, contact_id)
    if not contact or contact.customer_id != customer_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found")
    await db.delete(contact)
    return None


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

    # Sales follow-ups need the director's sign-off — the activity is only
    # written once approved (see core/approval.py). Other activity types and
    # other roles log directly.
    if payload.type == "follow_up" and Role(user.role) == Role.SALES:
        req = await request_approval(
            db,
            target_type="followup",
            target_id=customer_id,
            requested_by=user.id,
            required_role=Role.DIRECTOR,
            reason="Follow-up activity",
            payload={
                "source": "customer",
                "type": payload.type,
                "direction": payload.direction,
                "notes": payload.notes,
                "meta": payload.meta or {},
            },
        )
        await db.flush()
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "status": "pending_approval",
                "approval_request_id": str(req.id),
                "message": "Follow-up sent to the director for approval.",
            },
        )

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
    # Net each open invoice against its verified payments — a half-paid
    # invoice owes half, not its face value. Without this the card contradicted
    # itself: invoiced ≠ paid + outstanding whenever a payment was partial.
    paid_by_inv: dict = {}
    for p in payments:
        paid_by_inv[p.invoice_id] = paid_by_inv.get(p.invoice_id, 0.0) + float(p.amount or 0)
    outstanding    = float(sum(
        max(0.0, float(i.total or 0) - paid_by_inv.get(i.id, 0.0))
        for i in invoices
        if i.status in OUTSTANDING_INVOICE_STATUSES
    ))
    # "overdue" is not a status the app sets — it's a due date in the past on
    # an unpaid invoice.
    overdue_count = sum(
        1 for i in invoices
        if i.status in OUTSTANDING_INVOICE_STATUSES
        and i.due_date and i.due_date < date.today()
    )

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


class StageTaskPatch(BaseModel):
    note: str | None = None
    due_at: datetime | None = None


@router.patch("/{customer_id}/stage-tasks/{task_key}")
async def patch_stage_task(
    customer_id: UUID,
    task_key: str,
    payload: StageTaskPatch,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Edit a stage task — set a custom due date or add a note."""
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
    if payload.note is not None:
        # Keep the title visible on the calendar when the user clears the note
        from app.core.stage_playbook import playbook_for
        item = next((t for t in playbook_for(c.stage) if t["key"] == task_key), None)
        if payload.note.strip():
            r.message = payload.note.strip()
        elif item:
            r.message = item["title"]
    if payload.due_at is not None:
        r.due_at = payload.due_at
    return {
        "id": str(r.id),
        "status": r.status,
        "due_at": r.due_at,
        "note": r.message,
    }


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


# ─── Stage-move request (with reason + supporting files) ─────────────────────


@router.post("/{customer_id}/request-stage-move", status_code=201)
async def request_stage_move(
    customer_id: UUID,
    target_stage: str = Form(...),
    reason: str = Form(...),
    files: list[UploadFile] = File(default=[]),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Sales/admin requests a stage move with a written reason and optional
    supporting files. A manager or director sees all of this in /approvals
    and either of them can approve it.

    Managers and directors short-circuit — their own stage moves apply
    directly (they hold the approval authority) via this endpoint or
    PATCH /customers/:id.
    """
    from app.core.config import settings
    from app.models.attachment import Attachment

    obj = await db.get(Customer, customer_id)
    if not obj or obj.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if Role(user.role) == Role.SALES and obj.sales_pic_id != user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Sales can only request moves on own customers"
        )
    if not reason.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Reason is required")
    if target_stage == obj.stage:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Customer is already in stage '{target_stage}'",
        )
    if is_forward_skip(obj.stage, target_stage):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Can't skip from '{obj.stage}' straight to '{target_stage}'. "
            "Move one stage at a time — each stage must be approved before "
            "the next.",
        )
    # Managers and directors hold approval authority — apply directly, no
    # approval queue.
    if Role(user.role) in (Role.MANAGER, Role.DIRECTOR):
        prev_stage = obj.stage
        obj.stage = target_stage
        obj.updated_by = user.id
        if prev_stage != target_stage:
            await ensure_stage_tasks(db, obj, target_stage)
        await audit_record(
            db, actor=user, action="update", entity="customer",
            entity_id=obj.id,
            before={"stage": prev_stage},
            after={"stage": target_stage, "reason": reason},
        )
        return {"applied": True, "stage": target_stage}

    # Otherwise create an approval request that a manager or director can clear.
    req = await request_approval(
        db,
        target_type="customer",
        target_id=obj.id,
        requested_by=user.id,
        required_role=Role.MANAGER,
        reason=f"Move {obj.stage} → {target_stage}: {reason.strip()}",
        payload={
            "changes": {"stage": target_stage},
            "from_stage": obj.stage,
            "to_stage": target_stage,
            "narrative": reason.strip(),
        },
    )

    # Save supporting files (if any) tied to this request.
    saved_count = 0
    if files:
        for f in files:
            if not f.filename:
                continue
            data = await f.read()
            if not data:
                continue
            if len(data) > 20 * 1024 * 1024:
                raise HTTPException(
                    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    f"{f.filename}: max 20 MB per file",
                )
            safe = "".join(
                ch if (ch.isalnum() or ch in "._- ") else "_"
                for ch in f.filename
            )[:200]
            storage_path = await storage.save(data, filename=safe)
            db.add(Attachment(
                owner_type="approval_request",
                owner_id=req.id,
                filename=safe,
                content_type=f.content_type,
                size=len(data),
                storage_path=storage_path,
                description=f"[stage-move] {target_stage}",
                uploaded_by=user.id,
            ))
            saved_count += 1
        await db.flush()

    return {
        "request_id": str(req.id),
        "target_stage": target_stage,
        "files_attached": saved_count,
    }


@router.get("/{customer_id}/stage-history")
async def stage_history(
    customer_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """The paper trail of the deal pipeline: every stage move with the
    reason that was written when it was requested/applied.

    Sources:
      • ApprovalRequests (sales-requested moves) — carry the narrative,
        the requester, the decision and who made it.
      • AuditLog rows (direct manager/director moves) — carry the reason
        written at apply time.
    Document-driven bumps (quotation approved → 'quotation', etc.) have
    no narrative and appear as plain moves from the audit trail only if
    they were audited with a stage change.
    """
    obj = await db.get(Customer, customer_id)
    if not obj or obj.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if Role(user.role) == Role.SALES and obj.sales_pic_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Out of scope")

    from app.models.approval import ApprovalRequest
    from app.models.audit import AuditLog

    entries: list[dict] = []
    user_ids: set[UUID] = set()

    reqs = (await db.scalars(
        select(ApprovalRequest).where(
            ApprovalRequest.target_type == "customer",
            ApprovalRequest.target_id == customer_id,
        )
    )).all()
    for r in reqs:
        p = r.payload or {}
        if not p.get("to_stage"):
            continue
        if r.requested_by:
            user_ids.add(r.requested_by)
        if r.decided_by:
            user_ids.add(r.decided_by)
        entries.append({
            "from_stage": p.get("from_stage"),
            "to_stage": p.get("to_stage"),
            "reason": p.get("narrative"),
            "status": r.status,  # pending / approved / rejected
            "requested_by": str(r.requested_by) if r.requested_by else None,
            "decided_by": str(r.decided_by) if r.decided_by else None,
            "decision_notes": r.decision_notes,
            "at": (r.decided_at or r.created_at),
            "source": "request",
        })

    audits = (await db.scalars(
        select(AuditLog).where(
            AuditLog.entity == "customer",
            AuditLog.entity_id == customer_id,
        ).order_by(AuditLog.occurred_at.asc())
    )).all()
    for a in audits:
        after = a.after or {}
        before = a.before or {}
        if "stage" not in after or after.get("stage") == before.get("stage"):
            continue
        if a.actor_id:
            user_ids.add(a.actor_id)
        entries.append({
            "from_stage": before.get("stage"),
            "to_stage": after.get("stage"),
            "reason": after.get("reason"),
            "status": "applied",
            "requested_by": str(a.actor_id) if a.actor_id else None,
            "decided_by": None,
            "decision_notes": None,
            "at": a.occurred_at,
            "source": "direct",
        })

    names: dict[str, str] = {}
    if user_ids:
        for u in (await db.scalars(
            select(User).where(User.id.in_(list(user_ids)))
        )).all():
            names[str(u.id)] = u.full_name
    for e in entries:
        e["requested_by_name"] = names.get(e["requested_by"] or "")
        e["decided_by_name"] = names.get(e["decided_by"] or "")

    entries.sort(key=lambda e: e["at"] or datetime.min.replace(tzinfo=UTC),
                 reverse=True)
    return entries


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
    lines.append(_csv_row(["Transmisi Eng — Customer report"]))
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


def _customer_export_sections(s: dict) -> list[dict]:
    """Build tabular_export sections from a customer summary (shared by the
    PDF and Excel exporters; mirrors the CSV layout)."""
    cust = s["customer"]
    stats = s["stats"]
    sections: list[dict] = [
        {
            "name": "Profile",
            "headers": ["Field", "Value"],
            "rows": [
                ["Company name", cust["company_name"]],
                ["Industry", cust["industry"]],
                ["Stage", cust["stage"]],
                ["PIC name", cust["pic_name"] or ""],
                ["PIC position", cust["pic_position"] or ""],
                ["Phone", cust["phone"] or ""],
                ["WhatsApp", cust["whatsapp"] or ""],
                ["Email", cust["email"] or ""],
                ["Company address", cust["company_address"] or ""],
                ["Delivery address", cust["delivery_address"] or ""],
                ["Customer since", str(cust["created_at"] or "")],
                ["Lost reason", cust.get("lost_reason") or ""],
            ],
        },
        {
            "name": "Financial summary",
            "headers": ["Metric", "Value"],
            "rows": [
                ["Lifetime value", _fmt_idr(cust["lifetime_value"])],
                ["Total quoted (all-time)", _fmt_idr(stats["total_quoted"])],
                ["Won revenue", _fmt_idr(stats["won_revenue"])],
                ["Pipeline (open quotes)", _fmt_idr(stats["pipeline_value"])],
                ["Total invoiced", _fmt_idr(stats["total_invoiced"])],
                ["Total paid", _fmt_idr(stats["total_paid"])],
                ["Outstanding AR", _fmt_idr(stats["outstanding_ar"])],
            ],
        },
        {
            "name": "Engagement",
            "headers": ["Metric", "Value"],
            "rows": [
                ["Quotations · total", stats["total_quotations"]],
                ["Quotations · open", stats["open_quotations"]],
                ["Quotations · won", stats["won"]],
                ["Quotations · lost", stats["lost"]],
                ["Win rate", f"{stats['win_rate'] * 100:.1f}%"],
                ["Projects · active", stats["active_projects"]],
                ["Projects · completed", stats["completed_projects"]],
                ["Overdue invoices", stats["overdue_invoices"]],
                ["Activities logged", stats["activities_logged"]],
            ],
        },
        {
            "name": "Quotations",
            "headers": ["Number", "Status", "Variant", "Discount %", "Total", "Valid until"],
            "rows": [[
                q["number"], q["status"], q["variant"],
                f"{q['discount_pct']:.1f}", _fmt_idr(q["total"]), str(q["valid_until"] or ""),
            ] for q in s["quotations"]],
        },
        {
            "name": "Projects",
            "headers": ["Code", "Status", "PO Number", "PO Value", "Target", "Actual"],
            "rows": [[
                p["code"], p["status"], p["po_number"] or "", _fmt_idr(p["po_value"]),
                str(p["target_delivery"] or ""), str(p["actual_delivery"] or ""),
            ] for p in s["projects"]],
        },
        {
            "name": "Invoices",
            "headers": ["Number", "Type", "Issue", "Due", "Total", "Status"],
            "rows": [[
                i["number"], i["type"], str(i["issue_date"] or ""), str(i["due_date"] or ""),
                _fmt_idr(i["total"]), i["status"],
            ] for i in s["invoices"]],
        },
    ]
    return sections


@router.get("/{customer_id}/export.pdf")
async def export_customer_pdf(
    customer_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    c = await db.get(Customer, customer_id)
    if not c or c.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if not can_view_customer(user, c.sales_pic_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Out of scope")
    s = await _build_summary(db, c)
    from app.services.tabular_export import render_pdf
    data = render_pdf(f"Customer report — {c.company_name}", _customer_export_sections(s))
    safe = "".join(ch if ch.isalnum() else "_" for ch in c.company_name)[:60]
    return Response(
        content=data, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe}_customer-report.pdf"'},
    )


@router.get("/{customer_id}/export.xlsx")
async def export_customer_xlsx(
    customer_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    c = await db.get(Customer, customer_id)
    if not c or c.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if not can_view_customer(user, c.sales_pic_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Out of scope")
    s = await _build_summary(db, c)
    from app.services.tabular_export import render_xlsx
    data = render_xlsx(f"Customer report — {c.company_name}", _customer_export_sections(s))
    safe = "".join(ch if ch.isalnum() else "_" for ch in c.company_name)[:60]
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{safe}_customer-report.xlsx"'},
    )

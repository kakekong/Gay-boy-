"""Calendar — aggregates time-bound events across modules."""

from datetime import date, datetime, time, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.permissions import Role
from app.models.crm import Activity, Customer, Reminder
from app.models.finance import Invoice
from app.models.operation import Project
from app.models.quotation import Quotation
from app.models.user import User

router = APIRouter()


# ─── Calendar event aggregation ──────────────────────────────────────────────


@router.get("/events")
async def list_events(
    range_from: date = Query(alias="from"),
    range_to: date = Query(alias="to"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if range_to < range_from:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "to < from")
    if (range_to - range_from).days > 366:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "range too wide")

    sales_only = Role(user.role) == Role.SALES
    start_dt = datetime.combine(range_from, time.min)
    end_dt = datetime.combine(range_to, time.max)

    events: list[dict] = []

    # Reminders
    rem_stmt = select(Reminder).where(
        Reminder.due_at >= start_dt, Reminder.due_at <= end_dt
    )
    if sales_only:
        rem_stmt = rem_stmt.where(Reminder.user_id == user.id)
    for r in (await db.scalars(rem_stmt)).all():
        events.append({
            "id": f"reminder:{r.id}",
            "kind": "reminder",
            "title": r.message or r.kind.replace("_", " ").title(),
            "subtype": r.kind,
            "at": r.due_at,
            "status": r.status,
            "link": None,
            "color": _color_for_reminder(r.kind),
        })

    # Activities (logged interactions)
    act_stmt = select(Activity, Customer).join(
        Customer, Activity.customer_id == Customer.id
    ).where(Activity.occurred_at >= start_dt, Activity.occurred_at <= end_dt)
    if sales_only:
        act_stmt = act_stmt.where(Customer.sales_pic_id == user.id)
    for a, c in (await db.execute(act_stmt)).all():
        events.append({
            "id": f"activity:{a.id}",
            "kind": "activity",
            "title": f"{a.type.replace('_', ' ').title()} · {c.company_name}",
            "subtype": a.type,
            "at": a.occurred_at,
            "status": a.direction,
            "link": f"/customers/{c.id}",
            "color": "ink",
        })

    # Quotation valid_until
    quote_stmt = select(Quotation, Customer).join(
        Customer, Quotation.customer_id == Customer.id
    ).where(
        Quotation.valid_until.is_not(None),
        Quotation.valid_until >= range_from,
        Quotation.valid_until <= range_to,
        Quotation.status.in_(["sent", "approved", "pending_approval", "draft"]),
    )
    if sales_only:
        quote_stmt = quote_stmt.where(Quotation.sales_pic_id == user.id)
    for q, c in (await db.execute(quote_stmt)).all():
        events.append({
            "id": f"quote:{q.id}",
            "kind": "quotation_expiry",
            "title": f"Quote expires · {q.number} · {c.company_name}",
            "subtype": q.status,
            "at": datetime.combine(q.valid_until, time(17, 0)),
            "status": q.status,
            "link": f"/quotations/{q.id}",
            "color": "violet",
        })

    # Invoice due dates
    inv_stmt = select(Invoice, Customer).join(
        Customer, Invoice.customer_id == Customer.id
    ).where(
        Invoice.due_date.is_not(None),
        Invoice.due_date >= range_from,
        Invoice.due_date <= range_to,
        Invoice.status.in_(["draft", "issued", "partial", "overdue"]),
    )
    if sales_only:
        inv_stmt = inv_stmt.where(Customer.sales_pic_id == user.id)
    for inv, c in (await db.execute(inv_stmt)).all():
        events.append({
            "id": f"invoice:{inv.id}",
            "kind": "payment_due",
            "title": f"Invoice due · {inv.number} · {c.company_name}",
            "subtype": inv.status,
            "at": datetime.combine(inv.due_date, time(12, 0)),
            "status": inv.status,
            "link": None,
            "color": "red" if inv.status == "overdue" else "amber",
        })

    # Project target deliveries
    proj_stmt = select(Project, Customer).join(
        Customer, Project.customer_id == Customer.id
    ).where(
        Project.target_delivery.is_not(None),
        Project.target_delivery >= range_from,
        Project.target_delivery <= range_to,
        Project.status.notin_(["closed"]),
    )
    if sales_only:
        proj_stmt = proj_stmt.where(Customer.sales_pic_id == user.id)
    for p, c in (await db.execute(proj_stmt)).all():
        events.append({
            "id": f"project:{p.id}",
            "kind": "delivery",
            "title": f"Target delivery · {p.code} · {c.company_name}",
            "subtype": p.status,
            "at": datetime.combine(p.target_delivery, time(10, 0)),
            "status": p.status,
            "link": None,
            "color": "emerald",
        })

    events.sort(key=lambda e: e["at"])
    return events


def _color_for_reminder(kind: str) -> str:
    return {
        "follow_up":  "brand",
        "after_sales":"violet",
        "delivery":   "emerald",
        "payment_due":"amber",
    }.get(kind, "ink")


# ─── Reminder CRUD (used by the calendar's "+ New reminder" form) ────────────


class ReminderCreate(BaseModel):
    customer_id: UUID | None = None
    kind: str = "follow_up"
    due_at: datetime
    channel: str = "dashboard"
    message: str | None = None


@router.post("/reminders", status_code=201)
async def create_reminder(
    payload: ReminderCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    r = Reminder(
        customer_id=payload.customer_id,
        user_id=user.id,
        kind=payload.kind,
        due_at=payload.due_at,
        channel=payload.channel,
        message=payload.message,
        status="pending",
    )
    db.add(r)
    await db.flush()
    return {"id": str(r.id), "ok": True}


@router.patch("/reminders/{reminder_id}/done")
async def mark_done(
    reminder_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    r = await db.get(Reminder, reminder_id)
    if not r:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if r.user_id != user.id and Role(user.role) == Role.SALES:
        raise HTTPException(status.HTTP_403_FORBIDDEN)
    r.status = "done"
    return {"ok": True}


# Convenience: tomorrow as a default for forms
@router.get("/defaults")
async def defaults():
    return {"tomorrow": (date.today() + timedelta(days=1)).isoformat()}

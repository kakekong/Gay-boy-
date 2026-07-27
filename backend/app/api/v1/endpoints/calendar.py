"""Calendar — aggregates time-bound events across modules."""

from datetime import date, datetime, time, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.permissions import Role, require_min
from app.core.stage_playbook import playbook_for
from app.core.stage_tasks import parse_stage_task_kind
from app.models.crm import Activity, Customer, Reminder
from app.models.finance import Invoice, OUTSTANDING_INVOICE_STATUSES
from app.models.operation import Project
from app.models.quotation import Quotation
from app.models.user import User

router = APIRouter(
    # Internal-only surface. External portal accounts (customer /
    # supplier, hierarchy tier 0) must never reach the CRM, pricing,
    # calendar or notification data — they have /portal/* instead.
    dependencies=[Depends(require_min(Role.SALES))]
)


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

    role = Role(user.role)
    sales_only = role == Role.SALES
    oversight = role in (Role.MANAGER, Role.DIRECTOR)
    # Purchasing stays customer-blind everywhere, the calendar included.
    blind = role == Role.PURCHASING
    start_dt = datetime.combine(range_from, time.min)
    end_dt = datetime.combine(range_to, time.max)

    events: list[dict] = []

    # Reminders (incl. auto-generated per-stage checklist items). Stage
    # tasks are routed by the playbook's owning roles — finance sees
    # invoicing chores, purchasing sees purchasing chores, admin sees
    # delivery chores — instead of every role seeing every task. Manual
    # reminders stay private to their creator (managers+ see all).
    rem_stmt = (
        select(Reminder, Customer)
        .outerjoin(Customer, Reminder.customer_id == Customer.id)
        .where(Reminder.due_at >= start_dt, Reminder.due_at <= end_dt)
    )
    if sales_only:
        rem_stmt = rem_stmt.where(Reminder.user_id == user.id)
    for r, c in (await db.execute(rem_stmt)).all():
        # Pretty-print stage tasks like "Lead · Make first contact · PT Bara Kalsel"
        stage_info = parse_stage_task_kind(r.kind)
        if stage_info:
            stg, task_key = stage_info
            item = next((t for t in playbook_for(stg) if t["key"] == task_key), None)
            if not oversight:
                owner_roles = set((item.get("roles") if item else None) or ["sales"])
                if role.value not in owner_roles:
                    continue
            task_title = item["title"] if item else (r.message or task_key)
            cust_label = "—" if blind else (c.company_name if c else "—")
            title = f"{stg.replace('_', ' ').title()} · {task_title} · {cust_label}"
            subtype = f"stage:{stg}"
            color = "red" if r.status == "pending" and r.due_at <= datetime.now(r.due_at.tzinfo) else "brand"
        else:
            if not oversight and r.user_id != user.id:
                continue
            title = r.message or r.kind.replace("_", " ").title()
            if c and not blind:
                title = f"{title} · {c.company_name}"
            subtype = r.kind
            color = _color_for_reminder(r.kind)
        events.append({
            "id": f"reminder:{r.id}",
            "kind": "stage_task" if stage_info else "reminder",
            "title": title,
            "subtype": subtype,
            "at": r.due_at,
            "status": r.status,
            "link": f"/customers/{c.id}" if c and not blind else None,
            "color": color,
        })

    # Activities (logged interactions) — CRM ground: sales + oversight only.
    if sales_only or oversight:
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

    # Quotation valid_until — deal ground: sales + oversight only.
    if sales_only or oversight:
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

    # Invoice due dates — finance's queue; sales sees their own customers'.
    if role == Role.FINANCE or sales_only or oversight:
        inv_stmt = select(Invoice, Customer).join(
            Customer, Invoice.customer_id == Customer.id
        ).where(
            Invoice.due_date.is_not(None),
            Invoice.due_date >= range_from,
            Invoice.due_date <= range_to,
            Invoice.status.in_(("draft",) + OUTSTANDING_INVOICE_STATUSES),
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
                "color": "red" if inv.due_date < date.today() else "amber",
            })

    # Project target deliveries — everyone who works projects, but the
    # customer name stays hidden from purchasing.
    proj_stmt = select(Project, Customer).join(
        Customer, Project.customer_id == Customer.id
    ).where(
        Project.is_deleted.is_(False),
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
            "title": f"Target delivery · {p.code}"
                     + ("" if blind else f" · {c.company_name}"),
            "subtype": p.status,
            "at": datetime.combine(p.target_delivery, time(10, 0)),
            "status": p.status,
            "link": None,
            "color": "emerald",
        })

    # Reminder.due_at is timezone-aware while the datetime.combine() rows
    # above are naive — comparing them raises. Coerce naive → UTC for the
    # sort so mixed event types can share a calendar without crashing.
    from datetime import timezone as _tz
    events.sort(key=lambda e: e["at"] if e["at"].tzinfo
                else e["at"].replace(tzinfo=_tz.utc))
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
    recurs: str = "none"           # none | daily | weekly | biweekly | monthly
    recurs_until: date | None = None


def _next_due(current: datetime, recurs: str) -> datetime | None:
    """Compute the next due_at for a recurring reminder, or None if it ended."""
    if recurs == "daily":      return current + timedelta(days=1)
    if recurs == "weekly":     return current + timedelta(days=7)
    if recurs == "biweekly":   return current + timedelta(days=14)
    if recurs == "monthly":
        # Add ~30 days (good enough for follow-up cadence; calendar-month edge
        # cases not worth the complexity here)
        return current + timedelta(days=30)
    return None


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
        recurs=payload.recurs or "none",
        recurs_until=payload.recurs_until,
    )
    db.add(r)
    await db.flush()
    return {"id": str(r.id), "ok": True, "recurs": r.recurs}


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

    # Chain the next instance if recurring and not past the end date
    next_id: str | None = None
    if r.recurs and r.recurs != "none":
        nxt = _next_due(r.due_at, r.recurs)
        if nxt is not None:
            end = r.recurs_until
            nxt_d = nxt.date() if hasattr(nxt, "date") else nxt
            if end is None or nxt_d <= end:
                child = Reminder(
                    customer_id=r.customer_id,
                    user_id=r.user_id,
                    kind=r.kind,
                    due_at=nxt,
                    channel=r.channel,
                    message=r.message,
                    status="pending",
                    recurs=r.recurs,
                    recurs_until=r.recurs_until,
                    parent_reminder_id=r.parent_reminder_id or r.id,
                )
                db.add(child)
                await db.flush()
                next_id = str(child.id)
    return {"ok": True, "next_reminder_id": next_id}


# Convenience: tomorrow as a default for forms
@router.get("/defaults")
async def defaults():
    return {"tomorrow": (date.today() + timedelta(days=1)).isoformat()}

"""Closing reminders — by hand, or because the follow-up has happened.

A follow-up reminder is a promise to contact the customer. Once a call, a
visit or a WhatsApp to that customer is logged, the promise is kept; leaving
the reminder open made My Queue grow with work that was already done.
"""
from datetime import datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.stage_tasks import parse_stage_task_kind
from app.models.crm import Reminder

# Reminders a contact with the customer answers. A delivery check or a payment
# chase isn't done just because someone rang.
CONTACT_KINDS = ("follow_up", "after_sales")


def is_contact(activity_type: str, direction: str | None) -> bool:
    """A logged activity that is real contact with the customer — not a note
    to self, nor something the system logged (a quotation export)."""
    return activity_type != "note" and (direction or "") != "internal"


def _next_due(current: datetime, recurs: str) -> datetime | None:
    """The next due_at for a recurring reminder, or None if it doesn't repeat."""
    # Monthly is ~30 days: good enough for a follow-up cadence.
    days = {"daily": 1, "weekly": 7, "biweekly": 14, "monthly": 30}.get(recurs)
    return current + timedelta(days=days) if days else None


async def complete(db: AsyncSession, r: Reminder) -> Reminder | None:
    """Mark a reminder done; a repeating one schedules its next time.
    Returns the next instance, if one was made."""
    r.status = "done"
    if not r.recurs or r.recurs == "none" or not r.due_at:
        return None
    nxt = _next_due(r.due_at, r.recurs)
    if nxt is None or (r.recurs_until is not None and nxt.date() > r.recurs_until):
        return None
    child = Reminder(
        customer_id=r.customer_id, user_id=r.user_id, kind=r.kind, due_at=nxt,
        channel=r.channel, message=r.message, status="pending",
        recurs=r.recurs, recurs_until=r.recurs_until,
        parent_reminder_id=r.parent_reminder_id or r.id,
    )
    db.add(child)
    await db.flush()
    return child


async def close_due_followups(db: AsyncSession, customer_id: UUID) -> int:
    """A contact with the customer was just logged: close their follow-up
    reminders that are due by the end of today (office time). Later ones —
    "call again next Tuesday" — stay. Returns how many were closed."""
    tz = ZoneInfo(settings.TIMEZONE or "Asia/Jakarta")
    end_of_today = datetime.combine(datetime.now(tz).date() + timedelta(days=1),
                                    time.min, tzinfo=tz)
    rows = (await db.scalars(select(Reminder).where(
        Reminder.customer_id == customer_id,
        Reminder.status == "pending",
        Reminder.kind.in_(CONTACT_KINDS),
        Reminder.due_at < end_of_today,
    ))).all()
    n = 0
    for r in rows:
        if parse_stage_task_kind(r.kind):
            continue
        await complete(db, r)
        n += 1
    return n

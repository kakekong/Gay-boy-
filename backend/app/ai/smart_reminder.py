"""Smart Reminder Engine — AI timing for follow-ups + Top Actions ranking."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import deal_risk
from app.models.crm import Activity, Reminder


async def top_actions_for(db: AsyncSession, *, user_id: UUID, limit: int = 10) -> list[dict]:
    """Rank pending tasks for a sales user by AI priority."""
    reminders = (await db.scalars(
        select(Reminder).where(
            Reminder.user_id == user_id,
            Reminder.status == "pending",
        ).order_by(Reminder.due_at.asc()).limit(50)
    )).all()

    risk_index = {
        r["customer_id"]: r for r in await deal_risk.list_at_risk(db, limit=100)
    }

    out = []
    for r in reminders:
        priority = _priority(r, risk_index)
        out.append({
            "reminder_id": str(r.id),
            "customer_id": str(r.customer_id) if r.customer_id else None,
            "kind": r.kind,
            "due_at": r.due_at.isoformat(),
            "ai_optimal_at": r.ai_optimal_at.isoformat() if r.ai_optimal_at else None,
            "channel": r.channel,
            "message": r.message,
            "priority_score": priority,
        })
    return sorted(out, key=lambda x: -x["priority_score"])[:limit]


def _priority(r: Reminder, risk_index: dict) -> float:
    base = 1.0
    risk = risk_index.get(str(r.customer_id) if r.customer_id else None)
    if risk:
        base += {"low": 0, "medium": 0.5, "high": 1.5}.get(risk["risk_level"], 0)
    if r.kind == "payment_due":
        base += 0.8
    if r.kind == "follow_up":
        base += 0.3
    # Time pressure
    delta_h = (r.due_at - datetime.now(UTC)).total_seconds() / 3600.0
    if delta_h < 0:
        base += 1.0  # overdue
    elif delta_h < 24:
        base += 0.5
    return round(base, 3)


async def compute_optimal_time(db: AsyncSession, *, customer_id: UUID) -> datetime:
    """Pick best timestamp in next 48h based on inbound reply hour-of-day histogram."""
    msgs = (await db.scalars(
        select(Activity).where(
            Activity.customer_id == customer_id,
            Activity.direction == "inbound",
        ).limit(200)
    )).all()
    if not msgs:
        # default: tomorrow 09:00 local time
        target = datetime.now(UTC) + timedelta(days=1)
        return target.replace(hour=2, minute=0, second=0, microsecond=0)  # 09:00 WIB ~ 02:00 UTC
    hist = [0] * 24
    for m in msgs:
        hist[m.occurred_at.hour] += 1
    best_hour = hist.index(max(hist))
    target = datetime.now(UTC) + timedelta(days=1)
    return target.replace(hour=best_hour, minute=0, second=0, microsecond=0)

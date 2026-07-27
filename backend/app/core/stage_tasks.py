"""Stage-task helpers.

Reuses the Reminder model with a structured `kind` field:
    stage:<stage>:<task_key>

This keeps the data model small (no new table) while still letting us
query, complete, and notify on per-stage required tasks.
"""

from datetime import UTC, datetime, timedelta
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.stage_playbook import playbook_for
from app.models.crm import Customer, Reminder


def stage_task_kind(stage: str, task_key: str) -> str:
    return f"stage:{stage}:{task_key}"


def parse_stage_task_kind(kind: str) -> tuple[str, str] | None:
    """Return (stage, task_key) if this kind is a stage task, else None."""
    if not kind.startswith("stage:"):
        return None
    parts = kind.split(":", 2)
    if len(parts) != 3:
        return None
    return parts[1], parts[2]


async def close_superseded_stage_tasks(
    db: AsyncSession, customer: Customer, stage: str,
) -> int:
    """Close pending tasks belonging to stages the deal has already left.

    The customer page only renders the checklist for the CURRENT stage, and
    the complete/reopen endpoints derive the reminder kind from the current
    stage too. So a task left pending on an earlier stage could never be
    ticked again — it just kept firing "Overdue: …" in the bell, the calendar
    and the AI queue forever. Worst case is closed_won / closed_lost, which
    have no playbook at all.

    Anything from a strictly earlier stage is marked done (the deal moved on).
    Backward moves are safe: a task for the stage you returned to, or any
    later one, is left alone.
    """
    from app.core.stage_playbook import stage_index
    here = stage_index(stage)
    if here < 0:
        return 0
    rows = (await db.scalars(
        select(Reminder).where(
            Reminder.customer_id == customer.id,
            Reminder.kind.like("stage:%"),
            Reminder.status == "pending",
        )
    )).all()
    closed = 0
    for r in rows:
        parsed = parse_stage_task_kind(r.kind)
        if not parsed:
            continue
        task_stage, _key = parsed
        idx = stage_index(task_stage)
        if 0 <= idx < here:
            r.status = "done"
            closed += 1
    return closed


async def ensure_stage_tasks(
    db: AsyncSession, customer: Customer, stage: str,
) -> list[Reminder]:
    """Spawn missing reminders for this stage's playbook.

    Idempotent: existing reminders (any status) for the same (customer, kind)
    are left alone. Returns the list of *newly created* reminders so the
    caller can audit them.
    """
    # Always retire earlier-stage leftovers first — this must run even when
    # the new stage has no playbook (closed_won / closed_lost), which is why
    # it sits above the early returns below.
    await close_superseded_stage_tasks(db, customer, stage)

    if not customer.sales_pic_id:
        return []  # nothing to assign

    tasks = playbook_for(stage)
    if not tasks:
        return []

    kinds = [stage_task_kind(stage, t["key"]) for t in tasks]
    existing = (await db.scalars(
        select(Reminder).where(
            Reminder.customer_id == customer.id,
            Reminder.kind.in_(kinds),
        )
    )).all()
    have = {r.kind for r in existing}

    created: list[Reminder] = []
    for t in tasks:
        k = stage_task_kind(stage, t["key"])
        if k in have:
            continue
        r = Reminder(
            customer_id=customer.id,
            user_id=customer.sales_pic_id,
            kind=k,
            # No automatic deadline: the task appears on the checklist only.
            # It reaches the calendar + notifications when a user sets a
            # date on it (PATCH /customers/{id}/stage-tasks/{key}).
            due_at=None,
            status="pending",
            channel="in_app",
            message=t["title"],
        )
        db.add(r)
        created.append(r)
    if created:
        await db.flush()
    return created


async def stage_tasks_for(
    db: AsyncSession, customer: Customer, stage: str | None = None,
) -> list[dict]:
    """Return all stage-task rows for a customer (optionally filtered to
    a single stage) merged with the playbook metadata.
    """
    stage = stage or customer.stage
    tasks = playbook_for(stage)
    if not tasks:
        return []

    kinds = [stage_task_kind(stage, t["key"]) for t in tasks]
    rows = (await db.scalars(
        select(Reminder).where(
            Reminder.customer_id == customer.id,
            Reminder.kind.in_(kinds),
        )
    )).all()
    by_kind = {r.kind: r for r in rows}

    out: list[dict] = []
    for t in tasks:
        k = stage_task_kind(stage, t["key"])
        r = by_kind.get(k)
        # Stored note for a stage task is kept in Reminder.message; if it equals
        # the seeded title it counts as "no custom note yet".
        note = None
        if r and r.message and r.message != t["title"]:
            note = r.message
        out.append({
            "stage": stage,
            "key": t["key"],
            "title": t["title"],
            "hint": t["hint"],
            "due_after_days": t["due_after_days"],
            "reminder_id": str(r.id) if r else None,
            "status": r.status if r else "missing",  # pending / done / missing
            "due_at": r.due_at if r else None,
            "note": note,
            "completed_at": (
                r.updated_at if r and r.status == "done" else None
            ),
        })
    return out


def overdue_stage_reminders_stmt(user_id, now: datetime | None = None):
    """SQLA stmt for surfacing overdue pending stage tasks of a sales user."""
    now = now or datetime.now(UTC)
    return (
        select(Reminder)
        .where(
            Reminder.user_id == user_id,
            Reminder.status == "pending",
            Reminder.kind.like("stage:%"),
            Reminder.due_at <= now,
        )
        .order_by(Reminder.due_at.asc())
    )


def due_soon_stage_reminders_stmt(user_id, now: datetime | None = None,
                                  within_days: int = 2):
    now = now or datetime.now(UTC)
    soon = now + timedelta(days=within_days)
    return (
        select(Reminder)
        .where(
            Reminder.user_id == user_id,
            Reminder.status == "pending",
            Reminder.kind.like("stage:%"),
            Reminder.due_at > now,
            Reminder.due_at <= soon,
        )
        .order_by(Reminder.due_at.asc())
    )


def reminder_iter(stmt) -> Iterable[Reminder]:
    """Stub kept for future bulk operations."""
    raise NotImplementedError

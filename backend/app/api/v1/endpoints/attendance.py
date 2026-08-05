"""Attendance — clock in/out + salary integration.

- Everyone clocks themselves in/out
- HR / Director see all and can mark days manually (leave, absent, etc.)
- Director's salary form can pull attendance to compute per-day deductions
"""

from datetime import UTC, date as date_t, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.permissions import Role, require, require_min
from app.models.attachment import Attachment
from app.models.attendance import Attendance
from app.models.daily_log import DailyLog
from app.models.user import User

router = APIRouter(
    # Internal-only surface. External portal accounts (customer /
    # supplier, hierarchy tier 0) must never reach the CRM, pricing,
    # calendar or notification data — they have /portal/* instead.
    dependencies=[Depends(require_min(Role.SALES))]
)
_hr_or_director = require(Role.HR, Role.DIRECTOR)
# Who may read *other* people's daily logs (oversight). Everyone can read/write
# their own regardless of role.
_log_overseer = require(Role.HR, Role.MANAGER, Role.DIRECTOR)


VALID_STATUSES = {"present", "absent", "half_day", "leave", "wfh", "sick", "holiday"}


class ClockIn(BaseModel):
    """Optional note typed at the moment of clocking in or out — 'stuck in
    traffic on the toll road', 'leaving early for the site visit'. Shares the
    day's single `notes` column with HR's manual entries, so each line is
    labelled rather than overwriting what is already there."""
    note: str | None = None


class ManualIn(BaseModel):
    user_id: UUID
    date: date_t
    status: str = "present"
    hours: float = 8
    notes: str | None = None


class StatusPatch(BaseModel):
    status: str | None = None
    hours: float | None = None
    notes: str | None = None


async def _serialize(db: AsyncSession, a: Attendance) -> dict:
    u = await db.get(User, a.user_id)
    return {
        "id": str(a.id),
        "user_id": str(a.user_id),
        "user_name": u.full_name if u else None,
        "date": a.date,
        "clock_in": a.clock_in,
        "clock_out": a.clock_out,
        "hours": float(a.hours or 0),
        "status": a.status,
        "notes": a.notes,
    }


def _append_note(existing: str | None, label: str, note: str | None) -> str | None:
    """Add one labelled line to the day's notes, keeping whatever is there.

    Clocking out must never wipe the note written at clock-in, and HR's manual
    note has to survive both — one column, three possible authors, so append.
    """
    line = (note or "").strip()
    if not line:
        return existing
    return f"{(existing or '').rstrip()}\n{label}: {line}".strip()


@router.post("/clock-in", status_code=201)
async def clock_in(
    payload: ClockIn | None = None,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    today = date_t.today()
    existing = await db.scalar(
        select(Attendance).where(Attendance.user_id == me.id, Attendance.date == today)
    )
    if existing and existing.clock_in:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Already clocked in at {existing.clock_in.strftime('%H:%M')}")
    now = datetime.now(UTC)
    note = payload.note if payload else None
    if existing:
        existing.clock_in = now
        existing.status = "present"
        existing.notes = _append_note(existing.notes, "In", note)
        a = existing
    else:
        a = Attendance(user_id=me.id, date=today, clock_in=now, status="present",
                       notes=_append_note(None, "In", note))
        db.add(a)
    await db.flush()
    return await _serialize(db, a)


@router.post("/clock-out", status_code=200)
async def clock_out(
    payload: ClockIn | None = None,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    today = date_t.today()
    a = await db.scalar(
        select(Attendance).where(Attendance.user_id == me.id, Attendance.date == today)
    )
    if not a or not a.clock_in:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Not clocked in today")
    if a.clock_out:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Already clocked out at {a.clock_out.strftime('%H:%M')}")
    a.clock_out = datetime.now(UTC)
    delta = (a.clock_out - a.clock_in).total_seconds() / 3600
    a.hours = round(max(0, delta), 2)
    a.notes = _append_note(a.notes, "Out", payload.note if payload else None)
    await db.flush()
    return await _serialize(db, a)


@router.get("/me")
async def my_attendance(
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
    range_days: int = Query(30, ge=1, le=180),
):
    since = date_t.today() - timedelta(days=range_days)
    rows = (await db.scalars(
        select(Attendance)
        .where(Attendance.user_id == me.id, Attendance.date >= since)
        .order_by(Attendance.date.desc())
    )).all()
    return [await _serialize(db, a) for a in rows]


@router.get("/me/today")
async def my_today(
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    today = date_t.today()
    a = await db.scalar(
        select(Attendance).where(Attendance.user_id == me.id, Attendance.date == today)
    )
    if not a:
        return {"date": today, "clock_in": None, "clock_out": None, "hours": 0, "status": "not_started"}
    return await _serialize(db, a)


@router.get("")
async def list_attendance(
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_hr_or_director),
    user_id: UUID | None = None,
    period: str | None = Query(None, description="YYYY-MM"),
):
    stmt = select(Attendance).order_by(Attendance.date.desc(), Attendance.user_id)
    if user_id:
        stmt = stmt.where(Attendance.user_id == user_id)
    if period:
        try:
            y, m = period.split("-")
            start = date_t(int(y), int(m), 1)
            end = date_t(int(y) + (1 if m == "12" else 0),
                         1 if m == "12" else int(m) + 1, 1)
            stmt = stmt.where(Attendance.date >= start, Attendance.date < end)
        except ValueError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "period must be YYYY-MM")
    rows = (await db.scalars(stmt)).all()
    return [await _serialize(db, a) for a in rows]


@router.get("/summary-all")
async def summary_all(
    period: str = Query(..., description="YYYY-MM"),
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_hr_or_director),
):
    """Per-employee attendance roll-up for a month — powers the Attendance
    page's summary section. One row per active internal employee."""
    try:
        y, m = period.split("-")
        start = date_t(int(y), int(m), 1)
        end = date_t(int(y) + (1 if m == "12" else 0),
                     1 if m == "12" else int(m) + 1, 1)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "period must be YYYY-MM")

    workdays = 0
    d = start
    while d < end:
        if d.weekday() < 5:
            workdays += 1
        d += timedelta(days=1)

    users = (await db.scalars(
        select(User).where(
            User.is_active.is_(True),
            User.role.notin_(["customer", "supplier"]),
        ).order_by(User.full_name.asc())
    )).all()
    rows = (await db.scalars(
        select(Attendance).where(Attendance.date >= start, Attendance.date < end)
    )).all()
    by_user: dict = {}
    for a in rows:
        bucket = by_user.setdefault(a.user_id, {"counts": {}, "hours": 0.0})
        bucket["counts"][a.status] = bucket["counts"].get(a.status, 0) + 1
        bucket["hours"] += float(a.hours or 0)

    out = []
    for u in users:
        b = by_user.get(u.id, {"counts": {}, "hours": 0.0})
        c = b["counts"]
        present_like = c.get("present", 0) + c.get("wfh", 0)
        out.append({
            "user_id": str(u.id),
            "user_name": u.full_name,
            "role": u.role,
            "present_like_days": present_like,
            "absent_days": c.get("absent", 0),
            "half_days": c.get("half_day", 0),
            "leave_days": c.get("leave", 0) + c.get("sick", 0),
            "total_hours": round(b["hours"], 2),
            "counts": c,
        })
    return {"period": period, "workdays_in_month": workdays, "rows": out}


@router.post("/manual", status_code=201)
async def manual_entry(
    payload: ManualIn,
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_hr_or_director),
):
    if payload.status not in VALID_STATUSES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"status must be one of: {', '.join(sorted(VALID_STATUSES))}")
    existing = await db.scalar(
        select(Attendance).where(
            Attendance.user_id == payload.user_id, Attendance.date == payload.date
        )
    )
    if existing:
        existing.status = payload.status
        existing.hours = payload.hours
        existing.notes = payload.notes
        a = existing
    else:
        a = Attendance(
            user_id=payload.user_id, date=payload.date, status=payload.status,
            hours=payload.hours, notes=payload.notes,
        )
        db.add(a)
    await db.flush()
    return await _serialize(db, a)


@router.patch("/{attendance_id}")
async def update_status(
    attendance_id: UUID,
    payload: StatusPatch,
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_hr_or_director),
):
    a = await db.get(Attendance, attendance_id)
    if not a:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if payload.status and payload.status not in VALID_STATUSES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid status")
    if payload.status is not None: a.status = payload.status
    if payload.hours  is not None: a.hours = payload.hours
    if payload.notes  is not None: a.notes = payload.notes
    return await _serialize(db, a)


@router.get("/summary")
async def summary(
    user_id: UUID,
    period: str = Query(..., description="YYYY-MM"),
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_hr_or_director),
):
    """Per-period attendance summary — useful for salary calculations."""
    try:
        y, m = period.split("-")
        start = date_t(int(y), int(m), 1)
        end = date_t(int(y) + (1 if m == "12" else 0),
                     1 if m == "12" else int(m) + 1, 1)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "period must be YYYY-MM")
    rows = (await db.scalars(
        select(Attendance).where(
            Attendance.user_id == user_id,
            Attendance.date >= start, Attendance.date < end,
        )
    )).all()
    counts: dict[str, int] = {}
    total_hours = 0.0
    for a in rows:
        counts[a.status] = counts.get(a.status, 0) + 1
        total_hours += float(a.hours or 0)
    # Working days in the month, Mon-Fri
    workdays = 0
    d = start
    while d < end:
        if d.weekday() < 5:
            workdays += 1
        d += timedelta(days=1)
    present_like = counts.get("present", 0) + counts.get("wfh", 0)
    half = counts.get("half_day", 0)
    absent_like = counts.get("absent", 0)
    deductible_days = absent_like + (half * 0.5)
    return {
        "user_id": str(user_id),
        "period": period,
        "workdays_in_month": workdays,
        "counts": counts,
        "total_hours": round(total_hours, 2),
        "present_like_days": present_like,
        "absent_like_days": absent_like,
        "deductible_days": deductible_days,
    }


# ─── Daily log ────────────────────────────────────────────────────────────────
# A free-form journal of what you did today, with links + file attachments.
# Attendance says *when* you were here; the daily log says *what* you did.

_MAX_LINKS = 20
_MAX_BODY = 8000


class LogLink(BaseModel):
    label: str = ""
    url: str

    @field_validator("label")
    @classmethod
    def _cap_label(cls, v: str) -> str:
        return (v or "")[:200]

    @field_validator("url")
    @classmethod
    def _http_only(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("Link URL cannot be empty")
        if not (v.startswith("http://") or v.startswith("https://")):
            v = "https://" + v
        return v[:1000]


class DailyLogIn(BaseModel):
    date: date_t
    body: str | None = None
    links: list[LogLink] = []


async def _attach_count(db: AsyncSession, log_id: UUID) -> int:
    return await db.scalar(
        select(func.count(Attachment.id)).where(
            Attachment.owner_type == "daily_log", Attachment.owner_id == log_id
        )
    ) or 0


async def _log_out(db: AsyncSession, log: DailyLog, with_user: bool = False) -> dict:
    out = {
        "id": str(log.id),
        "user_id": str(log.user_id),
        "date": log.date,
        "body": log.body or "",
        "links": log.links or [],
        "file_count": await _attach_count(db, log.id),
        "updated_at": log.updated_at,
    }
    if with_user:
        u = await db.get(User, log.user_id)
        out["user_name"] = u.full_name if u else None
        out["user_role"] = u.role if u else None
    return out


@router.get("/daily-log")
async def get_daily_log(
    date: date_t = Query(..., description="YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    """The current user's own daily log for a date (or a stub if none yet)."""
    log = await db.scalar(
        select(DailyLog).where(DailyLog.user_id == me.id, DailyLog.date == date)
    )
    if not log:
        return {"id": None, "user_id": str(me.id), "date": date,
                "body": "", "links": [], "file_count": 0,
                "editable": date <= date_t.today()}
    out = await _log_out(db, log)
    out["editable"] = date <= date_t.today()
    return out


@router.put("/daily-log")
async def save_daily_log(
    payload: DailyLogIn,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    """Create or update the current user's daily log for a date.

    You can only write your own, and never for a future date.
    """
    if payload.date > date_t.today():
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Can't write a log for a future date")
    body = (payload.body or "").strip()[:_MAX_BODY]
    links = [ln.model_dump() for ln in payload.links][:_MAX_LINKS]
    log = await db.scalar(
        select(DailyLog).where(DailyLog.user_id == me.id, DailyLog.date == payload.date)
    )
    if log:
        log.body = body
        log.links = links
    else:
        log = DailyLog(user_id=me.id, date=payload.date, body=body, links=links)
        db.add(log)
        try:
            # Savepoint so a unique-collision (concurrent double-submit for the
            # same user+date) rolls back just this insert, not the whole txn.
            async with db.begin_nested():
                await db.flush()
        except IntegrityError:
            # The other write won — update its row instead of failing.
            log = await db.scalar(
                select(DailyLog).where(
                    DailyLog.user_id == me.id, DailyLog.date == payload.date)
            )
            if log is None:  # shouldn't happen, but never 500 on it
                raise HTTPException(status.HTTP_409_CONFLICT,
                                    "Log is being saved elsewhere; retry")
            log.body = body
            log.links = links
    await db.flush()
    # updated_at is a server-side timestamp — reload it before serializing so
    # attribute access doesn't lazy-fetch outside the async greenlet context.
    await db.refresh(log)
    return await _log_out(db, log)


@router.get("/daily-log/history")
async def daily_log_history(
    range_days: int = Query(30, ge=1, le=180),
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    """The current user's recent daily logs, newest first."""
    since = date_t.today() - timedelta(days=range_days)
    rows = (await db.scalars(
        select(DailyLog)
        .where(DailyLog.user_id == me.id, DailyLog.date >= since)
        .order_by(DailyLog.date.desc())
    )).all()
    return [await _log_out(db, log) for log in rows]


@router.get("/daily-log/team/days")
async def daily_log_team_days(
    range_days: int = Query(30, ge=1, le=180),
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_log_overseer),
):
    """Which recent days anyone actually wrote a log on, newest first.

    The team view shows one date at a time, and on a day nobody has written
    yet it has nothing to say — which reads as "there are no daily logs"
    rather than "not today". This gives the page somewhere to point: the days
    that do have entries, and how many each.
    """
    since = date_t.today() - timedelta(days=range_days)
    rows = (await db.execute(
        select(DailyLog.date, func.count(DailyLog.id))
        .where(DailyLog.date >= since)
        .group_by(DailyLog.date)
        .order_by(DailyLog.date.desc())
    )).all()
    return [{"date": d, "count": n} for d, n in rows]


@router.get("/daily-log/team")
async def daily_log_team(
    date: date_t = Query(..., description="YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_log_overseer),
):
    """HR / manager / director: every user's daily log for one date."""
    rows = (await db.scalars(
        select(DailyLog).where(DailyLog.date == date).order_by(DailyLog.updated_at.desc())
    )).all()
    return [await _log_out(db, log, with_user=True) for log in rows]

"""What a month of attendance does to a salary.

The working day comes from settings (`WORK_START`–`WORK_END` on `WORK_DAYS`,
local time `TIMEZONE`). Three things follow from it, each worked out per day
and then added up for the month:

* **Late** — clocking in more than `LATE_GRACE_MINUTES` after the start. Within
  the grace it costs nothing; past it, every minute late is deducted at the
  per-minute wage (monthly base ÷ `PAY_MONTHLY_HOURS` ÷ 60). Sixteen minutes
  late costs sixteen minutes, not one.
* **Absent** — a working day with no clock-in and nothing excusing it. One
  day's wage each (monthly base ÷ working days that month). Leave, sick,
  work-from-home and holiday days marked by HR are not absences; a half day
  counts as half. Days before the employee joined, and days not yet over,
  are not counted.
* **Overtime** — recorded by the director, by hand (`OvertimeEntry`), not
  read off clock-outs: clock times carry too many human errors, and a
  forgotten clock-out is hours of "overtime". Paid at the legal rate: the
  first hour at 1.5× the hourly wage and each hour after at 2×, per day, the
  day's recorded minutes rounded to the nearest hour (half an hour rounds
  up). A revoked entry is listed but not paid.

Only the base salary is the wage these are worked from — allowances are not.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.attendance import Attendance

EXCUSED = {"leave", "sick", "holiday", "wfh"}


def tz() -> ZoneInfo:
    return ZoneInfo(settings.TIMEZONE or "Asia/Jakarta")


def local_today() -> date:
    """Today where the office is — not where the server is. A 06:45 clock-in
    in Jakarta is 23:45 the day before in UTC."""
    return datetime.now(tz()).date()


def _hhmm(s: str) -> time:
    h, m = (s or "00:00").split(":")
    return time(int(h), int(m))


def work_start() -> time:
    return _hhmm(settings.WORK_START)


def work_end() -> time:
    return _hhmm(settings.WORK_END)


def work_days() -> set[int]:
    return {int(x) for x in (settings.WORK_DAYS or "0,1,2,3,4").split(",") if x.strip()}


def is_work_day(d: date) -> bool:
    return d.weekday() in work_days()


def month_bounds(period: str) -> tuple[date, date]:
    y, m = (int(x) for x in period.split("-"))
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def working_days_in(period: str) -> int:
    first, last = month_bounds(period)
    return sum(1 for i in range((last - first).days + 1)
               if is_work_day(first + timedelta(days=i)))


def raw_late_minutes(a: Attendance) -> int:
    """Minutes after the start of the day at clock-in, grace or not."""
    if not a.clock_in or not is_work_day(a.date):
        return 0
    local_in = a.clock_in.astimezone(tz())
    start = datetime.combine(a.date, work_start(), tzinfo=tz())
    return max(0, int((local_in - start).total_seconds() // 60))


def late_minutes(a: Attendance) -> int:
    """Minutes late at clock-in, or 0 inside the grace period."""
    mins = raw_late_minutes(a)
    return mins if mins > int(settings.LATE_GRACE_MINUTES) else 0


def overtime_minutes_at(a: Attendance) -> int:
    """Minutes past the end of the working day at clock-out."""
    if not a.clock_out:
        return 0
    local_out = a.clock_out.astimezone(tz())
    end = datetime.combine(a.date, work_end(), tzinfo=tz())
    return max(0, int((local_out - end).total_seconds() // 60))


def overtime_hours(minutes: int) -> int:
    """Approved minutes as paid hours — nearest hour, a half rounds up."""
    return int((minutes + 30) // 60)


def overtime_pay_for(hours: int, hourly: float) -> float:
    if hours <= 0:
        return 0.0
    return round(hourly * (1.5 * 1 + 2.0 * (hours - 1)), 2)


async def month_for(db: AsyncSession, user_id, period: str, base_salary: float,
                    *, join_date: date | None = None,
                    today: date | None = None) -> dict:
    """The month's attendance worked into pay: totals and the days behind them."""
    from app.models.attendance import OvertimeEntry
    first, last = month_bounds(period)
    rows = (await db.scalars(select(Attendance).where(
        Attendance.user_id == user_id,
        Attendance.date >= first, Attendance.date <= last))).all()
    entries = (await db.scalars(select(OvertimeEntry).where(
        OvertimeEntry.user_id == user_id,
        OvertimeEntry.date >= first, OvertimeEntry.date <= last))).all()
    return compute_month(rows, period, base_salary, join_date=join_date, today=today,
                         overtime=entries)


def compute_month(rows, period: str, base_salary: float, *,
                  join_date: date | None = None, today: date | None = None,
                  overtime=()) -> dict:
    """`month_for` without the database — given the month's attendance rows
    and the director's overtime entries. The worked examples on the payroll
    page run through this same code."""
    first, last = month_bounds(period)
    today = today or local_today()
    by_day = {a.date: a for a in rows}
    ot_by_day: dict[date, list] = {}
    for e in overtime:
        ot_by_day.setdefault(e.date, []).append(e)

    wdays = working_days_in(period)
    base = float(base_salary or 0)
    day_wage = base / wdays if wdays else 0.0
    hourly = base / float(settings.PAY_MONTHLY_HOURS or 173)
    per_minute = hourly / 60

    days: list[dict] = []
    late_total = 0
    absent_days = 0.0
    ot_hours_total = 0
    ot_pay_total = 0.0
    ot_pending = 0
    d = first
    while d <= last:
        a = by_day.get(d)
        line: dict | None = None
        counted = (is_work_day(d) and d < today
                   and (join_date is None or d >= join_date))
        if counted:
            status = a.status if a else None
            if a is None or status == "absent":
                absent_days += 1
                line = {"kind": "absent", "days": 1, "amount": round(day_wage, 2)}
            elif status == "half_day":
                absent_days += 0.5
                line = {"kind": "half_day", "days": 0.5, "amount": round(day_wage / 2, 2)}
            elif status in EXCUSED:
                # Shown so the payslip says why the day cost nothing.
                line = {"kind": "excused", "status": status, "amount": None}
            else:
                mins = late_minutes(a)
                raw = raw_late_minutes(a)
                if not mins and raw > 0:
                    line = {"kind": "grace", "minutes": raw,
                            "clock_in": a.clock_in.astimezone(tz()).strftime("%H:%M"),
                            "amount": None}
                if mins:
                    late_total += mins
                    line = {"kind": "late", "minutes": mins,
                            "clock_in": a.clock_in.astimezone(tz()).strftime("%H:%M"),
                            "amount": round(mins * per_minute, 2)}
        # Overtime the director recorded for this day. The legal rate runs
        # per day (first hour 1.5×, then 2×), so a day's live entries are
        # added together before rounding; a revoked one is listed, unpaid.
        day_entries = ot_by_day.get(d, [])
        live = [e for e in day_entries if e.status == "approved"]
        if live:
            mins = sum(int(e.minutes or 0) for e in live)
            h = overtime_hours(mins)
            pay = overtime_pay_for(h, hourly)
            ot_hours_total += h
            ot_pay_total += pay
            days.append({"date": d.isoformat(), "kind": "overtime", "status": "approved",
                         "minutes": mins, "hours": h, "amount": pay,
                         "reason": "; ".join(e.reason for e in live if e.reason) or None,
                         "entry_ids": [str(e.id) for e in live if getattr(e, "id", None)]})
        for e in day_entries:
            if e.status == "revoked":
                days.append({"date": d.isoformat(), "kind": "overtime", "status": "revoked",
                             "minutes": int(e.minutes or 0), "amount": None,
                             "reason": e.revoke_reason or e.reason})
        if line:
            days.append({"date": d.isoformat(), **line})
        d += timedelta(days=1)

    late_deduction = round(late_total * per_minute, 2)
    absent_deduction = round(absent_days * day_wage, 2)
    return {
        "period": period,
        "schedule": {"start": settings.WORK_START, "end": settings.WORK_END,
                     "days": sorted(work_days()),
                     "grace_minutes": int(settings.LATE_GRACE_MINUTES)},
        "working_days": wdays,
        "day_wage": round(day_wage, 2),
        "hourly_wage": round(hourly, 2),
        "minute_wage": round(per_minute, 4),
        "monthly_hours": int(settings.PAY_MONTHLY_HOURS or 173),
        "late_minutes": late_total,
        "late_deduction": late_deduction,
        "absent_days": absent_days,
        "absent_deduction": absent_deduction,
        "overtime_hours": ot_hours_total,
        "overtime_pay": round(ot_pay_total, 2),
        "overtime_pending": ot_pending,
        "days": days,
    }


async def migrate_clockout_overtime(db: AsyncSession) -> dict:
    """Once: overtime filed from clock-outs becomes the director's entries.

    Overtime used to be filed automatically when someone clocked out late and
    approved in the inbox. It is now recorded by the director by hand. An
    approval already given is kept — it becomes an entry, so it is still paid;
    a request still waiting is closed with a note saying why, because it was
    raised from a clock time and the director now enters overtime directly.
    """
    from datetime import UTC as _UTC
    from app.models.approval import ApprovalRequest
    from app.models.attendance import OvertimeEntry

    approved = (await db.scalars(select(Attendance).where(
        Attendance.overtime_status == "approved"))).all()
    made = 0
    for a in approved:
        exists = await db.scalar(select(OvertimeEntry.id).where(
            OvertimeEntry.user_id == a.user_id, OvertimeEntry.date == a.date))
        if exists:
            continue
        req = await db.scalar(select(ApprovalRequest).where(
            ApprovalRequest.target_type == "overtime", ApprovalRequest.target_id == a.id,
            ApprovalRequest.status == "approved"))
        db.add(OvertimeEntry(
            user_id=a.user_id, date=a.date,
            minutes=int(a.overtime_approved_minutes or a.overtime_minutes or 0) or 1,
            reason="Approved from a clock-out before overtime was entered by the director",
            status="approved", entered_by=req.decided_by if req else None))
        made += 1
    closed = 0
    for req in (await db.scalars(select(ApprovalRequest).where(
            ApprovalRequest.target_type == "overtime",
            ApprovalRequest.status == "pending"))).all():
        req.status = "rejected"
        req.decided_at = datetime.now(_UTC)
        req.decision_notes = ("Closed: overtime is now recorded by the director, not "
                              "filed from clock-out times. Ask the director to enter it "
                              "if it was worked.")
        a = await db.get(Attendance, req.target_id)
        if a is not None and a.overtime_status == "pending":
            a.overtime_status = None
        closed += 1
    await db.flush()
    return {"entries_from_approved": made, "requests_closed": closed}

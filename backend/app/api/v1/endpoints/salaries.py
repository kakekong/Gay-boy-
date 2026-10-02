"""Salary / payroll endpoints (Director only).

Each salary record is auto-postable to the Chart of Accounts:
  DR Beban Gaji Karyawan   (account_expense_no, default 6000-04)  = gross_salary
  CR Hutang Pph 21         (account_tax_no,     default 2102-04)  = pph21
  CR Hutang Gaji Karyawan  (account_liability_no, default 2102-02) = net_pay

Attendance feeds it (services/attendance_pay.py): minutes late and days
absent are deducted, approved overtime is paid. They are worked out when the
record is created, again whenever the base salary changes, and on demand
("Refresh from attendance") while it is still a draft.

Marking 'paid' moves the cash out of the bank into the liability:
  DR Hutang Gaji Karyawan  = net_pay
  CR Bank                  (account_bank_no, default 1101-01) = net_pay
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record as audit_record
from app.core.db import get_db
from app.core.permissions import Role, require, require_min
from app.models.account import Account
from app.models.salary import Salary
from app.models.user import User

router = APIRouter(
    # Internal-only surface. External portal accounts (customer /
    # supplier, hierarchy tier 0) must never reach the CRM, pricing,
    # calendar or notification data — they have /portal/* instead.
    dependencies=[Depends(require_min(Role.SALES))]
)
_director = require(Role.DIRECTOR)


DEFAULTS = {
    "expense":   "6000-04",
    "liability": "2102-02",
    "tax":       "2102-04",
    "bank":      "1101-01",
}


# ─── Schemas ─────────────────────────────────────────────────────────────────

class SalaryIn(BaseModel):
    user_id: UUID
    period: str = Field(pattern=r"^\d{4}-\d{2}$")  # YYYY-MM
    base_salary: float = 0
    transport: float = 0
    meal: float = 0
    bonus: float = 0
    thr: float = 0
    other_allowance: float = 0
    pph21: float = 0
    bpjs: float = 0
    other_deduction: float = 0
    account_expense_no:   str | None = None
    account_liability_no: str | None = None
    account_tax_no:       str | None = None
    account_bank_no:      str | None = None
    notes: str | None = None
    # Work the month's attendance into the record (late, absent, overtime).
    from_attendance: bool = True


class SalaryPatch(BaseModel):
    base_salary: float | None = None
    transport: float | None = None
    meal: float | None = None
    bonus: float | None = None
    thr: float | None = None
    other_allowance: float | None = None
    pph21: float | None = None
    bpjs: float | None = None
    other_deduction: float | None = None
    account_expense_no:   str | None = None
    account_liability_no: str | None = None
    account_tax_no:       str | None = None
    account_bank_no:      str | None = None
    notes: str | None = None


class SalaryOut(BaseModel):
    id: UUID
    user_id: UUID
    user_name: str | None = None
    period: str
    base_salary: float
    transport: float
    meal: float
    bonus: float
    thr: float
    other_allowance: float
    pph21: float
    bpjs: float
    other_deduction: float
    gross_salary: float
    net_pay: float
    status: str
    is_posted: bool
    posted_at: datetime | None = None
    paid_at: datetime | None = None
    account_expense_no:   str | None
    account_liability_no: str | None
    account_tax_no:       str | None
    account_bank_no:      str | None
    notes: str | None
    posted_snapshot: dict
    late_minutes: int = 0
    late_deduction: float = 0
    absent_days: float = 0
    absent_deduction: float = 0
    overtime_hours: float = 0
    overtime_pay: float = 0
    attendance_breakdown: dict = {}


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _recalc(s: Salary) -> None:
    # float() each: a record read back from the database holds Decimals, and
    # the attendance figures arrive as floats.
    f = lambda v: float(v or 0)  # noqa: E731
    s.gross_salary = round(
        f(s.base_salary) + f(s.transport) + f(s.meal) + f(s.bonus) + f(s.thr)
        + f(s.other_allowance) + f(s.overtime_pay), 2)
    deductions = (f(s.pph21) + f(s.bpjs) + f(s.other_deduction)
                  + f(s.late_deduction) + f(s.absent_deduction))
    s.net_pay = round(f(s.gross_salary) - deductions, 2)


async def _join_date(db: AsyncSession, user_id: UUID):
    """When the person started — days before it are not absences."""
    from app.models.employee import Employee
    u = await db.get(User, user_id)
    emp = await db.get(Employee, u.employee_id) if u and u.employee_id else None
    return emp.join_date if emp else None


async def _apply_attendance(db: AsyncSession, s: Salary) -> None:
    from app.services.attendance_pay import month_for
    m = await month_for(db, s.user_id, s.period, float(s.base_salary or 0),
                        join_date=await _join_date(db, s.user_id))
    s.late_minutes = m["late_minutes"]
    s.late_deduction = m["late_deduction"]
    s.absent_days = m["absent_days"]
    s.absent_deduction = m["absent_deduction"]
    s.overtime_hours = m["overtime_hours"]
    s.overtime_pay = m["overtime_pay"]
    s.attendance_breakdown = m


async def _bump(db: AsyncSession, account_no: str | None, delta: float) -> dict | None:
    if not account_no:
        return None
    acc = await db.scalar(select(Account).where(Account.account_no == account_no))
    if not acc:
        return None
    acc.balance = float(acc.balance or 0) + delta
    return {"account_no": account_no, "name": acc.name,
            "account_type": acc.account_type, "delta": delta,
            "new_balance": float(acc.balance)}


async def _journal_salary_moves(
    db: AsyncSession, s: Salary, movements: list[dict], verb: str,
) -> None:
    """Mirror salary CoA movements into the transaction journal so payroll
    shows up in period P&L (expense) and cash flow (bank)."""
    from app.services.ledger import journal_post
    for m in movements:
        await journal_post(
            db, entry_date=datetime.now(UTC).date(),
            account_no=m["account_no"], account_type=m.get("account_type", ""),
            account_name=m.get("name"), amount=float(m.get("delta") or 0),
            source_type="salary", source_id=s.id, source_ref=s.period,
            memo=f"Payroll {s.period} {verb} ({m.get('role')})",
        )


async def _user_name(db: AsyncSession, user_id: UUID) -> str | None:
    u = await db.get(User, user_id)
    return u.full_name if u else None


def _ensure_defaults(s: Salary) -> None:
    if not s.account_expense_no:   s.account_expense_no   = DEFAULTS["expense"]
    if not s.account_liability_no: s.account_liability_no = DEFAULTS["liability"]
    if not s.account_tax_no:       s.account_tax_no       = DEFAULTS["tax"]
    if not s.account_bank_no:      s.account_bank_no      = DEFAULTS["bank"]


async def _serialize(db: AsyncSession, s: Salary) -> dict:
    return SalaryOut(
        id=s.id, user_id=s.user_id, user_name=await _user_name(db, s.user_id),
        period=s.period, base_salary=float(s.base_salary), transport=float(s.transport),
        meal=float(s.meal), bonus=float(s.bonus), thr=float(s.thr),
        other_allowance=float(s.other_allowance), pph21=float(s.pph21),
        bpjs=float(s.bpjs), other_deduction=float(s.other_deduction),
        gross_salary=float(s.gross_salary), net_pay=float(s.net_pay),
        status=s.status, is_posted=s.is_posted, posted_at=s.posted_at,
        paid_at=s.paid_at,
        account_expense_no=s.account_expense_no,
        account_liability_no=s.account_liability_no,
        account_tax_no=s.account_tax_no,
        account_bank_no=s.account_bank_no,
        notes=s.notes, posted_snapshot=s.posted_snapshot or {},
        late_minutes=int(s.late_minutes or 0),
        late_deduction=float(s.late_deduction or 0),
        absent_days=float(s.absent_days or 0),
        absent_deduction=float(s.absent_deduction or 0),
        overtime_hours=float(s.overtime_hours or 0),
        overtime_pay=float(s.overtime_pay or 0),
        attendance_breakdown=s.attendance_breakdown or {},
    ).model_dump(mode="json")


# ─── CRUD ────────────────────────────────────────────────────────────────────

@router.get("")
async def list_salaries(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(_director),
    period: str | None = None,
    user_id: UUID | None = None,
):
    stmt = select(Salary).order_by(Salary.period.desc(), Salary.created_at.desc())
    if period:  stmt = stmt.where(Salary.period == period)
    if user_id: stmt = stmt.where(Salary.user_id == user_id)
    rows = (await db.scalars(stmt)).all()
    return [await _serialize(db, s) for s in rows]


@router.get("/attendance-preview")
async def attendance_preview(user_id: UUID, period: str, base_salary: float = 0,
                             db: AsyncSession = Depends(get_db),
                             _: User = Depends(_director)):
    """What this month's attendance does to pay, before a record exists."""
    from app.services.attendance_pay import month_for
    try:
        return await month_for(db, user_id, period, base_salary,
                               join_date=await _join_date(db, user_id))
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "period must be YYYY-MM")


EXAMPLE_BASE = 8_650_000       # → Rp 50.000 an hour at 173 hours
EXAMPLE_ALLOWANCES = {"transport": 500_000, "meal": 400_000}


@router.get("/examples")
async def worked_examples(_: User = Depends(_director)):
    """Three worked months — late, absent, late clock-out — for the payroll page.

    Built in memory on last month's calendar and run through the same code
    that works out real salaries (`attendance_pay.compute_month`), so the
    examples change when the settings do and never disagree with a payslip.
    Nothing is written.
    """
    from datetime import datetime as _dt, timedelta as _td
    from app.models.attendance import Attendance
    from app.core.config import settings
    from app.services import attendance_pay as ap

    today = ap.local_today()
    first_this = today.replace(day=1)
    last_prev = first_this - _td(days=1)
    period = last_prev.strftime("%Y-%m")
    start, end = ap.month_bounds(period)
    wdays = [start + _td(days=i) for i in range((end - start).days + 1)
             if ap.is_work_day(start + _td(days=i))]
    tz = ap.tz()
    ws, we = ap.work_start(), ap.work_end()

    def at(d, hh, mm):
        return _dt(d.year, d.month, d.day, hh, mm, tzinfo=tz)

    def shift(t, minutes):
        base = _dt(2000, 1, 1, t.hour, t.minute) + _td(minutes=minutes)
        return base.hour, base.minute

    def day(d, *, in_late=0, out_over=0, status="present", clocked=True):
        a = Attendance(date=d, status=status)
        if clocked:
            a.clock_in = at(d, *shift(ws, in_late))
            a.clock_out = at(d, *shift(we, out_over))
        a.overtime_minutes = ap.overtime_minutes_at(a) if clocked else 0
        return a

    grace = int(settings.LATE_GRACE_MINUTES)
    pick = lambda i: wdays[min(i, len(wdays) - 1)]  # noqa: E731

    late_in = {pick(2): grace - 5, pick(5): grace + 5, pick(9): 45}
    late_rows = [day(d, in_late=late_in.get(d, 0)) for d in wdays]

    absent_rows = []
    for d in wdays:
        if d in (pick(3), pick(11)):
            continue                                   # no clock-in at all
        if d == pick(6):
            absent_rows.append(day(d, status="half_day"))
        elif d == pick(15):
            absent_rows.append(day(d, status="sick", clocked=False))
        else:
            absent_rows.append(day(d))

    # Overtime is what the director recorded, not what the clock says: the
    # 19:30 clock-out with no entry (a forgotten clock-out) pays nothing.
    from app.models.attendance import OvertimeEntry
    outs = {pick(1): 105, pick(4): 120, pick(8): 70, pick(12): 150}
    ot_rows = [day(d, out_over=outs.get(d, 0)) for d in wdays]
    ot_entries = [
        OvertimeEntry(date=pick(1), minutes=105, status="approved",
                      reason="Stock-take after hours"),
        OvertimeEntry(date=pick(4), minutes=120, status="revoked",
                      reason="Entered for the wrong person",
                      revoke_reason="Entered for the wrong person — revoked"),
        OvertimeEntry(date=pick(8), minutes=70, status="approved",
                      reason="Packing a rush order"),
    ]

    def slip(key, title, story, story_id, rows, entries=()):
        m = ap.compute_month(rows, period, EXAMPLE_BASE, today=first_this,
                             overtime=entries)
        allow = sum(EXAMPLE_ALLOWANCES.values())
        gross = EXAMPLE_BASE + allow + m["overtime_pay"]
        net = gross - m["late_deduction"] - m["absent_deduction"]
        return {"key": key, "title": title, "story": story, "story_id": story_id,
                "base_salary": EXAMPLE_BASE, **EXAMPLE_ALLOWANCES,
                "overtime_pay": m["overtime_pay"], "late_deduction": m["late_deduction"],
                "absent_deduction": m["absent_deduction"],
                "gross_salary": round(gross, 2), "net_pay": round(net, 2),
                "breakdown": m}

    return {"period": period, "examples": [
        slip("late", "Late",
             f"On time every day but three: {grace - 5} min late (inside the "
             f"{grace}-minute grace), {grace + 5} min and 45 min late.",
             f"Tepat waktu setiap hari kecuali tiga: terlambat {grace - 5} mnt "
             f"(masih dalam toleransi {grace} mnt), {grace + 5} mnt, dan 45 mnt.", late_rows),
        slip("absent", "Absent",
             "On time every day but four: two days with no clock-in, one half "
             "day, and one sick day HR marked (excused).",
             "Tepat waktu setiap hari kecuali empat: dua hari tanpa absen masuk, "
             "satu setengah hari, dan satu hari sakit yang dicatat HR (dimaafkan).", absent_rows),
        slip("overtime", "Overtime",
             "The director recorded three overtime entries: 105 min and 70 min "
             "(paid), and 120 min entered for the wrong person (revoked — not "
             "paid). A day with a 19:30 clock-out but no entry pays nothing: "
             "overtime is what the director records, not what the clock says.",
             "Direktur mencatat tiga lembur: 105 mnt dan 70 mnt (dibayar), dan "
             "120 mnt yang salah orang (dibatalkan — tidak dibayar). Hari dengan "
             "absen pulang 19:30 tanpa catatan tidak dibayar: lembur adalah yang "
             "dicatat direktur, bukan jam absen.", ot_rows, ot_entries),
    ]}


@router.get("/{salary_id}")
async def get_salary(salary_id: UUID,
                     db: AsyncSession = Depends(get_db),
                     _: User = Depends(_director)):
    s = await db.get(Salary, salary_id)
    if not s:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return await _serialize(db, s)


@router.post("", status_code=201)
async def create_salary(payload: SalaryIn,
                        db: AsyncSession = Depends(get_db),
                        _: User = Depends(_director)):
    user = await db.get(User, payload.user_id)
    if not user:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Employee not found")

    dup = await db.scalar(
        select(Salary).where(Salary.user_id == payload.user_id,
                             Salary.period == payload.period)
    )
    if dup:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "A salary record already exists for this employee + period.")

    data = payload.model_dump()
    from_attendance = data.pop("from_attendance", True)
    s = Salary(**data, status="draft")
    if from_attendance:
        await _apply_attendance(db, s)
    _recalc(s)
    db.add(s)
    await db.flush()
    return await _serialize(db, s)


@router.patch("/{salary_id}")
async def update_salary(salary_id: UUID,
                        payload: SalaryPatch,
                        db: AsyncSession = Depends(get_db),
                        _: User = Depends(_director)):
    s = await db.get(Salary, salary_id)
    if not s:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if s.is_posted:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Reverse the posting before editing this salary.")
    changes = payload.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(s, k, v)
    # Late and absent are worked from the base salary, so a new base moves
    # them — unless this record was made without attendance.
    if "base_salary" in changes and s.attendance_breakdown:
        await _apply_attendance(db, s)
    _recalc(s)
    return await _serialize(db, s)


@router.post("/{salary_id}/refresh-attendance")
async def refresh_attendance(salary_id: UUID,
                             db: AsyncSession = Depends(get_db),
                             _: User = Depends(_director)):
    """Re-read the month's attendance — after HR marks a leave day, or a
    manager approves overtime filed since the record was made."""
    s = await db.get(Salary, salary_id)
    if not s:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if s.is_posted:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Reverse the posting before refreshing this salary.")
    await _apply_attendance(db, s)
    _recalc(s)
    await db.flush()
    return await _serialize(db, s)


@router.delete("/{salary_id}", status_code=204)
async def delete_salary(salary_id: UUID,
                        db: AsyncSession = Depends(get_db),
                        _: User = Depends(_director)):
    s = await db.get(Salary, salary_id)
    if not s:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if s.is_posted or s.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Only draft, unposted salaries can be deleted.")
    await db.delete(s)
    return None


# ─── Ledger actions ──────────────────────────────────────────────────────────

@router.post("/{salary_id}/post-ledger")
async def post_to_ledger(salary_id: UUID,
                         db: AsyncSession = Depends(get_db),
                         _: User = Depends(_director)):
    s = await db.get(Salary, salary_id)
    if not s:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if s.is_posted:
        raise HTTPException(status.HTTP_409_CONFLICT, "Already posted.")
    _ensure_defaults(s)
    _recalc(s)
    movements = []
    m1 = await _bump(db, s.account_expense_no,   float(s.gross_salary));  m1 and movements.append({**m1, "role": "expense"})
    m2 = await _bump(db, s.account_tax_no,       float(s.pph21));         m2 and movements.append({**m2, "role": "tax"})
    m3 = await _bump(db, s.account_liability_no, float(s.net_pay));       m3 and movements.append({**m3, "role": "liability"})
    await _journal_salary_moves(db, s, movements, "posted")
    s.is_posted = True
    s.status = "posted"
    s.posted_at = datetime.now(UTC)
    s.posted_snapshot = {"movements": movements, "posted_at": s.posted_at.isoformat()}
    await audit_record(db, actor=_, action="post_ledger", entity="salary",
                       entity_id=s.id, after={"gross": float(s.gross_salary),
                                              "net": float(s.net_pay),
                                              "pph21": float(s.pph21)})
    await db.flush()
    return await _serialize(db, s)


@router.post("/{salary_id}/reverse-ledger")
async def reverse_ledger(salary_id: UUID,
                         db: AsyncSession = Depends(get_db),
                         _: User = Depends(_director)):
    s = await db.get(Salary, salary_id)
    if not s:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if not s.is_posted:
        raise HTTPException(status.HTTP_409_CONFLICT, "Not posted.")
    if s.status == "paid":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Cannot reverse a salary that has already been paid.")
    reversed_moves = []
    for m in (s.posted_snapshot or {}).get("movements", []):
        rev = await _bump(db, m.get("account_no"), -float(m.get("delta") or 0))
        if rev:
            reversed_moves.append({**rev, "role": m.get("role")})
    await _journal_salary_moves(db, s, reversed_moves, "reversed")
    s.is_posted = False
    s.status = "draft"
    s.posted_at = None
    s.posted_snapshot = {"reversed_at": datetime.now(UTC).isoformat(),
                         "previous": s.posted_snapshot}
    await db.flush()
    return await _serialize(db, s)


@router.post("/{salary_id}/mark-paid")
async def mark_paid(salary_id: UUID,
                    db: AsyncSession = Depends(get_db),
                    _: User = Depends(_director)):
    s = await db.get(Salary, salary_id)
    if not s:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if not s.is_posted:
        raise HTTPException(status.HTTP_409_CONFLICT, "Post to ledger first.")
    if s.status == "paid":
        raise HTTPException(status.HTTP_409_CONFLICT, "Already paid.")
    _ensure_defaults(s)
    # DR liability (clear) ; CR bank (cash out)
    movements = list((s.posted_snapshot or {}).get("movements", []))
    m_liab = await _bump(db, s.account_liability_no, -float(s.net_pay))
    m_bank = await _bump(db, s.account_bank_no,      -float(s.net_pay))
    pay_moves = []
    if m_liab:
        movements.append({**m_liab, "role": "liability_clear"})
        pay_moves.append({**m_liab, "role": "liability_clear"})
    if m_bank:
        movements.append({**m_bank, "role": "bank_paid"})
        pay_moves.append({**m_bank, "role": "bank_paid"})
    await _journal_salary_moves(db, s, pay_moves, "paid")
    s.status = "paid"
    s.paid_at = datetime.now(UTC)
    s.posted_snapshot = {
        **(s.posted_snapshot or {}),
        "movements": movements,
        "paid_at": s.paid_at.isoformat(),
    }
    return await _serialize(db, s)

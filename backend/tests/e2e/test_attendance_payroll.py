"""Payroll from attendance — three people, one month, three ways to be off.

Schedule: 08:30–17:00, Monday–Friday, 15 minutes' grace. Each person is on a
base salary of Rp 8.650.000, which makes the hourly wage Rp 50.000
(÷ 173) and the per-minute wage Rp 833,33. August 2026 has 21 working days,
so a day's wage is Rp 411.904,76.

* LATE — on time every day but three: 08:40 (inside the grace: free), 08:50
  (20 min) and 09:15 (45 min). 65 minutes × Rp 833,33 = Rp 54.166,67.
* ABSENT — on time every day but four: two with no clock-in at all, one half
  day, and one sick day HR marked (excused). 2.5 days × Rp 411.904,76 =
  Rp 1.029.761,90.
* LATE CLOCK-OUT — on time in, but out late four times: 18:45 (105 min,
  approved → 2 hours: 1.5 + 2 = 3.5 × Rp 50.000 = Rp 175.000), 19:00
  (120 min, turned down → nothing), 18:10 (70 min, still waiting → nothing
  yet) and 17:20 (20 min — too short to file).

Overtime is filed by the same code a clock-out runs, and decided through the
approvals inbox like any other request.
"""
import asyncio, os, sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123",
    STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import httpx, logging; logging.disable(logging.INFO)
PASS, FAIL = [], []
def check(n, c, d=""):
    (PASS if c else FAIL).append(n); print(("  PASS " if c else "  FAIL ")+n+(f"  [{d}]" if d and not c else ""))
def J(r):
    try: return r.json()
    except Exception: return {"_": r.text[:200]}
def rp(n):
    return "Rp " + f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

JKT = ZoneInfo("Asia/Jakarta")
PERIOD = "2026-08"
BASE = 8_650_000
WORKDAYS = [date(2026, 8, d) for d in range(1, 32) if date(2026, 8, d).weekday() < 5]


def at(d: date, hhmm: str) -> datetime:
    h, m = hhmm.split(":")
    return datetime(d.year, d.month, d.day, int(h), int(m), tzinfo=JKT)


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    from app.core.db import SessionLocal
    from app.models.approval import ApprovalRequest
    from app.models.attendance import Attendance
    from app.models.salary import Salary
    from app.models.user import User
    from app.api.v1.endpoints.attendance import _file_overtime
    from sqlalchemy import delete, select
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=120)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    mgr = await login("manager@demo.local")

    people = {"late": "sales1@demo.local", "absent": "sales2@demo.local",
              "overtime": "hr@demo.local"}
    ids = {}
    async with SessionLocal() as db:
        for k, email in people.items():
            u = await db.scalar(select(User).where(User.email == email))
            ids[k] = u.id
        # A clean month for the three of them, so this can run again.
        for uid in ids.values():
            att = (await db.scalars(select(Attendance.id).where(
                Attendance.user_id == uid, Attendance.date >= date(2026, 8, 1),
                Attendance.date <= date(2026, 8, 31)))).all()
            if att:
                await db.execute(delete(ApprovalRequest).where(ApprovalRequest.target_id.in_(att)))
            await db.execute(delete(Attendance).where(Attendance.id.in_(att)))
            await db.execute(delete(Salary).where(Salary.user_id == uid, Salary.period == PERIOD))
        await db.commit()

        def day(uid, dd, cin="08:30", cout="17:00", status="present"):
            a = Attendance(user_id=uid, date=dd, status=status,
                           clock_in=at(dd, cin) if cin else None,
                           clock_out=at(dd, cout) if cout else None)
            if cin and cout:
                a.hours = round((at(dd, cout) - at(dd, cin)).total_seconds() / 3600, 2)
            db.add(a)
            return a

        # LATE
        late_days = {WORKDAYS[2]: "08:40", WORKDAYS[5]: "08:50", WORKDAYS[9]: "09:15"}
        for dd in WORKDAYS:
            day(ids["late"], dd, cin=late_days.get(dd, "08:30"))
        # ABSENT
        no_show = {WORKDAYS[3], WORKDAYS[11]}
        for dd in WORKDAYS:
            if dd in no_show:
                continue
            if dd == WORKDAYS[6]:
                day(ids["absent"], dd, cin="08:30", cout="12:30", status="half_day")
            elif dd == WORKDAYS[15]:
                day(ids["absent"], dd, cin=None, cout=None, status="sick")
            else:
                day(ids["absent"], dd)
        # LATE CLOCK-OUT
        outs = {WORKDAYS[1]: "18:45", WORKDAYS[4]: "19:00",
                WORKDAYS[8]: "18:10", WORKDAYS[12]: "17:20"}
        ot_rows = {}
        hr_user = await db.get(User, ids["overtime"])
        for dd in WORKDAYS:
            a = day(ids["overtime"], dd, cout=outs.get(dd, "17:00"))
            if dd in outs:
                ot_rows[dd] = a
        await db.flush()
        for dd, a in ot_rows.items():
            await _file_overtime(db, a, hr_user)        # what clock-out runs
        await db.commit()
        ot_ids = {dd: a.id for dd, a in ot_rows.items()}

    print("\n── overtime goes to the approvals inbox ──")
    async with SessionLocal() as db:
        reqs = {r.target_id: r for r in (await db.scalars(select(ApprovalRequest).where(
            ApprovalRequest.target_type == "overtime",
            ApprovalRequest.target_id.in_(list(ot_ids.values()))))).all()}
    check("three late clock-outs are filed (the 20-minute one is too short)",
          len(reqs) == 3 and ot_ids[WORKDAYS[12]] not in reqs, str(len(reqs)))
    inbox = J(await c.get("/approvals", headers=mgr))
    mine = [r for r in inbox if r.get("target_type") == "overtime"
            and r.get("target_id") in {str(i) for i in ot_ids.values()}]
    check("...and they are in the manager's inbox", len(mine) == 3, str(len(mine)))
    dinbox = J(await c.get("/approvals", headers=d))
    check("...and the director's", len([r for r in dinbox if r.get("target_type") == "overtime"
          and r.get("target_id") in {str(i) for i in ot_ids.values()}]) == 3)
    r = await c.post(f"/approvals/{reqs[ot_ids[WORKDAYS[1]]].id}/approve", headers=mgr, json={})
    check("the manager approves the 18:45 evening", r.status_code == 200, f"{r.status_code} {J(r)}")
    r = await c.post(f"/approvals/{reqs[ot_ids[WORKDAYS[4]]].id}/reject", headers=mgr,
                     json={"notes": "not agreed in advance"})
    check("...and turns down the 19:00 one", r.status_code == 200, f"{r.status_code} {J(r)}")

    print("\n── the payslips ──")
    slips = {}
    for k, uid in ids.items():
        r = await c.post("/salaries", headers=d, json={
            "user_id": str(uid), "period": PERIOD, "base_salary": BASE,
            "transport": 500_000, "meal": 400_000})
        check(f"{k}: the salary record is made from attendance", r.status_code == 201,
              f"{r.status_code} {str(J(r))[:200]}")
        slips[k] = J(r)

    per_min = BASE / 173 / 60
    day_wage = BASE / 21
    s = slips["late"]
    check("LATE: 21 working days in August", s["attendance_breakdown"]["working_days"] == 21)
    check("LATE: 65 minutes count (the 10-minute day is inside the grace)",
          s["late_minutes"] == 65, str(s["late_minutes"]))
    check("LATE: deducted at the per-minute wage", abs(s["late_deduction"] - round(65 * per_min, 2)) < 0.01,
          str(s["late_deduction"]))
    s = slips["absent"]
    check("ABSENT: two no-shows and a half day = 2.5 days (sick is excused)",
          s["absent_days"] == 2.5, str(s["absent_days"]))
    check("ABSENT: a day's wage each", abs(s["absent_deduction"] - round(2.5 * day_wage, 2)) < 0.01,
          str(s["absent_deduction"]))
    s = slips["overtime"]
    check("LATE OUT: only the approved evening is paid — 2 hours",
          s["overtime_hours"] == 2, str(s["overtime_hours"]))
    check("LATE OUT: first hour 1.5×, second 2× the Rp 50.000 hourly wage",
          abs(s["overtime_pay"] - 175_000) < 0.01, str(s["overtime_pay"]))
    check("LATE OUT: the waiting one is shown as waiting",
          s["attendance_breakdown"]["overtime_pending"] == 1)
    for k in ("late", "absent"):
        check(f"{k}: no overtime", slips[k]["overtime_pay"] == 0)
    for k, sl in slips.items():
        want_gross = BASE + 900_000 + sl["overtime_pay"]
        want_net = want_gross - sl["late_deduction"] - sl["absent_deduction"]
        check(f"{k}: gross and net include it", abs(sl["gross_salary"] - want_gross) < 0.01
              and abs(sl["net_pay"] - want_net) < 0.01,
              f'{sl["gross_salary"]} {sl["net_pay"]}')

    print("\n── approving the waiting evening, then refreshing ──")
    r = await c.post(f"/approvals/{reqs[ot_ids[WORKDAYS[8]]].id}/approve", headers=d, json={})
    check("the director approves the 18:10 evening", r.status_code == 200)
    r = J(await c.post(f'/salaries/{slips["overtime"]["id"]}/refresh-attendance', headers=d))
    check("refreshing adds it: 70 min → 1 hour at 1.5× = Rp 75.000 more",
          abs(r["overtime_pay"] - 250_000) < 0.01 and r["overtime_hours"] == 3, str(r.get("overtime_pay")))
    slips["overtime"] = r

    print("\n" + "═" * 64)
    for k, title in (("late", "LATE"), ("absent", "ABSENT"), ("overtime", "LATE CLOCK-OUT")):
        sl = slips[k]
        print(f"\n{title} — {sl['user_name']}, {PERIOD}")
        print(f"  Base salary            {rp(sl['base_salary']):>20}")
        print(f"  Transport + meal       {rp(sl['transport'] + sl['meal']):>20}")
        if sl["overtime_pay"]:
            print(f"  Overtime ({sl['overtime_hours']:g} h)         {rp(sl['overtime_pay']):>20}")
        print(f"  Gross                  {rp(sl['gross_salary']):>20}")
        if sl["late_deduction"]:
            print(f"  Late ({sl['late_minutes']} min)          -{rp(sl['late_deduction']):>19}")
        if sl["absent_deduction"]:
            print(f"  Absent ({sl['absent_days']:g} days)       -{rp(sl['absent_deduction']):>19}")
        print(f"  Net pay                {rp(sl['net_pay']):>20}")
        for ln in sl["attendance_breakdown"]["days"]:
            extra = (f"in {ln['clock_in']}, {ln['minutes']} min" if ln["kind"] == "late"
                     else f"out {ln.get('clock_out')}, {ln['minutes']} min, {ln['status']}"
                     if ln["kind"] == "overtime" else f"{ln['days']} day")
            amt = ln.get("amount")
            print(f"     {ln['date']}  {ln['kind']:<9} {extra:<34} {rp(amt) if amt is not None else ''}")

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

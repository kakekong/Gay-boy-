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
* OVERTIME — recorded by the director, by hand, not read off clock-outs.
  Four late clock-outs (18:45, 19:00, 18:10, and a forgotten 19:30); the
  director records 105 min for the first (→ 2 hours: 1.5 + 2 = 3.5 ×
  Rp 50.000 = Rp 175.000), records 120 min for the second for the wrong
  person and revokes it (kept, not paid), adds a test entry and deletes it,
  and later records 70 min for the third (+ Rp 75.000 after a refresh). The
  forgotten clock-out pays nothing — nobody recorded overtime for it.
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
    from app.models.attendance import OvertimeEntry
    from app.services.attendance_pay import overtime_minutes_at
    from sqlalchemy import delete, func, select
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
            await db.execute(delete(OvertimeEntry).where(
                OvertimeEntry.user_id == uid, OvertimeEntry.date >= date(2026, 8, 1),
                OvertimeEntry.date <= date(2026, 8, 31)))
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
        # OVERTIME — late clock-outs, which on their own pay nothing
        outs = {WORKDAYS[1]: "18:45", WORKDAYS[4]: "19:00",
                WORKDAYS[8]: "18:10", WORKDAYS[12]: "19:30"}
        for dd in WORKDAYS:
            a = day(ids["overtime"], dd, cout=outs.get(dd, "17:00"))
            a.overtime_minutes = overtime_minutes_at(a)      # what clock-out stores
        await db.commit()

    print("\n── overtime is recorded by the director ──")
    async with SessionLocal() as db:
        n = await db.scalar(select(func.count(ApprovalRequest.id)).where(
            ApprovalRequest.target_type == "overtime", ApprovalRequest.status == "pending",
            ApprovalRequest.requested_by == ids["overtime"]))
    check("a late clock-out files nothing — no overtime request appears", n == 0, str(n))
    hr = await login("hr@demo.local")
    ot_user = str(ids["overtime"])
    body = {"user_id": ot_user, "date": WORKDAYS[1].isoformat(), "minutes": 105,
            "reason": "Stock-take after hours"}
    for who, hdr in (("a manager", mgr), ("HR", hr)):
        r = await c.post("/attendance/overtime", headers=hdr, json=body)
        check(f"{who} cannot record overtime — only the director", r.status_code == 403,
              str(r.status_code))
    r = await c.post("/attendance/overtime", headers=d, json={**body, "date": "2099-01-01"})
    check("overtime is not recorded for a day that hasn't happened", r.status_code == 400)
    r = await c.post("/attendance/overtime", headers=d, json=body)
    e1 = J(r)
    check("the director records 105 min for the 18:45 evening",
          r.status_code == 201 and e1.get("status") == "approved", f"{r.status_code} {str(e1)[:160]}")
    check("...shown beside what the clock said that day",
          e1.get("clock_out_over_minutes") == 105, str(e1.get("clock_out_over_minutes")))
    r = await c.post("/attendance/overtime", headers=d, json={
        "user_id": ot_user, "date": WORKDAYS[4].isoformat(), "minutes": 120,
        "reason": "Loading the truck"})
    e2 = J(r)
    r = await c.post(f"/attendance/overtime/{e2['id']}/revoke", headers=d, json={"reason": ""})
    check("revoking needs a reason", r.status_code == 400, str(r.status_code))
    r = await c.post(f"/attendance/overtime/{e2['id']}/revoke", headers=mgr,
                     json={"reason": "wrong person"})
    check("only the director can revoke", r.status_code == 403, str(r.status_code))
    r = await c.post(f"/attendance/overtime/{e2['id']}/revoke", headers=d,
                     json={"reason": "Entered for the wrong person"})
    check("the director revokes the mistaken 120 min — kept on record",
          r.status_code == 200 and J(r).get("status") == "revoked"
          and J(r).get("revoke_reason") == "Entered for the wrong person", str(J(r))[:160])
    r = await c.post("/attendance/overtime", headers=d, json={
        "user_id": ot_user, "date": WORKDAYS[2].isoformat(), "minutes": 600, "reason": "test"})
    e3 = J(r)
    r = await c.delete(f"/attendance/overtime/{e3['id']}", headers=d)
    check("a test entry is deleted outright", r.status_code == 204, str(r.status_code))
    mine = J(await c.get("/attendance/overtime", headers=hr, params={"period": PERIOD,
                                                                    "user_id": ot_user}))
    check("the employee's overtime lists the live and the revoked entry, not the deleted one",
          sorted(x["status"] for x in mine) == ["approved", "revoked"], str([x["status"] for x in mine]))

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
    check("OVERTIME: only the director's live entry is paid — 105 min → 2 hours",
          s["overtime_hours"] == 2, str(s["overtime_hours"]))
    check("OVERTIME: first hour 1.5×, second 2× the Rp 50.000 hourly wage",
          abs(s["overtime_pay"] - 175_000) < 0.01, str(s["overtime_pay"]))
    kinds = [(ln["date"], ln.get("status")) for ln in s["attendance_breakdown"]["days"]
             if ln["kind"] == "overtime"]
    check("OVERTIME: the revoked entry is listed, unpaid; the forgotten clock-out isn't overtime",
          (WORKDAYS[4].isoformat(), "revoked") in kinds
          and not any(dd == WORKDAYS[12].isoformat() for dd, _ in kinds), str(kinds))
    for k in ("late", "absent"):
        check(f"{k}: no overtime", slips[k]["overtime_pay"] == 0)
    for k, sl in slips.items():
        want_gross = BASE + 900_000 + sl["overtime_pay"]
        want_net = want_gross - sl["late_deduction"] - sl["absent_deduction"]
        check(f"{k}: gross and net include it", abs(sl["gross_salary"] - want_gross) < 0.01
              and abs(sl["net_pay"] - want_net) < 0.01,
              f'{sl["gross_salary"]} {sl["net_pay"]}')

    print("\n── overtime recorded after the payslip, then a refresh ──")
    r = await c.post("/attendance/overtime", headers=d, json={
        "user_id": ot_user, "date": WORKDAYS[8].isoformat(), "minutes": 70,
        "reason": "Packing a rush order"})
    check("the director records 70 min for the 18:10 evening", r.status_code == 201)
    r = J(await c.post(f'/salaries/{slips["overtime"]["id"]}/refresh-attendance', headers=d))
    check("refreshing adds it: 70 min → 1 hour at 1.5× = Rp 75.000 more",
          abs(r["overtime_pay"] - 250_000) < 0.01 and r["overtime_hours"] == 3, str(r.get("overtime_pay")))
    slips["overtime"] = r

    print("\n── the worked examples on the payroll page ──")
    s1 = await login("sales1@demo.local")
    r = await c.get("/salaries/examples", headers=s1)
    check("only the director sees them", r.status_code == 403, str(r.status_code))
    ex = J(await c.get("/salaries/examples", headers=d))
    byk = {e["key"]: e for e in ex.get("examples", [])}
    check("three examples: late, absent, overtime", set(byk) == {"late", "absent", "overtime"})
    b = byk["late"]["breakdown"]
    check("the late example counts 65 minutes at the per-minute wage",
          b["late_minutes"] == 65 and abs(byk["late"]["late_deduction"] - round(65 * per_min, 2)) < 0.01,
          str(b["late_minutes"]))
    b = byk["absent"]["breakdown"]
    check("the absent example is 2.5 days at that month's day wage",
          b["absent_days"] == 2.5 and abs(byk["absent"]["absent_deduction"]
                                          - round(2.5 * BASE / b["working_days"], 2)) < 0.01,
          str(b["absent_days"]))
    b = byk["overtime"]["breakdown"]
    check("the overtime example pays the director's two live entries, not the revoked one",
          byk["overtime"]["overtime_pay"] == 250_000
          and any(ln.get("status") == "revoked" for ln in b["days"]), str(byk["overtime"]["overtime_pay"]))
    check("each example carries the rates it was worked at",
          all({"day_wage", "hourly_wage", "minute_wage"} <= set(e["breakdown"]) for e in byk.values()))

    print("\n── clock-out overtime from before becomes the director's ──")
    from app.services.attendance_pay import migrate_clockout_overtime
    from app.models.approval import ApprovalRequest as AR
    async with SessionLocal() as db:
        late_uid = ids["late"]        # their month has no overtime of its own
        a_ok = (await db.scalars(select(Attendance).where(
            Attendance.user_id == late_uid, Attendance.date == WORKDAYS[16]))).first()
        a_wait = (await db.scalars(select(Attendance).where(
            Attendance.user_id == late_uid, Attendance.date == WORKDAYS[17]))).first()
        a_ok.overtime_minutes, a_ok.overtime_status, a_ok.overtime_approved_minutes = 90, "approved", 90
        a_wait.overtime_minutes, a_wait.overtime_status = 60, "pending"
        db.add(AR(target_type="overtime", target_id=a_wait.id, requested_by=late_uid,
                  required_role="manager", status="pending", payload={}))
        await db.flush()
        res = await migrate_clockout_overtime(db)
        await db.commit()
        made = (await db.scalars(select(OvertimeEntry).where(
            OvertimeEntry.user_id == late_uid, OvertimeEntry.date == WORKDAYS[16]))).all()
        waiting = await db.scalar(select(func.count(AR.id)).where(
            AR.target_id == a_wait.id, AR.status == "pending"))
    check("an approval already given becomes a paid entry",
          len(made) == 1 and made[0].minutes == 90 and made[0].status == "approved", str(res))
    check("a request still waiting is closed, with a note", waiting == 0, str(waiting))
    async with SessionLocal() as db:        # and leave the late month as it was
        await db.execute(delete(OvertimeEntry).where(OvertimeEntry.user_id == ids["late"]))
        await db.commit()

    print("\n" + "═" * 64)
    for k, title in (("late", "LATE"), ("absent", "ABSENT"), ("overtime", "OVERTIME")):
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
            extra = (f"in {ln['clock_in']}, {ln['minutes']} min" if ln["kind"] in ("late", "grace")
                     else f"{ln['minutes']} min, {ln['status']} — {ln.get('reason') or ''}"
                     if ln["kind"] == "overtime" else f"{ln['status']} (excused)"
                     if ln["kind"] == "excused" else f"{ln['days']} day")
            amt = ln.get("amount")
            print(f"     {ln['date']}  {ln['kind']:<9} {extra:<34} {rp(amt) if amt is not None else ''}")

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

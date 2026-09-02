"""One person's attendance, day by day, behind their name.

Asked for, on the attendance summary: *"make it so i can click on the name and
after clicking the name let me view their full attendance record."*

The summary answers "how many days" and stops. The question it provokes is
always the next one — which days, and what happened on them: the fortnight
somebody clocked 82 hours next to a colleague's 118, the month with a zero in
it, the day that reads half. The only way to find out was to scroll the
all-employees table underneath and pick their rows out by eye.

The record itself was already reachable — `GET /attendance?user_id=&period=`
— so this pins the parts that matter for putting a person's history behind
their name:

**It is one person's, and it is complete.** Asking for a user returns that
user only, every recorded day, with the times and the note attached to each.

**A month, or all of it.** The panel opens on the month the summary was
showing and can walk back; leaving the period off returns everything on
record, which is what "full attendance record" means when somebody wants to
see a pattern rather than a page.

**And it stays HR's and the director's.** The summary is theirs; the day-level
record behind it is the same information at higher resolution, including the
notes people write when they clock in late, and it must not become readable
by everyone just because it moved behind a click.
"""
import asyncio, os, sys, uuid
from datetime import date, timedelta
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


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)
    tag = uuid.uuid4().hex[:5]

    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    hr = await login("hr@demo.local")
    s1 = await login("sales1@demo.local")
    adm = await login("admin@demo.local")
    fin = await login("finance@demo.local")

    # Two people, so "their record" can be shown to mean one of them.
    # A login belongs to somebody on the employee register, so each of these
    # is two steps now: the person, then their way to sign in.
    async def hire(name, email, role="sales"):
        emp = J(await c.post("/employees", headers=d, json={
            "full_name": name, "intended_role": role}))
        return J(await c.post("/users", headers=d, json={
            "email": email, "full_name": name, "role": role,
            "employee_id": emp["id"], "password": "test-pass-123"}))

    who = await hire(f"Hadir {tag}", f"hadir{tag}@demo.local")
    other = await hire(f"Lain {tag}", f"lain{tag}@demo.local")
    check("two employees exist to tell apart",
          bool(who.get("id")) and bool(other.get("id")),
          f"{who}/{other}"[:170])

    # A month of history: some present days, an absence, a half day, sick
    # leave — and one day for the other person, in the same month.
    today = date.today()
    plan = [("present", 8.0), ("present", 7.5), ("absent", 0.0),
            ("half_day", 4.0), ("sick", 0.0), ("present", 8.25)]
    # Attendance is only recorded for days that have happened, so early in a
    # month there is nowhere to put six of them — run against the month before
    # instead, which is entirely in the past.
    first = today.replace(day=1)
    if today.day < len(plan):
        first = (first - timedelta(days=1)).replace(day=1)
    period = first.strftime("%Y-%m")
    made = 0
    for i, (st, hours) in enumerate(plan):
        day = first + timedelta(days=i)
        if day > today:
            break
        r = await c.post("/attendance/manual", headers=hr, json={
            "user_id": who["id"], "date": day.isoformat(), "status": st,
            "hours": hours, "notes": f"{st} note {tag}"})
        if r.status_code in (200, 201):
            made += 1
    r = await c.post("/attendance/manual", headers=hr, json={
        "user_id": other["id"], "date": first.isoformat(), "status": "present",
        "hours": 8.0, "notes": f"other {tag}"})
    check("a month of days is recorded for one of them", made >= 3, str(made))
    check("...and one for the other", r.status_code in (200, 201),
          f"{r.status_code} {J(r)}"[:150])

    # ══ the record behind the name ═══════════════════════════════════════════
    print("\n── one person's month ──")
    r = await c.get("/attendance", headers=d,
                    params={"user_id": who["id"], "period": period})
    check("their record comes back", r.status_code == 200, str(r.status_code))
    rows = J(r)
    check("...only their days, nobody else's",
          all(x["user_id"] == who["id"] for x in rows),
          str({x["user_name"] for x in rows}))
    check("...as many as were recorded", len(rows) == made, f"{len(rows)} vs {made}")
    check("...with the status of each day",
          {x["status"] for x in rows} >= {"present", "absent"},
          str([x["status"] for x in rows]))
    day0 = next((x for x in rows if x["status"] == "present"), None)
    check("...the hours worked", day0 and float(day0["hours"]) > 0,
          str(day0)[:170])
    check("...and the note written on it",
          day0 and tag in (day0.get("notes") or ""), str(day0)[:200])
    check("...newest first, so the last few days read at the top",
          [x["date"] for x in rows] == sorted((x["date"] for x in rows), reverse=True),
          str([x["date"] for x in rows]))

    print("\n── the whole record, not one month ──")
    older = (first - timedelta(days=40))
    await c.post("/attendance/manual", headers=hr, json={
        "user_id": who["id"], "date": older.isoformat(), "status": "present",
        "hours": 8.0, "notes": f"older {tag}"})
    r = await c.get("/attendance", headers=d, params={"user_id": who["id"]})
    all_rows = J(r)
    check("leaving the month off returns everything on record",
          len(all_rows) == made + 1, f"{len(all_rows)} vs {made + 1}")
    check("...including the day from two months back",
          any(x["date"] == older.isoformat() for x in all_rows),
          str([x["date"] for x in all_rows])[:200])
    r = await c.get("/attendance", headers=d,
                    params={"user_id": who["id"], "period": period})
    check("...while the month still returns only its own days",
          len(J(r)) == made, str(len(J(r))))

    print("\n── the roll-up and the record agree ──")
    summary = J(await c.get("/attendance/summary-all", headers=d,
                            params={"period": period}))
    mine = next((x for x in summary["rows"] if x["user_id"] == who["id"]), None)
    check("the summary has a row for them", mine is not None, "missing")
    month_rows = J(await c.get("/attendance", headers=d,
                               params={"user_id": who["id"], "period": period}))
    present = sum(1 for x in month_rows if x["status"] in ("present", "wfh"))
    hours = round(sum(float(x["hours"] or 0) for x in month_rows), 2)
    check("...counting the same present days as the record does",
          mine and mine["present_like_days"] == present,
          f"summary={mine and mine['present_like_days']} record={present}")
    check("...and the same hours",
          mine and abs(float(mine["total_hours"]) - hours) < 0.01,
          f"summary={mine and mine['total_hours']} record={hours}")

    print("\n── who may open it ──")
    r = await c.get("/attendance", headers=hr, params={"user_id": who["id"]})
    check("HR can read it — the summary is theirs", r.status_code == 200,
          str(r.status_code))
    for label, hdr in (("sales", s1), ("admin", adm), ("finance", fin)):
        r = await c.get("/attendance", headers=hdr, params={"user_id": who["id"]})
        check(f"{label} cannot read somebody's day-level record",
              r.status_code in (401, 403), str(r.status_code))
    r = await c.get("/attendance/me", headers=s1)
    check("...though everyone still has their own", r.status_code == 200,
          str(r.status_code))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)


asyncio.run(main())

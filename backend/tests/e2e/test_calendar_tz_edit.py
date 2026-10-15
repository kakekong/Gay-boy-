"""The calendar puts a plan on the day it was set for, and a note can be changed.

Staff feedback: a plan made this morning for today, the 15th, showed on the
16th; plans set for a day sometimes didn't show at all; and a note couldn't be
edited, so any change meant a new reminder.

* Calendar days are office (WIB) days. A reminder at 06:00 WIB on the 15th —
  still the 14th in UTC — is in the 15th's range, and one at 23:30 WIB on the
  15th is not in the 16th's.
* A manual reminder comes with what the edit form needs.
* Whoever set it can change its note and time in place, or delete it; another
  sales rep can't; a manager can. Checklist tasks aren't edited here.
"""
import asyncio, os, sys, uuid
from datetime import datetime, timedelta, timezone
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123",
    STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import httpx, logging; logging.disable(logging.INFO)
TAG = uuid.uuid4().hex[:5].upper()
PASS, FAIL = [], []
def check(n, c, d=""):
    (PASS if c else FAIL).append(n); print(("  PASS " if c else "  FAIL ")+n+(f"  [{d}]" if d and not c else ""))
def J(r):
    try: return r.json()
    except Exception: return {"_": r.text[:200]}

WIB = timezone(timedelta(hours=7))


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    s1 = await login("sales1@demo.local")
    s2 = await login("sales2@demo.local")

    async def day(who, iso):
        return J(await c.get("/calendar/events", headers=who, params={"from": iso, "to": iso}))

    def mine(evs, rid):
        return [e for e in evs if e["id"] == f"reminder:{rid}"]

    async def new(who, at, msg):
        r = await c.post("/calendar/reminders", headers=who, json={
            "kind": "follow_up", "due_at": at.isoformat(), "message": msg})
        return J(r)["id"]

    print("\n── the day it was set for ──")
    early = await new(s1, datetime(2026, 10, 15, 6, 0, tzinfo=WIB), f"Call PT Bara early {TAG}")
    late = await new(s1, datetime(2026, 10, 15, 23, 30, tzinfo=WIB), f"Send the quote tonight {TAG}")
    morning = await new(s1, datetime(2026, 10, 15, 8, 0, tzinfo=WIB), f"Visit site {TAG}")
    d14, d15, d16 = (await day(s1, "2026-10-14"), await day(s1, "2026-10-15"),
                     await day(s1, "2026-10-16"))
    check("06:00 WIB on the 15th (the 14th in UTC) is on the 15th",
          mine(d15, early) and not mine(d14, early))
    check("23:30 WIB on the 15th (the 16th in UTC) is on the 15th",
          mine(d15, late) and not mine(d16, late))
    check("08:00 WIB on the 15th is on the 15th, not the 16th",
          mine(d15, morning) and not mine(d16, morning))
    ev = (mine(d15, morning) or [{}])[0]
    rem = ev.get("reminder") or {}
    check("a manual reminder carries what the edit form needs",
          rem.get("id") == morning and rem.get("message") == f"Visit site {TAG}"
          and rem.get("editable") is True, str(rem)[:200])
    check("...and it's editable only by whoever set it — not another rep",
          not mine(await day(s2, "2026-10-15"), morning))
    dr = mine(await day(d, "2026-10-15"), morning)
    check("...or a manager/director, who sees it as editable",
          dr and dr[0]["reminder"]["editable"] is True)

    print("\n── changing it in place ──")
    note = f"Visit site — bring the chain samples\nAsk for Pak Budi at the gate {TAG}"
    r = await c.patch(f"/calendar/reminders/{morning}", headers=s1, json={
        "message": note, "due_at": datetime(2026, 10, 16, 10, 0, tzinfo=WIB).isoformat()})
    check("the rep edits the note and moves it to the 16th", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:200])
    d15, d16 = await day(s1, "2026-10-15"), await day(s1, "2026-10-16")
    moved = mine(d16, morning)
    check("...it's now on the 16th, and gone from the 15th", moved and not mine(d15, morning))
    check("...titled by the note's first line, the full note kept",
          moved and moved[0]["title"] == "Visit site — bring the chain samples"
          and moved[0]["reminder"]["message"] == note, str(moved)[:250])
    check("...still the same reminder — no new one made",
          len([e for e in d16 if TAG in (e.get("reminder") or {}).get("message", "")]) == 1)

    r = await c.patch(f"/calendar/reminders/{morning}", headers=s2, json={"message": "mine now"})
    check("another sales rep can't change it", r.status_code == 403, str(r.status_code))
    r = await c.patch(f"/calendar/reminders/{morning}", headers=d, json={"recurs": "weekly",
                                                                    "recurs_until": "2026-12-31"})
    check("the director can", r.status_code == 200, f"{r.status_code} {J(r)}"[:200])
    rem = mine(await day(s1, "2026-10-16"), morning)[0]["reminder"]
    check("...and the note is untouched by a change that didn't send it",
          rem["message"] == note and rem["recurs"] == "weekly"
          and rem["recurs_until"] == "2026-12-31", str(rem)[:250])
    await c.patch(f"/calendar/reminders/{morning}", headers=s1, json={"recurs": "none"})
    rem = mine(await day(s1, "2026-10-16"), morning)[0]["reminder"]
    check("turning repeat off clears its end date", rem["recurs_until"] is None, str(rem))

    print("\n── deleting ──")
    r = await c.delete(f"/calendar/reminders/{early}", headers=s2)
    check("another rep can't delete it", r.status_code == 403, str(r.status_code))
    r = await c.delete(f"/calendar/reminders/{early}", headers=s1)
    check("whoever set it can", r.status_code == 200 and not mine(await day(s1, "2026-10-15"), early),
          f"{r.status_code} {J(r)}"[:200])
    r = await c.patch(f"/calendar/reminders/{early}", headers=s1, json={"message": "x"})
    check("...and it's gone", r.status_code == 404, str(r.status_code))
    await c.delete(f"/calendar/reminders/{late}", headers=s1)
    await c.delete(f"/calendar/reminders/{morning}", headers=s1)

    print("\n── checklist tasks ──")
    from app.core.db import SessionLocal
    from app.models.crm import Reminder
    from app.models.user import User
    from sqlalchemy import select
    async with SessionLocal() as s:
        dir_id = await s.scalar(select(User.id).where(User.email == "director@demo.local"))
        t = Reminder(user_id=dir_id, kind="stage:lead:first_contact", status="pending",
                     channel="dashboard", due_at=datetime(2026, 10, 15, 9, 0, tzinfo=WIB))
        s.add(t); await s.commit(); tid = t.id
    ev = mine(await day(d, "2026-10-15"), tid)
    check("a stage task shows without an edit form", ev and "reminder" not in ev[0], str(ev)[:200])
    r = await c.patch(f"/calendar/reminders/{tid}", headers=d, json={"message": "x"})
    check("...and isn't edited here", r.status_code == 400, f"{r.status_code} {J(r)}"[:200])
    async with SessionLocal() as s:
        await s.delete(await s.get(Reminder, tid)); await s.commit()

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

"""The sales rep's own to-dos on a customer's stage checklist.

The checklist held only the stage's playbook tasks. Now the rep adds their
own, and a date puts one on the calendar and in the reminders exactly like a
playbook task.

* Added with a title, a note and a date: on the checklist, marked as the
  rep's own, and on the rep's calendar under its title.
* Without a date: on the checklist only.
* Ticked off, reopened, its note or date changed like any task — the title
  stays.
* Another rep's customer is refused.
* When the deal moves on it moves with it, still open — not closed for them.
* It can be removed; the playbook's own tasks can't.
"""
import asyncio, os, sys, uuid
from datetime import date, datetime, timedelta, UTC
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

    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT TUGAS {TAG}", "industry": "mining"}))["id"]
    async def items(who=s1):
        return J(await c.get(f"/customers/{cust}/stage-tasks", headers=who)).get("items", [])

    print("\n── the rep adds their own to-do ──")
    when = (datetime.now(UTC) + timedelta(days=3)).replace(hour=3, minute=0, second=0, microsecond=0)
    r = await c.post(f"/customers/{cust}/stage-tasks", headers=s1, json={
        "title": f"Call to confirm the chain spec {TAG}", "note": "ask about pitch 50.8",
        "due_at": when.isoformat()})
    todo = J(r)
    check("added with a title, a note and a date", r.status_code == 201 and todo.get("custom") is True
          and todo.get("note") == "ask about pitch 50.8", f"{r.status_code} {todo}"[:200])
    rows = await items()
    mine = next((x for x in rows if x["key"] == todo.get("key")), None)
    check("...it is on the checklist beside the stage's tasks",
          mine is not None and any(not x.get("custom") for x in rows), str(rows)[:300])

    rng = {"from": (date.today() - timedelta(days=1)).isoformat(),
           "to": (date.today() + timedelta(days=10)).isoformat()}
    ev = J(await c.get("/calendar/events", headers=s1, params=rng))
    ev = ev if isinstance(ev, list) else ev.get("events", ev.get("items", []))
    on_cal = [e for e in ev if f"Call to confirm the chain spec {TAG}" in (e.get("title") or "")]
    check("...and on the rep's calendar, under its title (not its note)",
          len(on_cal) == 1 and "pitch" not in on_cal[0]["title"], str([e.get("title") for e in on_cal]))

    r = await c.post(f"/customers/{cust}/stage-tasks", headers=s1, json={"title": f"Send catalogue {TAG}"})
    nodate = J(r)
    ev = J(await c.get("/calendar/events", headers=s1, params=rng))
    ev = ev if isinstance(ev, list) else ev.get("events", ev.get("items", []))
    check("without a date: on the checklist only", r.status_code == 201 and nodate.get("due_at") is None
          and not any(f"Send catalogue {TAG}" in (e.get("title") or "") for e in ev))
    r = await c.post(f"/customers/{cust}/stage-tasks", headers=s1, json={"title": "   "})
    check("an empty to-do is refused", r.status_code == 400, str(r.status_code))
    r = await c.post(f"/customers/{cust}/stage-tasks", headers=s2, json={"title": "not mine"})
    check("another rep's customer is refused", r.status_code == 403, str(r.status_code))

    print("\n── like any task ──")
    k = todo["key"]
    r = await c.patch(f"/customers/{cust}/stage-tasks/{k}", headers=s1, json={"note": "pitch 50.8, double"})
    mine = next(x for x in await items() if x["key"] == k)
    check("its note changes, its title stays",
          mine["title"] == f"Call to confirm the chain spec {TAG}" and mine["note"] == "pitch 50.8, double",
          str(mine))
    await c.post(f"/customers/{cust}/stage-tasks/{k}/complete", headers=s1)
    check("...ticked off", next(x for x in await items() if x["key"] == k)["status"] == "done")
    await c.post(f"/customers/{cust}/stage-tasks/{k}/reopen", headers=s1)
    check("...and reopened", next(x for x in await items() if x["key"] == k)["status"] == "pending")

    print("\n── the deal moves on ──")
    r = await c.patch(f"/customers/{cust}", headers=d, json={"stage": "presentation"})
    check("the customer moves to the next stage", r.status_code in (200, 202), f"{r.status_code} {J(r)}"[:160])
    rows = await items()
    carried = next((x for x in rows if x["key"] == k), None)
    check("...the open to-do moves with the deal, still open, onto the new stage's checklist",
          carried is not None and carried["status"] == "pending" and carried["stage"] == "presentation",
          str(carried))
    r = await c.post(f"/customers/{cust}/stage-tasks/{k}/complete", headers=s1)
    check("...and can still be ticked off there", r.status_code == 200
          and next(x for x in await items() if x["key"] == k)["status"] == "done", str(r.status_code))

    print("\n── removing ──")
    play = next((x for x in rows if not x.get("custom")), None)
    if play:
        r = await c.delete(f"/customers/{cust}/stage-tasks/{play['key']}", headers=s1)
        check("a stage's own task can't be removed", r.status_code == 400, str(r.status_code))
    r = await c.delete(f"/customers/{cust}/stage-tasks/{nodate['key']}", headers=s1)
    check("the rep's own to-do can", r.status_code == 204
          and not any(x["key"] == nodate["key"] for x in await items()), str(r.status_code))

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

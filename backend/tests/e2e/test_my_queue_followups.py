"""My Queue: a follow-up leaves the queue once it's been done.

Staff feedback: follow-ups kept piling up in My Queue even after the contact
was made, and clicking one only opened the customer. Nothing ever closed them
— only a quotation's follow-up panel could.

* Logging a call, visit, WhatsApp or email on the customer closes their
  follow-ups due today or overdue; later ones stay, and so do reminders that
  a call doesn't answer (a payment chase). A note to self closes nothing.
* A repeating follow-up schedules its next time when closed this way.
* Any reminder can be ticked off from the queue with Done.
* The queue names a reminder without a customer by what it is, not "follow_up".
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
    s1 = await login("sales1@demo.local")

    now = datetime.now(WIB)
    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Maruwai {TAG}", "industry": "mining"}))["id"]

    async def remind(at, msg, kind="follow_up", customer=cust, recurs="none"):
        r = await c.post("/calendar/reminders", headers=s1, json={
            "customer_id": customer, "kind": kind, "due_at": at.isoformat(),
            "message": f"{msg} {TAG}", "recurs": recurs})
        return J(r)["id"]

    async def queue():
        return J(await c.get("/dashboard/my-queue", headers=s1))
    n0 = (await queue())["counts"]["reminders_due"]

    yesterday = await remind(now - timedelta(days=1), "follow up bu Susi")
    this_morning = await remind(now - timedelta(minutes=30), "hubungi pak Nanang")
    weekly = await remind(now - timedelta(days=2), "cek stok rantai", recurs="weekly")
    next_week = await remind(now + timedelta(days=7), "call again next week")
    chase = await remind(now - timedelta(days=1), "tagih DP", kind="payment_due")
    loose = await remind(now - timedelta(hours=2), "Bu Susi Maruwai Coal", customer=None)

    def ids(qd):
        return {r["id"] for r in qd["reminders_due"]}

    print("\n── before ──")
    qd = await queue()
    check("the five due ones are counted in the queue", qd["counts"]["reminders_due"] == n0 + 5,
          f'{qd["counts"]["reminders_due"]} vs {n0}+5')
    check("...the one for next week isn't", next_week not in ids(qd))
    labels = {r["label"] for r in qd["reminders_due"] if r["kind"] == "follow_up"}
    check("a follow-up is named by what it is, not 'follow_up'", labels == {"Follow up"}, str(labels))

    print("\n── a note to self ──")
    r = await c.post(f"/customers/{cust}/activities", headers=s1, json={
        "type": "note", "direction": "internal", "notes": "internal note"})
    check("a note closes nothing", r.status_code == 201 and J(r).get("closed_followups") == 0,
          f"{r.status_code} {J(r)}"[:200])

    print("\n── the call is made ──")
    r = await c.post(f"/customers/{cust}/activities", headers=s1, json={
        "type": "call", "direction": "outbound", "notes": "Sudah telepon bu Susi"})
    check("logging the call closes the three follow-ups that were due",
          r.status_code == 201 and J(r).get("closed_followups") == 3, f"{r.status_code} {J(r)}"[:200])

    from app.core.db import SessionLocal
    from app.models.crm import Reminder
    from sqlalchemy import select
    async with SessionLocal() as s:
        st = {str(x.id): x.status for x in (await s.scalars(select(Reminder).where(
            Reminder.message.like(f"%{TAG}")))).all()}
        nxt = (await s.scalars(select(Reminder).where(
            Reminder.parent_reminder_id == uuid.UUID(weekly)))).all()
    check("...overdue and this morning's are done",
          st[yesterday] == "done" and st[this_morning] == "done" and st[weekly] == "done", str(st))
    check("...next week's stays", st[next_week] == "pending")
    check("...a payment chase isn't answered by a call", st[chase] == "pending")
    check("...the weekly one is booked again a week on",
          len(nxt) == 1 and nxt[0].status == "pending"
          and abs((nxt[0].due_at - (now - timedelta(days=2) + timedelta(days=7))).total_seconds()) < 5,
          str([(x.due_at, x.status) for x in nxt]))
    qd = await queue()
    check("...and they've left the queue (two of the five remain)",
          qd["counts"]["reminders_due"] == n0 + 2
          and not ({yesterday, this_morning, weekly} & ids(qd)), str(qd["counts"]))

    print("\n── done from the queue ──")
    r = await c.patch(f"/calendar/reminders/{loose}/done", headers=s1)
    qd = await queue()
    check("Done takes a reminder off the queue",
          r.status_code == 200 and qd["counts"]["reminders_due"] == n0 + 1, f"{r.status_code} {qd['counts']}")
    await c.patch(f"/calendar/reminders/{chase}/done", headers=s1)
    for rid in (next_week, str(nxt[0].id)):
        await c.delete(f"/calendar/reminders/{rid}", headers=s1)

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

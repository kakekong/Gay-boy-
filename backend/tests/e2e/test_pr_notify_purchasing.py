"""Purchasing hears about a new price request — on the bell and on the phone.

Two ways it went quiet. The bell took the *oldest* twenty requests waiting for
a cost and dropped the rest, so once twenty were waiting every new one fell
off the end — the very item the alert exists for. And the phone only heard on
the background sweeper's next tick (every 15 minutes, working hours only).

Now: the queue is newest-first, the submit pushes to purchasing at once, and
the push is recorded so the sweeper does not send it a second time.
"""
import asyncio, os, sys, uuid
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
    from app.services import webpush
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    s1 = await login("sales1@demo.local")
    pur = await login("purchasing@demo.local")
    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Antre {TAG}", "industry": "mining"}))["id"]

    async def submitted(label):
        pr = J(await c.post("/price-requests", headers=s1, json={
            "customer_id": cust, "items": [{"description": f"{label} {TAG}", "qty": 2, "uom": "pcs"}]}))
        r = await c.post(f"/price-requests/{pr['id']}/submit", headers=s1)
        assert r.status_code == 200, r.text
        return pr

    print("\n── a long queue ──")
    for i in range(25):
        await submitted(f"OLD {i}")
    from app.core.db import SessionLocal
    from app.models.price_request import PriceRequest
    from sqlalchemy import func, select
    async with SessionLocal() as s:
        waiting = await s.scalar(select(func.count()).select_from(PriceRequest).where(
            PriceRequest.status == "pending_purchasing", PriceRequest.is_deleted.is_(False)))
    check("more than twenty requests are waiting for a cost", waiting > 20, str(waiting))

    # A phone for purchasing, with the push service replaced by a recorder.
    from app.models.push import PushDelivered, PushSubscription
    from app.models.user import User
    async with SessionLocal() as s:
        pid = await s.scalar(select(User.id).where(User.email == "purchasing@demo.local"))
        s.add(PushSubscription(user_id=pid, endpoint=f"https://push.example/{uuid.uuid4().hex}",
                               p256dh="x" * 20, auth="y" * 10, user_agent="test"))
        await s.commit()
    sent: list[dict] = []
    real = webpush._send_one
    webpush._send_one = lambda sub, payload, pem: (sent.append(payload) or {"ok": True, "dead": False, "detail": None})
    try:
        print("\n── a new one arrives ──")
        new = await submitted("BRAND NEW")
        await asyncio.sleep(1.0)        # the push is fire-and-forget
        bell = J(await c.get("/notifications", headers=pur))
        ids = [i["id"] for i in bell["items"]]
        check("the newest request is on purchasing's bell", f"pr-cost:{new['id']}" in ids,
              f"{len(ids)} items")
        item = next((i for i in bell["items"] if i["id"] == f"pr-cost:{new['id']}"), {})
        check("...as work to do (high)", item.get("severity") == "high", str(item)[:150])
        check("...still without the customer's name", "ANTRE" not in str(item).upper(), str(item)[:150])
        mine = [p for p in sent if new["number"] in p.get("title", "")]
        check("purchasing's phone is told straight away", len(mine) == 1, str(sent)[-2:])
        check("...with a link that opens the request",
              mine and mine[0]["url"] == f"/price-requests?open={new['id']}", str(mine)[:200])
        check("...and no customer name", mine and "ANTRE" not in str(mine[0]).upper(), str(mine)[:200])
        async with SessionLocal() as s:
            rec = await s.scalar(select(func.count()).select_from(PushDelivered).where(
                PushDelivered.user_id == pid, PushDelivered.item_id == f"pr-cost:{new['id']}"))
        check("...and it is recorded as delivered", rec == 1, str(rec))
        before = len(sent)
        async with SessionLocal() as s:
            u = await s.get(User, pid)
            await webpush.sweep_once(s)
            await s.commit()
        again = [p for p in sent[before:] if new["number"] in p.get("title", "")]
        check("the 15-minute sweeper does not send it a second time", not again, str(again)[:200])
    finally:
        webpush._send_one = real
        async with SessionLocal() as s:
            from sqlalchemy import delete
            await s.execute(delete(PushSubscription).where(PushSubscription.endpoint.like("https://push.example/%")))
            await s.commit()

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

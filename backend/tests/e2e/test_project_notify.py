"""A new project tells the director and purchasing — on the bell and the phone.

The director hears the customer, the customer PO and the value; purchasing
hears there is a job to source and which price request it came from, never
the customer. Phones hear at once (after the commit — a project that rolled
back is never announced), and the sweeper does not repeat it. Whoever opened
the project is not told about their own act.
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
    from sqlalchemy import select, func, delete
    from app.core.db import SessionLocal
    from app.core.security import hash_password
    from app.models.user import User
    from app.models.push import PushDelivered, PushSubscription
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    # A second director approves, so the first one is the person to tell.
    d2_email = f"director2-{TAG}@demo.local".lower()
    async with SessionLocal() as s:
        s.add(User(email=d2_email, full_name=f"Second Director {TAG}", role="director",
                   password_hash=hash_password("test-pass-123"), is_active=True))
        ids = {}
        for e in ("director@demo.local", "purchasing@demo.local", d2_email):
            pass
        await s.commit()
        for e in ("director@demo.local", "purchasing@demo.local", d2_email):
            ids[e] = await s.scalar(select(User.id).where(User.email == e))
            s.add(PushSubscription(user_id=ids[e], endpoint=f"https://push.example/{uuid.uuid4().hex}",
                                   p256dh="x" * 20, auth="y" * 10, user_agent="test"))
        await s.commit()
    by_endpoint = {}
    async with SessionLocal() as s:
        for sub in (await s.scalars(select(PushSubscription).where(
                PushSubscription.endpoint.like("https://push.example/%")))).all():
            by_endpoint[sub.endpoint] = sub.user_id
    sent: list[tuple] = []
    real = webpush._send_one
    webpush._send_one = lambda sub, payload, pem: (
        sent.append((sub.user_id, payload)) or {"ok": True, "dead": False, "detail": None})

    d = await login("director@demo.local")
    d2 = await login(d2_email)
    s1 = await login("sales1@demo.local")
    pur = await login("purchasing@demo.local")
    try:
        cust = J(await c.post("/customers", headers=s1, json={
            "company_name": f"PT Proyek Baru {TAG}", "industry": "mining"}))["id"]
        pr = J(await c.post("/price-requests", headers=s1, json={
            "customer_id": cust, "items": [{"description": f"CHAIN {TAG}", "qty": 4, "uom": "pcs"}]}))
        await c.post(f"/price-requests/{pr['id']}/submit", headers=s1)
        await c.post(f"/price-requests/{pr['id']}/price", headers=pur, json={
            "items": [{"line_no": 1, "cost_price": 1_000_000, "basis": "unit"}]})
        await c.post(f"/price-requests/{pr['id']}/approve", headers=d2, json={
            "items": [{"line_no": 1, "sell_price": 2_500_000, "basis": "unit"}]})
        q = J(await c.post(f"/quotations/from-price-request/{pr['id']}", headers=s1))
        await c.post(f"/quotations/{q['id']}/submit", headers=s1)
        await c.post(f"/quotations/{q['id']}/approve", headers=d2, json={"notes": ""})
        po = J(await c.post("/customer-pos", headers=s1, json={
            "customer_id": cust, "quotation_id": q["id"], "number": f"PO-BARU-{TAG}",
            "items": [{"description": f"CHAIN {TAG}", "qty": 4, "unit_price": 2_500_000}],
            "is_downpayment": False}))
        # The project may open at Won or at the PO approval, depending on how
        # the deal was set up — count the pushes from either step.
        sent.clear()
        await c.post(f"/quotations/{q['id']}/won", headers=d2)
        proj = J(await c.post(f"/customer-pos/{po['id']}/approve", headers=d2,
                              json={"notes": ""})).get("project_id")
        check("the second director approves and a project opens", bool(proj), str(proj))
        await asyncio.sleep(1.0)

        print("\n── phones ──")
        to = lambda e: [p for uid, p in sent
                        if uid == ids[e] and p.get("url") == f"/projects/{proj}"]
        dp = to("director@demo.local")
        check("the director's phone hears at once", len(dp) == 1, str(sent)[:300])
        check("...with the customer, the PO and the value",
              dp and f"PT PROYEK BARU {TAG}" in dp[0]["title"] and f"PO-BARU-{TAG}" in dp[0]["body"]
              and "10.000.000" in dp[0]["body"], str(dp)[:300])
        check("...opening the project", dp and dp[0]["url"] == f"/projects/{proj}", str(dp)[:200])
        pp = to("purchasing@demo.local")
        check("purchasing's phone hears at once", len(pp) == 1, str(sent)[:300])
        check("...that there is a job to source, and from which price request",
              pp and "New job to source" in pp[0]["title"] and pr["number"] in pp[0]["body"], str(pp)[:300])
        check("...and never whose it is", pp and "PROYEK BARU" not in str(pp[0]).upper()
              and f"PO-BARU-{TAG}" not in str(pp[0]), str(pp)[:300])
        check("the director who opened it is not told about their own act",
              not to(d2_email), str(to(d2_email))[:200])

        print("\n── bells ──")
        bell = J(await c.get("/notifications", headers=d))
        it = next((i for i in bell["items"] if i["id"] == f"project-dir:{proj}"), None)
        check("the director's bell has it", it is not None and it["severity"] == "medium", str(it)[:200])
        bell2 = J(await c.get("/notifications", headers=d2))
        check("...the approving director's does not", not any(
            i["id"] == f"project-dir:{proj}" for i in bell2["items"]))
        pb = J(await c.get("/notifications", headers=pur))
        it = next((i for i in pb["items"] if i["id"] == f"project-new:{proj}"), None)
        check("purchasing's bell has the job to source", it is not None and it["severity"] == "high",
              str(it)[:200])
        check("...customer-blind", it and "PROYEK BARU" not in str(it).upper(), str(it)[:200])

        print("\n── no repeats, no ghosts ──")
        before = len(sent)
        async with SessionLocal() as s:
            await webpush.sweep_once(s)
            await s.commit()
        again = [p for _, p in sent[before:] if proj in (p.get("url") or "")]
        check("the 15-minute sweeper does not send either again", not again, str(again)[:200])

        from app.services.project_factory import create_project
        before = len(sent)
        async with SessionLocal() as s:
            u = await s.get(User, ids[d2_email])
            ghost = await create_project(s, user=u, customer_id=uuid.UUID(cust))
            await s.rollback()
        await asyncio.sleep(0.5)
        check("a project that rolled back is never announced",
              not [p for _, p in sent[before:] if str(ghost.id) in (p.get("url") or "")],
              str(sent[before:])[:200])
    finally:
        webpush._send_one = real
        async with SessionLocal() as s:
            await s.execute(delete(PushSubscription).where(PushSubscription.endpoint.like("https://push.example/%")))
            await s.execute(delete(User).where(User.email == d2_email))
            await s.commit()

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

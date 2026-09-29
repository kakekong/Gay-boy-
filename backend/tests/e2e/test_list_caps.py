"""Lists that stopped at a fixed number of rows without saying so.

The customer list once showed 50 of 87 after an import, and nothing on the
screen said the rest existed. The same shape was elsewhere: the Quotations
page read the newest 50 quotations, a customer's activity timeline the newest
50 (and its "activities logged" topped out at 100), and the Cash & Bank,
journal, fixed-asset, audit and attachment lists clamped their page size on
the server, so a "Load more" stops loading. This builds past each old cap
and checks every row is still reachable.
"""
import asyncio, os, sys, uuid
from datetime import datetime, timedelta, UTC
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123",
    STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import httpx, logging; logging.disable(logging.INFO)
TAG = uuid.uuid4().hex[:6].upper()
PASS, FAIL = [], []
def check(n, c, d=""):
    (PASS if c else FAIL).append(n); print(("  PASS " if c else "  FAIL ")+n+(f"  [{d}]" if d and not c else ""))
def J(r):
    try: return r.json()
    except Exception: return {"_": r.text[:200]}


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    from app.core.db import SessionLocal
    from app.models.crm import Activity, Customer
    from app.models.quotation import Quotation
    from app.models.user import User
    from sqlalchemy import select
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)

    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")

    # ── one customer with more quotations and activities than the old caps ──
    now = datetime.now(UTC)
    async with SessionLocal() as db:
        rep = await db.scalar(select(User).where(User.email == "sales1@demo.local"))
        cu = Customer(company_name=f"PT Banyak {TAG}", industry="mining",
                      sales_pic_id=rep.id)
        db.add(cu); await db.flush()
        for i in range(60):
            db.add(Quotation(number=f"Q-CAP-{TAG}-{i:03d}", customer_id=cu.id,
                             sales_pic_id=rep.id, status="sent"))
        for i in range(120):
            db.add(Activity(customer_id=cu.id, user_id=rep.id, type="call",
                            direction="outbound", occurred_at=now - timedelta(hours=i),
                            notes=f"call {i}"))
        await db.commit()
        cid = str(cu.id)

    print("\n── quotations ──")
    rows = J(await c.get("/quotations", headers=d, params={"customer_id": cid}))
    check("a customer's quotations are all listed, not the newest 50",
          isinstance(rows, list) and len(rows) == 60, str(len(rows) if isinstance(rows, list) else rows))
    rows = J(await c.get("/quotations", headers=d))
    check("the Quotations page is not cut at 50",
          isinstance(rows, list) and len(rows) >= 60, str(len(rows)))
    rows = J(await c.get("/quotations", headers=d, params={"limit": 5}))
    check("...and a caller can still ask for fewer", len(rows) == 5, str(len(rows)))

    print("\n── a customer's activity ──")
    acts = J(await c.get(f"/customers/{cid}/activities", headers=d))
    check("the timeline has every activity, not the newest 50",
          len(acts) == 120, str(len(acts)))
    s = J(await c.get(f"/customers/{cid}/summary", headers=d))
    check("'activities logged' counts all of them, not up to 100",
          s["stats"]["activities_logged"] == 120, str(s["stats"]["activities_logged"]))

    print("\n── lists that page ──")
    for path, key in (("/cash", "items"), ("/journals", "items"),
                      ("/assets", "items"), ("/inventory", "items")):
        r = await c.get(path, headers=d, params={"limit": 1500})
        check(f"{path} accepts a page past its old ceiling", r.status_code == 200,
              f"{r.status_code} {str(J(r))[:120]}")
    for path in ("/audit", "/attachments/all"):
        r = await c.get(path, headers=d, params={"limit": 1500})
        check(f"{path} accepts a page past its old ceiling", r.status_code == 200,
              f"{r.status_code} {str(J(r))[:120]}")

    print("\n── every customer, for the pickers and the board ──")
    tot = J(await c.get("/customers", headers=d, params={"page_size": 1}))["total"]
    got, page = 0, 1
    while True:
        b = J(await c.get("/customers", headers=d, params={"page": page, "page_size": 500}))
        got += len(b["data"])
        if not b["data"] or got >= b["total"]:
            break
        page += 1
    check("paging through /customers reaches the total", got == tot, f"{got} of {tot}")

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

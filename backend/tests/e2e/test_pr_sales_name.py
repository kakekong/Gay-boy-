"""The director sees which sales each price request is for.

* Each request names its sales (the customer's rep) — on the list and on
  the request itself.
* Filed by someone else (the director, for the rep), it says who filed it.
* Purchasing, who don't see the customer side, don't get the names.
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
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t/api/v1", timeout=180)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d, s1, pur = (await login("director@demo.local"), await login("sales1@demo.local"),
                  await login("purchasing@demo.local"))
    me = J(await c.get("/auth/me", headers=s1)); dme = J(await c.get("/auth/me", headers=d))

    cust = J(await c.post("/customers", headers=s1, json={"company_name": f"PT SIAPA {TAG}", "industry": "mining"}))["id"]
    own = J(await c.post("/price-requests", headers=s1, json={"customer_id": cust, "items": [
        {"description": f"BOLT {TAG}", "qty": 1, "uom": "pcs"}]}))
    await c.post(f"/price-requests/{own['id']}/submit", headers=s1)
    by_dir = J(await c.post("/price-requests", headers=d, json={"customer_id": cust, "items": [
        {"description": f"NUT {TAG}", "qty": 1, "uom": "pcs"}]}))
    await c.post(f"/price-requests/{by_dir['id']}/submit", headers=d)

    rows = {r["id"]: r for r in J(await c.get("/price-requests", headers=d))}
    a, b = rows.get(own["id"], {}), rows.get(by_dir["id"], {})
    check("the director's list names the sales on each request", a.get("sales_pic_name") == me["full_name"],
          str(a.get("sales_pic_name")))
    check("...filed by the rep themselves: no 'filed by'", a.get("filed_by_name") is None, str(a.get("filed_by_name")))
    check("filed by the director for the rep: still the rep's, and says who filed it",
          b.get("sales_pic_name") == me["full_name"] and b.get("filed_by_name") == dme["full_name"],
          f"{b.get('sales_pic_name')} / {b.get('filed_by_name')}")
    one = J(await c.get(f"/price-requests/{own['id']}", headers=d))
    check("the request itself names the sales too", one.get("sales_pic_name") == me["full_name"])
    prow = next((r for r in J(await c.get("/price-requests", headers=pur)) if r["id"] == own["id"]), {})
    check("purchasing doesn't get the names", prow and "sales_pic_name" not in prow and "filed_by_name" not in prow,
          str(prow)[:160])

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

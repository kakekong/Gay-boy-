"""A customer can be deactivated like a user — kept, not erased.

Deactivated: out of the customer list and every picker built on it, no new
price requests or quotations, everything already on file intact and still
openable, and one click (director or manager) to bring them back.
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
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=120)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    mgr = await login("manager@demo.local")
    s1 = await login("sales1@demo.local")

    me = J(await c.get("/auth/me", headers=s1))
    cust = J(await c.post("/customers", headers=d, json={
        "company_name": f"PT Tidur {TAG}", "industry": "mining",
        "sales_pic_id": me.get("id")}))
    cid = cust["id"]
    pr = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cid, "items": [{"description": f"CHAIN {TAG}", "qty": 1}]}))
    check("work exists before deactivating (a price request)", "id" in pr, str(pr)[:200])

    async def listed(status=None, who=d):
        params = {"q": TAG, "page_size": 50}
        if status:
            params["status"] = status
        return {x["id"] for x in J(await c.get("/customers", headers=who, params=params))["data"]}

    check("an active customer is in the list", cid in await listed())

    print("\n── deactivating ──")
    r = await c.post(f"/customers/{cid}/deactivate", headers=s1, json={})
    check("sales cannot deactivate", r.status_code == 403, str(r.status_code))
    r = await c.post(f"/customers/{cid}/deactivate", headers=d, json={"reason": "stopped ordering"})
    body = J(r)
    check("the director deactivates, with a reason", r.status_code == 200
          and body.get("is_active") is False and body.get("deactivated_reason") == "stopped ordering",
          f"{r.status_code} {str(body)[:200]}")
    check("it leaves the customer list (and the pickers built on it)", cid not in await listed())
    check("...and the rep's list too", cid not in await listed(who=s1))
    check("it is under 'deactivated'", cid in await listed("inactive"))
    check("...and under 'all'", cid in await listed("all"))

    r = await c.get(f"/customers/{cid}", headers=s1)
    check("its page still opens, saying it is deactivated",
          r.status_code == 200 and J(r).get("is_active") is False, str(r.status_code))
    r = await c.get(f"/price-requests/{pr['id']}", headers=s1)
    check("its existing price request is untouched", r.status_code == 200, str(r.status_code))
    r = await c.get(f"/customers/{cid}/summary", headers=d)
    check("its history is all there", r.status_code == 200, str(r.status_code))

    r = await c.post("/price-requests", headers=s1, json={
        "customer_id": cid, "items": [{"description": "NEW", "qty": 1}]})
    check("no new price request for a deactivated customer", r.status_code == 409,
          f"{r.status_code} {str(J(r))[:160]}")
    msg = str(J(r))
    check("...and it says how to undo it", "reactivate" in msg.lower(), msg[:160])
    r = await c.post("/quotations", headers=d, json={"customer_id": cid, "items": []})
    check("no new quotation either", r.status_code == 409, f"{r.status_code} {str(J(r))[:160]}")

    print("\n── reactivating ──")
    r = await c.post(f"/customers/{cid}/reactivate", headers=mgr)
    check("a manager reactivates", r.status_code == 200 and J(r).get("is_active") is True,
          f"{r.status_code} {str(J(r))[:160]}")
    check("it is back in the list", cid in await listed())
    r = await c.post("/price-requests", headers=s1, json={
        "customer_id": cid, "items": [{"description": "NEW", "qty": 1}]})
    check("and can take new work again", r.status_code in (200, 201), f"{r.status_code} {str(J(r))[:160]}")

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

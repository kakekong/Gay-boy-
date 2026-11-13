"""Deleting a supplier price request entered wrongly — even applied and closed.

* A quote with the wrong supplier and price was applied as the cost and
  closed. Purchasing can't delete it; the director can.
* Its price request lines lose the link to it (supplier, quoted currency),
  keep the figure, and the request is noted; the right quote then applies.
* On a settled request, the cost revision a quote queued for the director
  is withdrawn with it.
* A draft is still anyone's to throw away.
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
BASE = "/purchasing/price-requests"


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    pur = await login("purchasing@demo.local")
    s1 = await login("sales1@demo.local")

    wrong = J(await c.post("/purchasing/suppliers", headers=d, json={"name": f"PT SALAH {TAG}"}))["id"]
    right = J(await c.post("/purchasing/suppliers", headers=d, json={"name": f"PT BENAR {TAG}"}))["id"]
    cust = J(await c.post("/customers", headers=s1, json={"company_name": f"PT HAPUS {TAG}", "industry": "mining"}))["id"]
    pr = J(await c.post("/price-requests", headers=s1, json={"customer_id": cust, "items": [
        {"description": f"CHAIN {TAG}", "qty": 10, "uom": "meter"}]}))
    await c.post(f"/price-requests/{pr['id']}/submit", headers=s1)
    async def line():
        return J(await c.get(f"/price-requests/{pr['id']}", headers=d))["items"][0]

    print("\n── a wrong quote, applied and closed ──")
    a = J(await c.post(BASE, headers=pur, json={"supplier_ids": [wrong], "price_request_id": pr["id"]}))[0]
    await c.post(f"{BASE}/{a['id']}/quote", headers=pur, json={"currency": "CNY", "fx_rate": 2200,
                                                               "items": [{"line_no": 1, "quoted_price": 99}]})
    await c.post(f"{BASE}/{a['id']}/apply", headers=pur)
    await c.post(f"{BASE}/{a['id']}/close", headers=pur, json={"reason": "done"})
    L = await line()
    check("it is the line's cost, from the wrong supplier", L.get("cost_source") == a["number"]
          and L.get("cost_price") == 217_800, str(L)[:200])
    r = await c.delete(f"{BASE}/{a['id']}", headers=pur)
    check("purchasing can't delete it once answered", r.status_code == 409, str(r.status_code))
    r = await c.delete(f"{BASE}/{a['id']}", headers=d, params={"reason": "wrong supplier and price"})
    out = J(r)
    check("the director deletes it, closed and applied as it is", r.status_code == 200
          and out.get("unlinked") == [{"price_request": pr["number"], "lines": [1]}], f"{r.status_code} {out}")
    check("...it is gone", (await c.get(f"{BASE}/{a['id']}", headers=d)).status_code == 404)
    L = await line()
    check("...the line no longer names it, nor its supplier or yuan — the figure stays",
          not L.get("cost_source") and not L.get("cost_supplier") and not L.get("cost_currency")
          and L.get("cost_price") == 217_800, str(L)[:200])
    notes = J(await c.get(f"/price-requests/{pr['id']}", headers=d)).get("notes") or ""
    check("...and the request says why", a["number"] in notes and "wrong supplier and price" in notes, notes[-200:])

    print("\n── the right one goes in ──")
    b = J(await c.post(BASE, headers=pur, json={"supplier_ids": [right], "price_request_id": pr["id"]}))[0]
    await c.post(f"{BASE}/{b['id']}/quote", headers=pur, json={"items": [{"line_no": 1, "quoted_price": 150_000}]})
    r = await c.post(f"{BASE}/{b['id']}/apply", headers=pur)
    L = await line()
    check("the right quote is the cost now", r.status_code == 200 and L.get("cost_source") == b["number"]
          and L.get("cost_price") == 150_000, f"{r.status_code} {str(L)[:160]}")

    print("\n── on a settled request, its queued revision goes too ──")
    await c.post(f"/price-requests/{pr['id']}/approve", headers=d, json={"items": [{"line_no": 1, "sell_price": 250_000}]})
    x = J(await c.post(BASE, headers=pur, json={"supplier_ids": [wrong], "price_request_id": pr["id"]}))[0]
    await c.post(f"{BASE}/{x['id']}/quote", headers=pur, json={"items": [{"line_no": 1, "quoted_price": 1}]})
    await c.post(f"{BASE}/{x['id']}/apply", headers=pur)
    revs = J(await c.get(f"/price-requests/{pr['id']}/revisions", headers=d))
    revs = revs if isinstance(revs, list) else revs.get("items", revs.get("revisions", []))
    check("the quote queued a cost revision for the director",
          any(rv.get("status") == "pending" for rv in revs), str(revs)[:200])
    r = await c.delete(f"{BASE}/{x['id']}", headers=d)
    revs = J(await c.get(f"/price-requests/{pr['id']}/revisions", headers=d))
    revs = revs if isinstance(revs, list) else revs.get("items", revs.get("revisions", []))
    check("deleting it withdraws that revision", r.status_code == 200 and J(r).get("withdrawn")
          and not any(rv.get("status") == "pending" for rv in revs), f"{r.status_code} {J(r)}")
    appr = J(await c.get("/approvals", headers=d, params={"status": "pending"}))
    appr = appr if isinstance(appr, list) else appr.get("items", appr.get("data", []))
    left = [(a_.get("reason"), a_.get("status"), a_.get("target_type")) for a_ in appr
            if pr["number"] in (a_.get("reason") or "") and "revision" in (a_.get("reason") or "").lower()]
    check("...and it leaves the director's approvals", not left, str(left)[:300])

    print("\n── a draft ──")
    dr = J(await c.post(BASE, headers=pur, json={"supplier_ids": [right], "price_request_id": pr["id"]}))[0]
    r = await c.delete(f"{BASE}/{dr['id']}", headers=pur)
    check("a draft is still anyone's to throw away", r.status_code == 204, str(r.status_code))

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

"""A cost the director changes on a price request follows to the supplier quote.

* Two vendors quote; one quote (in yuan) is applied as the cost.
* The director changes a line's cost at approval, in yuan: the applied
  quote's line takes the yuan figure; the losing quote is left alone.
* Repriced in rupiah later: the quote takes the rupiah cost turned back into
  yuan at its own rate.
* A line costed by hand, with two vendors asked and neither named, is not
  guessed at — the response says so.
* A cost corrected on the job's order follows the same way.
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

    sup_a = J(await c.post("/purchasing/suppliers", headers=d, json={"name": f"PT GZ {TAG}"}))["id"]
    sup_b = J(await c.post("/purchasing/suppliers", headers=d, json={"name": f"PT LOKAL {TAG}"}))["id"]
    cust = J(await c.post("/customers", headers=s1, json={"company_name": f"PT SINKRON {TAG}", "industry": "mining"}))["id"]
    pr = J(await c.post("/price-requests", headers=s1, json={"customer_id": cust, "items": [
        {"description": f"CHAIN RS80 {TAG}", "qty": 10, "uom": "meter"},
        {"description": f"SPROCKET {TAG}", "qty": 2, "uom": "pcs"}]}))
    await c.post(f"/price-requests/{pr['id']}/submit", headers=s1)
    a, b = J(await c.post(BASE, headers=pur, json={"supplier_ids": [sup_a, sup_b], "price_request_id": pr["id"]}))
    await c.post(f"{BASE}/{a['id']}/quote", headers=pur, json={"currency": "CNY", "fx_rate": 2200, "items": [
        {"line_no": 1, "quoted_price": 10, "basis": "unit"}]})
    await c.post(f"{BASE}/{b['id']}/quote", headers=pur, json={"items": [
        {"line_no": 1, "quoted_price": 30_000, "basis": "unit"}]})
    r = await c.post(f"{BASE}/{a['id']}/apply", headers=pur)
    check("the yuan quote is applied as the cost", r.status_code == 200, f"{r.status_code} {J(r)}"[:160])
    l1 = J(await c.get(f"/price-requests/{pr['id']}", headers=d))["items"][0]
    check("...and the line reads in yuan: ¥10 × 2.200 = Rp 22.000",
          l1.get("cost_currency") == "CNY" and l1.get("cost_original") == 10
          and l1.get("cost_fx_rate") == 2200 and l1.get("cost_price") == 22_000, str(l1)[:240])
    async def quote_line(spr, n=1):
        x = J(await c.get(f"{BASE}/{spr}", headers=pur))
        return next(i for i in x["items"] if i["line_no"] == n), x

    print("\n── the director changes it at approval ──")
    r = await c.post(f"/price-requests/{pr['id']}/approve", headers=d, json={"items": [
        {"line_no": 1, "sell_price": 50_000, "cost_price": 12, "cost_currency": "CNY", "cost_fx_rate": 2200},
        {"line_no": 2, "sell_price": 200_000, "cost_price": 120_000}]})
    out = J(r)
    la, xa = await quote_line(a["id"])
    lb, _ = await quote_line(b["id"])
    check("the applied quote now says ¥12", r.status_code == 200 and float(la["quoted_price"]) == 12,
          f"{r.status_code} {la.get('quoted_price')}")
    check("...the quote that lost is left alone", float(lb["quoted_price"]) == 30_000, str(lb.get("quoted_price")))
    check("...the quote's log says why", "cost changed on the price request" in (xa.get("notes") or ""),
          str(xa.get("notes"))[-160:])
    rows = {x["line_no"]: x for x in out.get("supplier_quotes", [])}
    check("...and the response says which quote moved", rows.get(1, {}).get("spr") == a["number"]
          and rows[1].get("to") == 12, str(out.get("supplier_quotes")))
    check("a line costed by hand with two vendors asked and none named is not guessed at",
          "skipped" in rows.get(2, {}), str(rows.get(2)))

    print("\n── repriced in rupiah ──")
    r = await c.post(f"/price-requests/{pr['id']}/reprice", headers=d, json={"reason": "new price", "items": [
        {"line_no": 1, "cost_price": 33_000, "cost_currency": "IDR"}]})
    la, _ = await quote_line(a["id"])
    check("Rp 33.000 on a yuan quote at 2.200: ¥15", r.status_code == 200 and float(la["quoted_price"]) == 15,
          f"{r.status_code} {la.get('quoted_price')}")

    print("\n── on the job's order ──")
    qid = J(await c.post(f"/quotations/from-price-request/{pr['id']}", headers=s1))["id"]
    await c.post(f"/quotations/{qid}/submit", headers=s1)
    await c.post(f"/quotations/{qid}/approve", headers=d, json={"notes": ""})
    cpo = J(await c.post("/customer-pos", headers=s1, json={
        "customer_id": cust, "quotation_id": qid, "number": f"CPO-{TAG}",
        "items": [{"description": f"CHAIN RS80 {TAG}", "qty": 10, "unit_price": 50_000, "line_no": 1}],
        "is_downpayment": False}))
    await c.post(f"/quotations/{qid}/won", headers=d)
    pid = J(await c.post(f"/customer-pos/{cpo['id']}/approve", headers=d, json={"notes": ""})).get("project_id")
    r = await c.post(f"/operation/projects/{pid}/order-costs", headers=d, json={"lines": [{"line_no": 1, "cost_price": 39_600}]})
    la, _ = await quote_line(a["id"])
    check("a cost corrected on the order: ¥18 on the quote", r.status_code == 200 and float(la["quoted_price"]) == 18,
          f"{r.status_code} {J(r)} {la.get('quoted_price')}"[:200])

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

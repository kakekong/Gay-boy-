"""A currency per line on a supplier price request.

* A yuan quote with one line priced in rupiah: each line keeps its own
  currency; the total is in the quote's currency (converted) and in rupiah.
* A line in a currency with no rate can't be applied — the refusal names it.
* Applied, each line becomes its cost at its own rate.
* Changing the quote's currency recosts only the lines that follow it.
* A cost the director changes goes back to the line in that line's currency.
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

    sup = J(await c.post("/purchasing/suppliers", headers=d, json={"name": f"PT CAMPUR {TAG}"}))["id"]
    cust = J(await c.post("/customers", headers=s1, json={"company_name": f"PT KURS GARIS {TAG}", "industry": "mining"}))["id"]
    pr = J(await c.post("/price-requests", headers=s1, json={"customer_id": cust, "items": [
        {"description": f"CHAIN {TAG}", "qty": 10, "uom": "meter"},
        {"description": f"SHACKLE {TAG}", "qty": 4, "uom": "pcs"},
        {"description": f"PIN {TAG}", "qty": 2, "uom": "pcs"}]}))
    await c.post(f"/price-requests/{pr['id']}/submit", headers=s1)
    q = J(await c.post(BASE, headers=pur, json={"supplier_ids": [sup], "price_request_id": pr["id"]}))[0]

    print("\n── a yuan quote, one line in rupiah, one in dollars without a rate ──")
    r = await c.post(f"{BASE}/{q['id']}/quote", headers=pur, json={"currency": "CNY", "fx_rate": 2200, "items": [
        {"line_no": 1, "quoted_price": 10, "currency": "CNY"},
        {"line_no": 2, "quoted_price": 150_000, "currency": "IDR"},
        {"line_no": 3, "quoted_price": 5, "currency": "USD"}]})
    x = J(r)
    L = {i["line_no"]: i for i in x.get("items", [])}
    check("each line keeps its own currency; the quote's own needs none",
          r.status_code == 200 and not L[1].get("currency") and L[2].get("currency") == "IDR"
          and L[3].get("currency") == "USD", f"{r.status_code} {[(k, v.get('currency')) for k, v in L.items()]}")
    r = await c.post(f"{BASE}/{q['id']}/apply", headers=pur)
    check("a line in dollars with no rate can't be applied — the refusal names it",
          r.status_code == 409 and "line 3" in str(J(r)) and "USD" in str(J(r)), f"{r.status_code} {J(r)}"[:200])

    r = await c.post(f"{BASE}/{q['id']}/quote", headers=pur, json={"items": [
        {"line_no": 3, "quoted_price": 5, "currency": "USD", "fx_rate": 16_000}]})
    x = J(r)
    # CNY: 10×10 = 100; Rp 600.000 / 2200 = 272,73; $10 × 16.000 / 2200 = 72,73
    check("the total is in yuan, converted: ¥445,45", abs(x.get("quoted_total", 0) - (100 + 600_000 / 2200 + 160_000 / 2200)) < 0.01,
          str(x.get("quoted_total")))
    check("...and in rupiah: Rp 980.000", abs((x.get("quoted_total_idr") or 0) - 980_000) < 0.01 and x.get("mixed_currency"),
          f"{x.get('quoted_total_idr')} {x.get('mixed_currency')}")

    print("\n── applied ──")
    r = await c.post(f"{BASE}/{q['id']}/apply", headers=pur)
    P = {i["line_no"]: i for i in J(await c.get(f"/price-requests/{pr['id']}", headers=d))["items"]}
    check("¥10 at 2.200 → Rp 22.000, kept in yuan", r.status_code == 200 and P[1]["cost_price"] == 22_000
          and P[1].get("cost_currency") == "CNY", f"{r.status_code} {str(P[1])[:160]}")
    check("Rp 150.000 → Rp 150.000, plain rupiah", P[2]["cost_price"] == 150_000 and not P[2].get("cost_currency"),
          str(P[2])[:160])
    check("$5 at 16.000 → Rp 80.000, kept in dollars", P[3]["cost_price"] == 80_000 and P[3].get("cost_currency") == "USD"
          and P[3].get("cost_original") == 5, str(P[3])[:160])

    print("\n── the quote's rate changes ──")
    r = await c.patch(f"{BASE}/{q['id']}/currency", headers=pur, json={"currency": "CNY", "fx_rate": 2300})
    P = {i["line_no"]: i for i in J(await c.get(f"/price-requests/{pr['id']}", headers=d))["items"]}
    check("only the line that follows it moves: ¥10 → Rp 23.000; the rupiah and dollar lines stay",
          r.status_code == 200 and P[1]["cost_price"] == 23_000 and P[2]["cost_price"] == 150_000
          and P[3]["cost_price"] == 80_000, f"{r.status_code} {[P[n]['cost_price'] for n in (1, 2, 3)]}")

    print("\n── the director changes a cost ──")
    r = await c.post(f"/price-requests/{pr['id']}/approve", headers=d, json={"items": [
        {"line_no": 1, "sell_price": 50_000}, {"line_no": 2, "sell_price": 250_000, "cost_price": 160_000},
        {"line_no": 3, "sell_price": 150_000}]})
    L = {i["line_no"]: i for i in J(await c.get(f"{BASE}/{q['id']}", headers=pur))["items"]}
    check("the rupiah line on the quote takes Rp 160.000, in rupiah",
          r.status_code == 200 and float(L[2]["quoted_price"]) == 160_000 and float(L[1]["quoted_price"]) == 10,
          f"{r.status_code} {[L[n].get('quoted_price') for n in (1, 2, 3)]}")

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

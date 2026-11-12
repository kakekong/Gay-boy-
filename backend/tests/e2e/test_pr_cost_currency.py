"""A price request cost typed in the supplier's currency.

* Purchasing or the director types a cost in yuan, dollars… with its rupiah
  rate; the line keeps that figure and rate, and its cost is the rupiah
  equivalent every margin and quotation reads.
* A total on the line is divided by the quantity first.
* A foreign cost needs a rate; only the currencies a PO is written in.
* Reprice moves it to another currency, or back to rupiah.
* Sales see none of it.
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
                          base_url="http://t/api/v1", timeout=180)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    s1 = await login("sales1@demo.local")
    pur = await login("purchasing@demo.local")

    cust = J(await c.post("/customers", headers=s1, json={"company_name": f"PT KURS {TAG}", "industry": "mining"}))["id"]
    pr = J(await c.post("/price-requests", headers=s1, json={"customer_id": cust, "items": [
        {"description": f"CHAIN 80-1 {TAG}", "qty": 10, "uom": "meter"},
        {"description": f"SPROCKET {TAG}", "qty": 2, "uom": "pcs"}]}))["id"]
    await c.post(f"/price-requests/{pr}/submit", headers=s1)
    async def lines(who=d):
        return {i["line_no"]: i for i in J(await c.get(f"/price-requests/{pr}", headers=who))["items"]}

    print("\n── purchasing costs a line in yuan ──")
    r = await c.post(f"/price-requests/{pr}/price", headers=pur, json={"items": [
        {"line_no": 1, "cost_price": 10, "basis": "unit", "cost_currency": "CNY", "cost_fx_rate": 2200},
        {"line_no": 2, "cost_price": 150_000, "basis": "unit"}]})
    L = await lines()
    check("¥10 at 2.200: the cost is Rp 22.000, the yuan kept beside it",
          r.status_code == 200 and L[1]["cost_price"] == 22_000 and L[1].get("cost_currency") == "CNY"
          and L[1].get("cost_original") == 10 and L[1].get("cost_fx_rate") == 2200, str(L[1])[:240])
    check("...a rupiah line stays plain rupiah", L[2]["cost_price"] == 150_000 and not L[2].get("cost_currency"),
          str(L[2])[:200])

    print("\n── the director, at approval, in dollars ──")
    r = await c.post(f"/price-requests/{pr}/approve", headers=d, json={"items": [
        {"line_no": 1, "sell_price": 400_000, "basis": "unit",
         "cost_price": 100, "cost_basis": "total", "cost_currency": "USD"},
    ]})
    check("a foreign cost with no rate is refused", r.status_code == 400 and "rate" in str(J(r)).lower(),
          f"{r.status_code} {J(r)}"[:160])
    r = await c.post(f"/price-requests/{pr}/approve", headers=d, json={"items": [
        {"line_no": 1, "sell_price": 400_000, "basis": "unit",
         "cost_price": 100, "cost_basis": "total", "cost_currency": "GBP", "cost_fx_rate": 20000}]})
    check("...and a currency a PO isn't written in", r.status_code == 400, str(r.status_code))
    r = await c.post(f"/price-requests/{pr}/approve", headers=d, json={"items": [
        {"line_no": 1, "sell_price": 400_000, "basis": "unit",
         "cost_price": 100, "cost_basis": "total", "cost_currency": "USD", "cost_fx_rate": 16_000},
        {"line_no": 2, "sell_price": 250_000, "basis": "unit"}]})
    L = await lines()
    check("$100 for the line of 10 at 16.000: $10 a metre, Rp 160.000",
          r.status_code == 200 and L[1]["cost_price"] == 160_000 and L[1].get("cost_currency") == "USD"
          and L[1].get("cost_original") == 10, str(L[1])[:240])

    print("\n── repriced later ──")
    r = await c.post(f"/price-requests/{pr}/reprice", headers=d, json={"reason": "new quote", "items": [
        {"line_no": 1, "cost_price": 12, "cost_currency": "CNY", "cost_fx_rate": 2250}]})
    L = await lines()
    check("to ¥12 at 2.250: Rp 27.000", r.status_code == 200 and L[1]["cost_price"] == 27_000
          and L[1].get("cost_currency") == "CNY", f"{r.status_code} {str(L[1])[:200]}")
    r = await c.post(f"/price-requests/{pr}/reprice", headers=d, json={"reason": "local supplier", "items": [
        {"line_no": 1, "cost_price": 25_000, "cost_currency": "IDR"}]})
    L = await lines()
    check("...and back to rupiah: no yuan left on it", r.status_code == 200 and L[1]["cost_price"] == 25_000
          and not L[1].get("cost_currency") and L[1].get("cost_original") is None, str(L[1])[:200])

    L = await lines(s1)
    check("sales see none of it", all("cost_price" not in x and "cost_currency" not in x for x in L.values()),
          str(L[1])[:200])

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

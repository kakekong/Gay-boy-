"""Request order: a buying price per line.

* Lines carry a unit price, in a currency a PO is written in; each keeps its line
  total, and purchasing's list shows them.
* A request waiting on the director says what it would cost.
* Sales and admin never see buying prices, so they can't set one — they
  still request without.
* Never below zero; only the listed currencies.
* Ordering a catalogue item takes the price given, else its last cost.
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
    pur = await login("purchasing@demo.local")
    s1 = await login("sales1@demo.local")

    async def pr_row(number):
        return next((x for x in J(await c.get("/purchasing/pr", headers=d)) if x["number"] == number), None)

    print("\n── a price on each line ──")
    r = await c.post("/inventory/request-order", headers=d, json={"currency": "CNY", "items": [
        {"name": f"BEARING 6205 {TAG}", "qty": 100, "uom": "pcs", "unit_price": 3.5},
        {"name": f"OIL SEAL {TAG}", "qty": 20, "uom": "pcs"}]})
    check("the director's request goes in", r.status_code == 200, f"{r.status_code} {J(r)}"[:160])
    row = await pr_row(J(r).get("number"))
    it = (row or {}).get("items", [])
    check("...the priced line keeps its price, currency and total",
          it and it[0].get("unit_price") == 3.5 and it[0].get("currency") == "CNY" and it[0].get("amount") == 350,
          str(it)[:200])
    check("...a line with no price stays without one", len(it) == 2 and it[1].get("unit_price") is None, str(it)[:200])

    print("\n── the director sees what it would cost ──")
    r = await c.post("/inventory/request-order", headers=pur, json={"items": [
        {"name": f"CHAIN RS60 {TAG}", "qty": 10, "uom": "meter", "unit_price": 125_000}]})
    num = J(r).get("number")
    data = J(await c.get("/approvals", headers=d, params={"status": "pending"}))
    rows = data if isinstance(data, list) else data.get("items", data.get("data", []))
    appr = [a for a in rows if num and num in (a.get("reason") or "")]
    check("purchasing's request waits on the director, with its total",
          r.status_code == 200 and appr and "Rp 1.250.000" in appr[0]["reason"],
          f"{r.status_code} {[a.get('reason') for a in appr]}")

    print("\n── who may price ──")
    r = await c.post("/inventory/request-order", headers=s1, json={"items": [
        {"name": f"GREASE {TAG}", "qty": 1, "uom": "pcs", "unit_price": 50_000}]})
    check("sales can't put a buying price on", r.status_code == 403, str(r.status_code))
    r = await c.post("/inventory/request-order", headers=s1, json={"items": [
        {"name": f"GREASE {TAG}", "qty": 1, "uom": "pcs"}]})
    check("...but still requests without one", r.status_code == 200, str(r.status_code))
    r = await c.post("/inventory/request-order", headers=d, json={"items": [
        {"name": f"X {TAG}", "qty": 1, "uom": "pcs", "unit_price": -1}]})
    check("never below zero", r.status_code == 400, str(r.status_code))
    r = await c.post("/inventory/request-order", headers=d, json={"currency": "XYZ", "items": [
        {"name": f"X {TAG}", "qty": 1, "uom": "pcs", "unit_price": 1}]})
    check("only the currencies a PO is written in", r.status_code == 400, str(r.status_code))

    print("\n── ordering a catalogue item ──")
    item = J(await c.post("/inventory", headers=d, json={"sku": "", "name": f"PULLEY {TAG}",
                                                         "uom": "pcs", "unit_cost": 40_000}))
    r = await c.post(f"/inventory/{item['id']}/request-order", headers=d, json={"qty": 5})
    it = (await pr_row(J(r).get("number")) or {}).get("items", [{}])[0]
    check("no price given: its last cost", it.get("unit_price") == 40_000 and it.get("amount") == 200_000, str(it))
    r = await c.post(f"/inventory/{item['id']}/request-order", headers=d, json={"qty": 5, "unit_price": 38_000})
    it = (await pr_row(J(r).get("number")) or {}).get("items", [{}])[0]
    check("a price given: that one", it.get("unit_price") == 38_000 and it.get("amount") == 190_000, str(it))

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

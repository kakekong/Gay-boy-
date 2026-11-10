"""Editing a part: its code (a temporary one replaced) and its cost currency.

* Made with no code, a part takes the next stock code — a placeholder.
* The director replaces it with the real one. A prefixed code is stored in
  the one format; every document line with the old code takes the new one;
  the old code still finds the part.
* Never another part's code, in any spelling. Admin edits parts but not codes.
* Purchasing edits a part's price and code, at once — not the rest of it.
* The cost carries its currency and rate; rupiah needs no rate.
"""
import asyncio, os, sys, uuid
from datetime import date
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123",
    STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import httpx, logging; logging.disable(logging.INFO)
TAG = uuid.uuid4().hex[:4].upper()
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
    from app.models.inventory import InventoryItem
    from app.services.stock_sync import ItemIndex
    from sqlalchemy import select
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    adm = await login("admin@demo.local")
    pur = await login("purchasing@demo.local")

    async def item(iid):
        async with SessionLocal() as s:
            return await s.get(InventoryItem, uuid.UUID(iid))

    print("\n── a placeholder code ──")
    name = f"SPROCKET 80B24 {TAG}"
    r = await c.post("/inventory", headers=d, json={"name": name, "uom": "pcs", "unit_cost": 12.5,
                                                    "cost_currency": "CNY", "cost_fx_rate": 2250})
    iid = J(r)["id"]
    it = await item(iid)
    old = it.sku
    check("made with no code: the next stock code", r.status_code == 201 and old.startswith("STK-"), old)
    check("...its cost in yuan, with the rate", it.cost_currency == "CNY" and float(it.cost_fx_rate) == 2250,
          f"{it.cost_currency} {it.cost_fx_rate}")
    sup = J(await c.post("/purchasing/suppliers", headers=pur, json={"name": f"PT KODE {TAG}"}))["id"]
    po = J(await c.post("/purchasing/po", headers=d, json={
        "supplier_id": sup, "po_date": date.today().isoformat(), "currency": "CNY", "fx_rate": 2250,
        "items": [{"description": name, "sku": old, "qty": 4, "uom": "pcs", "unit_price": 12.5, "amount": 50}],
        "total": 50}))

    print("\n── the real code ──")
    real = f"Q{TAG}-77"
    r = await c.patch(f"/inventory/{iid}", headers=adm, json={"sku": real})
    check("admin can't change a code", r.status_code == 403, str(r.status_code))
    r = await c.patch(f"/inventory/{iid}", headers=d, json={"sku": real.lower()})
    got = J(r)
    it = await item(iid)
    check("the director replaces it — stored in the one format",
          r.status_code == 200 and it.sku == f"Q{TAG}-0077", f"{r.status_code} {it.sku}")
    check("...documents carrying the old code are named", any(x["number"] == po["number"] for x in got.get("documents", [])),
          str(got.get("documents"))[:160])
    po_now = J(await c.get(f"/purchasing/po/{po['id']}", headers=d))
    check("...and carry the new one", po_now["items"][0].get("sku") == f"Q{TAG}-0077", str(po_now["items"][0].get("sku")))
    async with SessionLocal() as s:
        idx = ItemIndex((await s.scalars(select(InventoryItem))).all())
    check("...the old code still finds the part", (idx.find(old, None) or it).id == it.id
          and idx.find(old, None) is not None)

    other = J(await c.post("/inventory", headers=d, json={"name": f"IDLER {TAG}", "uom": "pcs"}))["id"]
    r = await c.patch(f"/inventory/{other}", headers=d, json={"sku": f"q{TAG} 77"})
    check("never another part's code, in any spelling", r.status_code == 409, f"{r.status_code} {J(r)}"[:160])

    print("\n── the cost's currency ──")
    r = await c.patch(f"/inventory/{iid}", headers=adm, json={"cost_currency": "IDR", "unit_cost": 28_000})
    it = await item(iid)
    check("back to rupiah: no rate kept", r.status_code == 200 and it.cost_currency == "IDR"
          and it.cost_fx_rate is None and float(it.unit_cost) == 28_000, f"{it.cost_currency} {it.cost_fx_rate}")
    r = await c.patch(f"/inventory/{iid}", headers=adm, json={"cost_currency": "XYZ"})
    check("only a currency a PO is written in", r.status_code == 400, str(r.status_code))
    r = await c.patch(f"/inventory/{iid}", headers=adm, json={"cost_currency": "USD", "cost_fx_rate": 0})
    check("a rate is more than zero", r.status_code == 400, str(r.status_code))

    print("\n── purchasing keeps the price and code current ──")
    r = await c.patch(f"/inventory/{iid}", headers=pur, json={
        "sku": f"Q{TAG}-0078", "unit_cost": 13, "cost_currency": "CNY", "cost_fx_rate": 2300})
    it = await item(iid)
    check("purchasing changes the code and the price, at once",
          r.status_code == 200 and it.sku == f"Q{TAG}-0078" and float(it.unit_cost) == 13
          and it.cost_currency == "CNY" and float(it.cost_fx_rate) == 2300,
          f"{r.status_code} {it.sku} {it.unit_cost} {it.cost_currency} {J(r)}"[:200])
    po_now = J(await c.get(f"/purchasing/po/{po['id']}", headers=d))
    check("...and documents follow", po_now["items"][0].get("sku") == f"Q{TAG}-0078",
          str(po_now["items"][0].get("sku")))
    r = await c.patch(f"/inventory/{iid}", headers=pur, json={"name": "SOMETHING ELSE"})
    check("...but not its name or the rest", r.status_code == 403, str(r.status_code))
    # The edit form sends the whole record: unchanged fields pass.
    r = await c.patch(f"/inventory/{iid}", headers=pur, json={
        "name": it.name, "category": "", "uom": it.uom, "location": "", "notes": "",
        "reorder_point": 0, "reorder_qty": 0, "unit_cost": 14, "is_active": True})
    it = await item(iid)
    check("...the whole form sent back unchanged, with a new price: fine",
          r.status_code == 200 and float(it.unit_cost) == 14, f"{r.status_code} {J(r)}"[:160])

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

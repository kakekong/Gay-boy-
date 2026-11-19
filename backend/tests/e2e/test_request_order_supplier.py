"""Purchasing names the supplier when it requests an order.

* Purchasing's request without a supplier is refused, from the form and from
  an item's own Request order button; with one it goes in, and the request
  carries the supplier on each line.
* An unknown supplier is refused.
* Anyone else may still request without one (purchasing picks later), or
  name one if they know it.
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
def why(r):
    b = J(r)
    return str(b.get("detail") or (b.get("errors") or [{}])[0].get("message", "")) if isinstance(b, dict) else str(b)


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    from app.core.db import SessionLocal
    from app.models.inventory import InventoryItem
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t/api/v1", timeout=180)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d, pur, adm = (await login("director@demo.local"), await login("purchasing@demo.local"),
                   await login("admin@demo.local"))
    sup = J(await c.post("/purchasing/suppliers", headers=d, json={"name": f"PT PEMASOK {TAG}"}))
    async def pr_row(number):
        return next((x for x in J(await c.get("/purchasing/pr", headers=d)) if x["number"] == number), None)
    line = {"name": f"SHACKLE {TAG}", "qty": 4, "uom": "pcs"}

    print("\n── purchasing, from the form ──")
    r = await c.post("/inventory/request-order", headers=pur, json={"items": [line]})
    check("without a supplier: refused, and says to pick one",
          r.status_code == 400 and "supplier" in why(r).lower(), f"{r.status_code} {why(r)}")
    r = await c.post("/inventory/request-order", headers=pur,
                     json={"supplier_id": str(uuid.uuid4()), "items": [line]})
    check("an unknown supplier: refused", r.status_code == 400 and "unknown supplier" in why(r).lower(),
          f"{r.status_code} {why(r)}")
    r = await c.post("/inventory/request-order", headers=pur, json={"supplier_id": sup["id"], "items": [line]})
    check("with a supplier: goes in, and names it", r.status_code == 200 and J(r).get("supplier_name") == sup["name"],
          f"{r.status_code} {J(r)}"[:200])
    it = ((await pr_row(J(r).get("number"))) or {}).get("items", [{}])[0]
    check("...the request line carries the supplier",
          it.get("supplier_id") == sup["id"] and it.get("supplier_name") == sup["name"]
          and it.get("supplier_hint") == sup["name"], str(it)[:200])

    print("\n── purchasing, from an item's button ──")
    async with SessionLocal() as db:
        item = InventoryItem(sku=f"RQS-{TAG}", name=f"PIN {TAG}", uom="pcs", current_stock=0,
                             reorder_qty=10, unit_cost=5000, is_active=True)
        db.add(item); await db.commit(); iid = str(item.id)
    r = await c.post(f"/inventory/{iid}/request-order", headers=pur, json={"qty": 10})
    check("without a supplier: refused", r.status_code == 400, f"{r.status_code} {why(r)}")
    r = await c.post(f"/inventory/{iid}/request-order", headers=pur, json={"qty": 10, "supplier_id": sup["id"]})
    it = ((await pr_row(J(r).get("number"))) or {}).get("items", [{}])[0]
    check("with one: goes in, line names the supplier", r.status_code == 200 and it.get("supplier_id") == sup["id"],
          f"{r.status_code} {str(it)[:160]}")

    print("\n── anyone else ──")
    r = await c.post("/inventory/request-order", headers=adm, json={"items": [line]})
    check("admin may still request without a supplier", r.status_code == 200, f"{r.status_code} {why(r)}")
    r = await c.post(f"/inventory/{iid}/request-order", headers=d, json={"qty": 10})
    check("...the director too", r.status_code == 200, f"{r.status_code} {why(r)}")
    r = await c.post("/inventory/request-order", headers=adm, json={"supplier_id": sup["id"], "items": [line]})
    it = ((await pr_row(J(r).get("number"))) or {}).get("items", [{}])[0]
    check("...or name one when they know it", r.status_code == 200 and it.get("supplier_id") == sup["id"],
          f"{r.status_code} {str(it)[:160]}")

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

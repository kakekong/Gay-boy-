"""Inventory lists what is on the shelf first.

* Items with stock come before items with none, whatever their names.
* Within each group, by name.
* Filters and paging keep that order.
"""
import asyncio, os, sys, uuid
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123",
    STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import httpx, logging; logging.disable(logging.INFO)
TAG = "ISF" + uuid.uuid4().hex[:5].upper()
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
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t/api/v1", timeout=180)
    r = await c.post("/auth/login", json={"email": "director@demo.local", "password": "test-pass-123"})
    d = {"Authorization": f"Bearer {r.json()['access_token']}"}

    # Names chosen so alphabetical order alone would put the empty ones first.
    spec = [("A EMPTY", 0), ("B EMPTY", 0), ("C STOCKED", 5), ("D EMPTY", 0), ("E STOCKED", 2), ("F NEGATIVE", -1)]
    async with SessionLocal() as db:
        for name, qty in spec:
            db.add(InventoryItem(sku=f"{TAG}-{name[0]}", name=f"{name} {TAG}", uom="pcs",
                                 current_stock=qty, unit_cost=1000, is_active=True))
        await db.commit()

    rows = J(await c.get("/inventory", headers=d, params={"q": TAG}))["items"]
    names = [x["name"].split(" ")[0] + " " + x["name"].split(" ")[1] for x in rows]
    check("items with stock come first, by name",
          names[:2] == ["C STOCKED", "E STOCKED"], str(names))
    check("...then the rest, by name (none or below zero)",
          names[2:] == ["A EMPTY", "B EMPTY", "D EMPTY", "F NEGATIVE"], str(names))

    page1 = J(await c.get("/inventory", headers=d, params={"q": TAG, "limit": 2}))["items"]
    check("page one is the stock you can use",
          [x["name"].split(" ")[0] for x in page1] == ["C", "E"], str([x["name"] for x in page1]))

    whole = J(await c.get("/inventory", headers=d, params={"limit": 2000}))["items"]
    flags = [float(x["current_stock"]) > 0 for x in whole]
    first_empty = flags.index(False) if False in flags else len(flags)
    check("across the whole list, no stocked item comes after an empty one",
          all(not f for f in flags[first_empty:]), f"first empty at {first_empty}")

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

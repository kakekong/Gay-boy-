"""Inventory: on order until received, and never counted twice.

* An approved purchasing PO puts its quantity "on order" — shown beside the
  stock, not in it. Receiving moves it onto the shelf; part of it received
  leaves the rest on order, so a short delivery shows.
* A PO renamed after it moved stock keeps its movements: the old number's
  "ordered" stock used to stay behind, uncancelled, and receiving added the
  goods again — ordered +138, received +138 (PO-260924-001 → PO-LMJ-…-001).
* Doubles already on file are repaired: the old number's movements are
  matched back to the renamed order and its stock re-based on receipts.
"""
import asyncio, os, sys, uuid
from datetime import date
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
    from app.core.db import SessionLocal
    from app.models.inventory import InventoryItem
    from app.models.purchasing import SupplierPO
    from sqlalchemy import select
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d, pur = await login("director@demo.local"), await login("purchasing@demo.local")
    sup = J(await c.post("/purchasing/suppliers", headers=pur, json={"name": f"PT Stok {TAG}"}))["id"]

    def order(desc, qty, number=None):
        body = {"supplier_id": sup, "po_date": date.today().isoformat(),
                "items": [{"description": desc, "qty": qty, "uom": "pcs",
                           "unit_price": 10_000, "amount": qty * 10_000}], "total": qty * 10_000}
        if number:
            body["number"] = number
        return c.post("/purchasing/po", headers=d, json=body)

    async def item(name):
        rows = J(await c.get("/inventory", headers=d, params={"q": name, "limit": 20}))["items"]
        it = next((x for x in rows if x["name"].upper() == name.upper()), None)
        if not it:
            return None
        h = J(await c.get(f"/inventory/{it['id']}/history", headers=d))
        return it, h

    print("\n── on order until it arrives ──")
    A = f"Roller A {TAG}"
    po = J(await order(A, 10))
    it, h = await item(A)
    check("an approved PO puts it on order, not in stock",
          it["current_stock"] == 0 and it["on_order"] == 10, f"{it['current_stock']} {it['on_order']}")
    check("...the item page says which PO, not received yet",
          h["on_order"] and h["on_order"][0]["po_number"] == po["number"]
          and h["on_order"][0]["received"] == 0 and h["on_order"][0]["state"] == "on_order",
          str(h.get("on_order"))[:200])
    await c.post(f"/purchasing/po/{po['id']}/gr", headers=pur, json={"items": [{"description": A, "qty": 6}]})
    it, h = await item(A)
    check("six arrive: six on the shelf, four still on order",
          it["current_stock"] == 6 and it["on_order"] == 4
          and h["on_order"][0]["received"] == 6 and h["on_order"][0]["outstanding"] == 4,
          f"{it['current_stock']} {it['on_order']} {h.get('on_order')}"[:200])
    await c.post(f"/purchasing/po/{po['id']}/gr", headers=pur, json={"items": [{"description": A, "qty": 4}]})
    it, h = await item(A)
    check("the rest arrives: ten on the shelf, nothing on order",
          it["current_stock"] == 10 and it["on_order"] == 0 and not h["on_order"],
          f"{it['current_stock']} {it['on_order']}")

    print("\n── a PO renamed after it moved stock ──")
    from app.services.stock_sync import receive_purchase_order
    B = f"Roller B {TAG}"
    pob = J(await order(B, 8))
    async with SessionLocal() as s:     # the old rule: stock rose when ordered
        await receive_purchase_order(s, await s.get(SupplierPO, uuid.UUID(pob["id"])), move_stock=True)
        await s.commit()
    new_no = pob["number"].replace("PO-", f"PO-{TAG[:3]}-", 1)
    r = await c.patch(f"/purchasing/po/{pob['id']}", headers=d, json={"number": new_no})
    check("the director renames it", r.status_code == 200, f"{r.status_code} {J(r)}"[:150])
    await c.post(f"/purchasing/po/{pob['id']}/gr", headers=pur, json={"items": [{"description": B, "qty": 8}]})
    it, _ = await item(B)
    check("receiving it after the rename counts the goods once, not twice",
          it["current_stock"] == 8, str(it["current_stock"]))

    print("\n── a double already on file ──")
    C = f"Roller C {TAG}"
    poc = J(await order(C, 5, number=f"PO-{TAG}-777"))
    async with SessionLocal() as s:     # ordered under a number it no longer has
        p = await s.get(SupplierPO, uuid.UUID(poc["id"]))
        p.number = f"PO-OLD-{TAG}-777"
        await s.flush()
        await receive_purchase_order(s, p, move_stock=True)
        p.number = f"PO-{TAG}-777"
        await s.commit()
    from app.services.stock_sync import on_order as _oo  # noqa: F401
    await c.post(f"/purchasing/po/{poc['id']}/gr", headers=pur, json={"items": [{"description": C, "qty": 5}]})
    it, _ = await item(C)
    check("set up: five ordered under the old number, five received — counted ten",
          it["current_stock"] == 10, str(it["current_stock"]))
    from app.services.stock_sync import rebase_to_receipts, rename_po_references
    async with SessionLocal() as s:
        # The boot repair matches an orphan by its number's ending; this one's
        # old number doesn't end the same way, so it is named here directly.
        await rename_po_references(s, f"PO-OLD-{TAG}-777", f"PO-{TAG}-777")
        await rebase_to_receipts(s)
        await s.commit()
    it, h = await item(C)
    check("repaired: the shelf says five, what was received",
          it["current_stock"] == 5 and h["in_step"], f"{it['current_stock']} {h['in_step']}")

    print("\n── the boot repair finds a renamed order by its number ──")
    from app.services.stock_sync import repair_renamed_po_references
    D = f"Roller D {TAG}"
    pod = J(await order(D, 3, number=f"PO-{TAG}-888"))
    async with SessionLocal() as s:
        p = await s.get(SupplierPO, uuid.UUID(pod["id"]))
        p.number = f"PO-{TAG}-888"
        await receive_purchase_order(s, p, move_stock=True)
        p.number = f"PO-LMJ-{TAG}-888"          # renamed without its movements
        await s.commit()
        res = await repair_renamed_po_references(s)
        await s.commit()
    check("the old number's movements are matched to the renamed order",
          (f"PO-{TAG}-888", f"PO-LMJ-{TAG}-888") in [tuple(x) for x in res["repaired"]],
          str(res)[:200])

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

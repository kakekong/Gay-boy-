"""A supplier PO line's unit can be changed — link, meter, pcs, set, roll.

Spellings are folded onto the house list ("links" → link, "mtr" → meter); a
unit the list doesn't know is refused, because receiving books stock in it.
A line still carrying an odd unit it was saved with stays editable. The
change goes through the same approval as any PO edit, and the director's
preview shows the unit it replaces. Finance still can't change a unit.
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
    fin = await login("finance@demo.local")
    sup = J(await c.post("/purchasing/suppliers", headers=pur, json={"name": f"PT Rantai Satuan {TAG}"}))["id"]

    def line(desc, qty, uom, price):
        return {"description": desc, "qty": qty, "uom": uom, "unit_price": price, "amount": qty * price}

    po = J(await c.post("/purchasing/po", headers=d, json={
        "supplier_id": sup, "po_date": "2026-10-12",
        "items": [line(f"ROLLER CHAIN {TAG}", 40, "links", 50_000)], "total": 2_000_000}))
    check("a PO is raised with the chain in 'links'", bool(po.get("id")), str(po)[:200])
    got = J(await c.get(f"/purchasing/po/{po['id']}", headers=d))
    check("...stored in the house spelling, 'link'", got["items"][0]["uom"] == "link",
          str(got["items"][0]))

    print("\n── changing the unit ──")
    items = [dict(got["items"][0], uom="mtr", qty=10, unit_price=200_000, amount=2_000_000)]
    r = await c.patch(f"/purchasing/po/{po['id']}", headers=d, json={"items": items, "total": 2_000_000})
    got = J(await c.get(f"/purchasing/po/{po['id']}", headers=d))
    check("the director changes link → meter", r.status_code == 200
          and got["items"][0]["uom"] == "meter" and float(got["items"][0]["qty"]) == 10,
          f"{r.status_code} {got['items'][0]}")

    items = [dict(got["items"][0], uom="link", qty=40, unit_price=50_000, amount=2_000_000)]
    r = await c.patch(f"/purchasing/po/{po['id']}", headers=pur, json={"items": items, "total": 2_000_000})
    check("purchasing's change goes to the director", r.status_code in (200, 202), f"{r.status_code} {J(r)}")
    got = J(await c.get(f"/purchasing/po/{po['id']}", headers=d))
    check("...so the PO still says meter for now", got["items"][0]["uom"] == "meter", str(got["items"][0]))
    rows = J(await c.get("/approvals", headers=d))
    req = next((x for x in rows if x["target_type"] == "supplier_po" and x["target_id"] == po["id"]), None)
    pv = J(await c.get(f"/approvals/{req['id']}/preview", headers=d)) if req else {}
    li = (pv.get("items") or [{}])[0]
    check("...and the preview shows the unit it replaces",
          li.get("uom") == "link" and li.get("was_uom") == "meter", str(li))
    r = await c.post(f"/approvals/{req['id']}/approve", headers=d)
    got = J(await c.get(f"/purchasing/po/{po['id']}", headers=d))
    check("...approved, the PO is back in links", got["items"][0]["uom"] == "link", str(got["items"][0]))

    print("\n── what is refused, and what isn't ──")
    bad = [dict(got["items"][0], uom="kg")]
    r = await c.patch(f"/purchasing/po/{po['id']}", headers=d, json={"items": bad, "total": 2_000_000})
    check("a unit we don't count in is refused, naming the list", r.status_code == 400
          and "link" in str(J(r)) and "meter" in str(J(r)), f"{r.status_code} {str(J(r))[:160]}")

    from app.core.db import SessionLocal
    from app.models.purchasing import SupplierPO
    async with SessionLocal() as s:
        row = await s.get(SupplierPO, uuid.UUID(po["id"]))
        row.items = [dict(row.items[0], uom="kg")]
        await s.commit()
    got = J(await c.get(f"/purchasing/po/{po['id']}", headers=d))
    items = [dict(got["items"][0], unit_price=55_000, amount=40 * 55_000)]
    r = await c.patch(f"/purchasing/po/{po['id']}", headers=d, json={"items": items, "total": 40 * 55_000})
    check("an old line still saying 'kg' can still be edited", r.status_code == 200, f"{r.status_code} {J(r)}")

    items = [dict(got["items"][0], uom="pcs")]
    r = await c.patch(f"/purchasing/po/{po['id']}", headers=fin, json={"items": items})
    check("finance still can't change a unit — only a price", r.status_code == 403
          and "unit" in str(J(r)).lower(), f"{r.status_code} {str(J(r))[:160]}")

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

"""Who made a supplier PO, and how it was approved.

The PO page named only "Sales in charge" — the customer's sales rep — so an
order made from a purchasing account looked like the salesperson's, and
there was no way to tell whether it had been through the director.

* A PO made from purchasing shows purchasing as its maker, and the approval:
  waiting, then approved by whom and when.
* A PO the director makes shows the director, and that no approval was needed.
* Older POs get their maker from the approval request they filed.
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
    from app.models.purchasing import SupplierPO
    from sqlalchemy import update
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d, pur = await login("director@demo.local"), await login("purchasing@demo.local")
    me_pur = J(await c.get("/auth/me", headers=pur))
    me_d = J(await c.get("/auth/me", headers=d))
    sup = J(await c.post("/purchasing/suppliers", headers=pur, json={"name": f"PT Pembuat {TAG}"}))["id"]

    def order(h):
        return c.post("/purchasing/po", headers=h, json={
            "supplier_id": sup, "po_date": date.today().isoformat(),
            "items": [{"description": f"CHAIN {TAG}", "qty": 1, "uom": "pcs",
                       "unit_price": 1000, "amount": 1000}], "total": 1000})

    print("\n── made from purchasing ──")
    po = J(await order(pur))
    got = J(await c.get(f"/purchasing/po/{po['id']}", headers=d))
    check("the PO shows purchasing as its maker",
          (got.get("created_by") or {}).get("name") == me_pur.get("full_name")
          and got["created_by"]["role"] == "purchasing", str(got.get("created_by")))
    check("...waiting in the director's Approvals",
          (got.get("approval") or {}).get("status") == "pending", str(got.get("approval")))
    rows = J(await c.get("/approvals", headers=d))
    rows = rows if isinstance(rows, list) else rows.get("items", [])
    req = next((x for x in rows if x.get("target_id") == po["id"]), None)
    check("...and it is in the director's inbox", req is not None)
    await c.post(f"/approvals/{req['id']}/approve", headers=d)
    got = J(await c.get(f"/purchasing/po/{po['id']}", headers=d))
    check("approved: by the director, with when",
          got["approval"]["status"] == "approved" and got["approval"]["decided_by"] == me_d.get("full_name")
          and got["approval"]["decided_at"], str(got.get("approval")))

    print("\n── made by the director ──")
    po2 = J(await order(d))
    got = J(await c.get(f"/purchasing/po/{po2['id']}", headers=d))
    check("the director's own PO shows the director, and no approval needed",
          got["created_by"]["role"] == "director" and got.get("approval") is None and got["status"] == "open",
          f"{got.get('created_by')} {got.get('approval')} {got.get('status')}")

    print("\n── older POs ──")
    async with SessionLocal() as s:
        await s.execute(update(SupplierPO).where(SupplierPO.id == uuid.UUID(po["id"])).values(created_by=None))
        await s.commit()
    await ensure_schema()
    async with SessionLocal() as s:
        row = await s.get(SupplierPO, uuid.UUID(po["id"]))
    check("an older PO gets its maker from the approval request it filed",
          str(row.created_by) == me_pur.get("id"), str(row.created_by))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

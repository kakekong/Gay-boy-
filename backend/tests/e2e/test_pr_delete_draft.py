"""The director can delete a draft price request.

A draft nobody sent on — nobody priced it, nothing was made from it — can be
cleared out by the director. It leaves every list and lookup; the row is
kept and the delete is in the audit log. Anything past draft has a trail and
stays; nobody but the director may delete.
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
    from app.core.db import SessionLocal
    from app.models.audit import AuditLog
    from app.models.price_request import PriceRequest
    from sqlalchemy import select
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d, s1, mgr = [await login(f"{x}@demo.local") for x in ("director", "sales1", "manager")]

    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Draf {TAG}", "industry": "mining"}))["id"]
    def new_pr():
        return c.post("/price-requests", headers=s1, json={
            "customer_id": cust, "items": [{"description": f"CHAIN {TAG}", "qty": 1, "uom": "pcs"}]})
    draft = J(await new_pr())
    sent = J(await new_pr())
    await c.post(f"/price-requests/{sent['id']}/submit", headers=s1)

    async def listed(pid):
        rows = J(await c.get("/price-requests", headers=d))
        rows = rows if isinstance(rows, list) else rows.get("items", rows.get("data", []))
        return any(r["id"] == pid for r in rows)

    check("the director sees the draft", await listed(draft["id"]))
    r = await c.delete(f"/price-requests/{draft['id']}", headers=s1)
    check("the sales rep who wrote it can't delete it", r.status_code == 403, str(r.status_code))
    r = await c.delete(f"/price-requests/{draft['id']}", headers=mgr)
    check("...nor a manager", r.status_code == 403, str(r.status_code))
    r = await c.delete(f"/price-requests/{sent['id']}", headers=d)
    check("one already sent to purchasing can't be deleted", r.status_code == 409
          and "draft" in str(J(r)).lower(), f"{r.status_code} {J(r)}"[:200])

    r = await c.delete(f"/price-requests/{draft['id']}", headers=d)
    check("the director deletes the draft", r.status_code == 200, f"{r.status_code} {J(r)}"[:200])
    check("...it's gone from the list", not await listed(draft["id"]))
    r = await c.get(f"/price-requests/{draft['id']}", headers=d)
    check("...and can't be opened", r.status_code == 404, str(r.status_code))
    r = await c.delete(f"/price-requests/{draft['id']}", headers=d)
    check("...deleting it again says so", r.status_code == 404, str(r.status_code))
    async with SessionLocal() as s:
        row = await s.get(PriceRequest, uuid.UUID(draft["id"]))
        log = await s.scalar(select(AuditLog).where(AuditLog.entity == "price_request",
                                                    AuditLog.entity_id == row.id,
                                                    AuditLog.action == "delete"))
    check("the row is kept, marked deleted", row is not None and row.is_deleted and row.deleted_at)
    check("...and the audit log says who", log is not None and log.actor_id is not None)

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

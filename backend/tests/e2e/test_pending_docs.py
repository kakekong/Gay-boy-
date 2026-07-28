"""Delivery proof leaves the approvals doc-queue once the project closes."""
import asyncio, os, sys, io
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123", STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import httpx, logging; logging.disable(logging.INFO)
PASS, FAIL = [], []
def check(n,c,d=""):
    (PASS if c else FAIL).append(n); print(("  PASS " if c else "  FAIL ")+n+(f"  [{d}]" if d and not c else ""))
async def login(c,e):
    r=await c.post("/auth/login",json={"email":e,"password":"test-pass-123"}); return {"Authorization":f"Bearer {r.json()['access_token']}"}

async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.core.db import SessionLocal
    from app.models.crm import Customer
    from app.models.operation import DeliveryOrder, Project
    from app.models.attachment import Attachment
    from sqlalchemy import select
    from datetime import date
    from app.main import app
    c=httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://t/api/v1",timeout=40)
    d=await login(c,"director@demo.local")

    # A project still in-flight with an unverified delivery order + uploaded proof.
    async with SessionLocal() as db:
        cust=Customer(company_name="PT DO Test", industry="mining"); db.add(cust); await db.flush()
        proj=Project(code="PRJ-DOTEST-1", customer_id=cust.id, status="packaging"); db.add(proj); await db.flush()
        do=DeliveryOrder(project_id=proj.id, number="DO-TEST-9", status="pending")  # verified_at is None
        db.add(do); await db.flush()
        db.add(Attachment(owner_type="delivery_order", owner_id=do.id, filename="pod.pdf",
                          content_type="application/pdf", size=1, storage_path="/x"))
        await db.commit()
        proj_id=str(proj.id)

    def has_do(items):
        return any(x.get("kind")=="delivery_proof" and "DO-TEST-9" in x.get("title","") for x in items)

    # In-flight → the proof SHOULD appear
    items=(await c.get("/approvals/pending-documents",headers=d)).json()
    check("proof shown while project in-flight (packaging)", has_do(items), "not shown")

    # Close the project (simulate the paid->closed auto-advance) — proof should drop
    async with SessionLocal() as db:
        p=await db.get(Project, proj_id); p.status="closed"; await db.commit()
    items=(await c.get("/approvals/pending-documents",headers=d)).json()
    check("proof GONE after project closed", not has_do(items), "still shown after close")

    # Also gone for 'delivered' and 'paid'
    for st in ("delivered","paid"):
        async with SessionLocal() as db:
            p=await db.get(Project, proj_id); p.status=st; await db.commit()
        items=(await c.get("/approvals/pending-documents",headers=d)).json()
        check(f"proof gone when project '{st}'", not has_do(items), f"shown at {st}")

    # Back in-flight → reappears (proves it's status-driven, not deleted)
    async with SessionLocal() as db:
        p=await db.get(Project, proj_id); p.status="qc"; await db.commit()
    items=(await c.get("/approvals/pending-documents",headers=d)).json()
    check("proof reappears when project active again", has_do(items), "not shown at qc")

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL: print("FAILED:",FAIL); sys.exit(1)
asyncio.run(main())

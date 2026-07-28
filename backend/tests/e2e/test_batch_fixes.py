"""Remaining-bug batch: stage-task cleanup, approval gates, scoping, tax period."""
import asyncio, os, sys, io, uuid
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123", STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import httpx, logging; logging.disable(logging.INFO)
PASS, FAIL = [], []
def check(n,c,d=""):
    (PASS if c else FAIL).append(n); print(("  PASS " if c else "  FAIL ")+n+(f"  [{d}]" if d and not c else ""))
def J(r):
    try: return r.json()
    except: return {"_":r.text[:150]}
async def login(c,e):
    r=await c.post("/auth/login",json={"email":e,"password":"test-pass-123"})
    return {"Authorization":f"Bearer {r.json()['access_token']}"}

async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.core.db import SessionLocal
    from app.models.crm import Customer, Reminder
    from app.models.operation import Project
    from sqlalchemy import select
    from app.main import app
    c=httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://t/api/v1",timeout=40)
    d=await login(c,"director@demo.local"); s1=await login(c,"sales1@demo.local"); s2=await login(c,"sales2@demo.local")
    tag=uuid.uuid4().hex[:6]

    # ---- 1. Stage tasks from a past stage get retired on stage move ----
    cust=J(await c.post("/customers",headers=s1,json={"company_name":f"PT Stage {tag}","industry":"mining"}))["id"]
    # give a lead-stage task a due date so it would otherwise nag forever
    tasks=J(await c.get(f"/customers/{cust}/stage-tasks",headers=s1))["items"]
    key=tasks[0]["key"]
    await c.patch(f"/customers/{cust}/stage-tasks/{key}",headers=s1,json={"due_at":"2026-01-01T09:00:00"})
    # move the deal to closed_lost (which has NO playbook — the worst case)
    r=await c.patch(f"/customers/{cust}",headers=d,json={"stage":"closed_lost"})
    check("stage move to closed_lost ok", r.status_code==200, str(r.status_code))
    async with SessionLocal() as db:
        left=(await db.scalars(select(Reminder).where(
            Reminder.customer_id==cust, Reminder.kind.like("stage:%"),
            Reminder.status=="pending"))).all()
    check("prior-stage tasks retired on close", len(left)==0,
          f"{len(left)} still pending: {[r.kind for r in left]}")

    # ---- 2. Manager can no longer approve a DRAFT quotation ----
    cust2=J(await c.post("/customers",headers=s1,json={"company_name":f"PT Draft {tag}","industry":"mining"}))["id"]
    pr=J(await c.post("/price-requests",headers=s1,json={"customer_id":cust2,"items":[{"description":"X","qty":1,"uom":"pcs"}]}))["id"]
    await c.post(f"/price-requests/{pr}/submit",headers=s1)
    await c.post(f"/price-requests/{pr}/price",headers=d,json={"items":[{"line_no":1,"cost_price":100,"basis":"unit"}]})
    await c.post(f"/price-requests/{pr}/approve",headers=d,json={"items":[{"line_no":1,"sell_price":200,"basis":"unit"}]})
    q=J(await c.post(f"/quotations/from-price-request/{pr}",headers=s1))["id"]
    mgr=await login(c,"manager@demo.local")
    r=await c.post(f"/quotations/{q}/approve",headers=mgr,json={"notes":""})
    check("approving a DRAFT quote is blocked", r.status_code>=400, f"HTTP{r.status_code}")
    # normal path still works
    await c.post(f"/quotations/{q}/submit",headers=s1)
    r=await c.post(f"/quotations/{q}/approve",headers=d,json={"notes":""})
    check("submitted quote still approves", r.status_code==200, f"HTTP{r.status_code}")

    # ---- 3. Revise blocked while a mark-won request is pending ----
    await c.post(f"/quotations/{q}/won",headers=s1)     # files a request
    r=await c.post(f"/quotations/{q}/revise",headers=s1)
    check("revise blocked while mark-won pending", r.status_code==409, f"HTTP{r.status_code}")

    # ---- 4. A reminder from another customer can't be closed via a quote ----
    other=J(await c.post("/customers",headers=s1,json={"company_name":f"PT Other {tag}","industry":"mining"}))["id"]
    ot=J(await c.get(f"/customers/{other}/stage-tasks",headers=s1))["items"]
    async with SessionLocal() as db:
        rem=await db.scalar(select(Reminder).where(Reminder.customer_id==other,
                                                   Reminder.kind.like("stage:%")))
        rid=str(rem.id) if rem else None
    if rid:
        r=await c.patch(f"/quotations/{q}/reminders/{rid}/done",headers=s1)
        check("cross-customer reminder close blocked", r.status_code==404, f"HTTP{r.status_code}")

    # ---- 5. Tax report honours its period ----
    r=await c.get("/finance/tax/report",headers=d,params={"period":"2026-07"})
    b=J(r)
    check("tax report accepts YYYY-MM", r.status_code==200 and b.get("from"), str(b)[:120])
    r=await c.get("/finance/tax/report",headers=d,params={"period":"nonsense"})
    check("tax report rejects a bad period", r.status_code==400, f"HTTP{r.status_code}")

    # ---- 6. Deleted project drops out of queues ----
    async with SessionLocal() as db:
        cu=Customer(company_name=f"PT Del {tag}", industry="mining"); db.add(cu); await db.flush()
        pj=Project(code=f"PRJ-DEL-{tag}", customer_id=cu.id, status="production",
                   is_deleted=True)
        db.add(pj); await db.flush()
        from app.models.operation import WorkOrder
        db.add(WorkOrder(project_id=pj.id, code=f"WO-DEL-{tag}", stage="receiving"))
        await db.commit()
    wos=J(await c.get("/operation/work-orders",headers=d,params={"completed":"false"}))
    rows=wos if isinstance(wos,list) else wos.get("items",[])
    check("deleted project's work order hidden from the board",
          not any(f"WO-DEL-{tag}"==w.get("code") for w in rows), "still listed")

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL: print("FAILED:",FAIL); sys.exit(1)
asyncio.run(main())

"""The delivery work order comes after the delivery order — and only finance
releases a delivery order.

The delivery WO is the goods physically going out; the delivery order is the
document they go out under, which only prints once finance has released it.
So a delivery WO — filed new, moved into delivery, or completed — waits until
a delivery order on the job exists AND is released.

Pinned here: filing a delivery WO with no delivery order is refused and says
to raise one; with one raised but unreleased it is refused and says finance
has to release it; moving another WO into delivery is refused the same way;
once finance releases it all three go through; a delivery WO that predates
the rule cannot be completed on a job with no released delivery order; and
the finance-only release holds against the director on both routes.
"""
import asyncio, os, sys, uuid
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123",
    STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import httpx, logging; logging.disable(logging.INFO)
TAG = uuid.uuid4().hex[:6].upper()
PASS, FAIL = [], []
def check(n, c, d=""):
    (PASS if c else FAIL).append(n); print(("  PASS " if c else "  FAIL ")+n+(f"  [{d}]" if d and not c else ""))
def J(r):
    try: return r.json()
    except Exception: return {"_": r.text[:200]}
def why(r):
    b = J(r)
    if not isinstance(b, dict):
        return str(b)[:200]
    return str(b.get("detail") or (b.get("errors") or [{}])[0].get("message", ""))


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    from app.core.db import SessionLocal
    from app.models.operation import Project, WorkOrder
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)

    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    adm = await login("admin@demo.local")
    fin = await login("finance@demo.local")
    s1 = await login("sales1@demo.local")

    async def a_job(tag):
        cust = J(await c.post("/customers", headers=s1, json={
            "company_name": f"PT Antar {tag}", "industry": "mining"}))["id"]
        pr = J(await c.post("/price-requests", headers=s1, json={
            "customer_id": cust,
            "items": [{"description": f"CHAIN {tag}", "qty": 4, "uom": "pcs"}]}))["id"]
        await c.post(f"/price-requests/{pr}/submit", headers=s1)
        await c.post(f"/price-requests/{pr}/price", headers=d, json={
            "items": [{"line_no": 1, "cost_price": 500_000, "basis": "unit"}]})
        await c.post(f"/price-requests/{pr}/approve", headers=d, json={
            "items": [{"line_no": 1, "sell_price": 1_000_000, "basis": "unit"}]})
        q = J(await c.post(f"/quotations/from-price-request/{pr}", headers=s1))
        await c.post(f"/quotations/{q['id']}/submit", headers=s1)
        await c.post(f"/quotations/{q['id']}/approve", headers=d, json={"notes": ""})
        cpo = J(await c.post("/customer-pos", headers=s1, json={
            "customer_id": cust, "quotation_id": q["id"], "number": f"PO-ANT-{tag}",
            "items": [{"description": f"CHAIN {tag}", "qty": 4, "unit_price": 1_000_000}],
            "is_downpayment": False}))["id"]
        await c.post(f"/quotations/{q['id']}/won", headers=d)
        proj = J(await c.post(f"/customer-pos/{cpo}/approve", headers=d,
                              json={"notes": ""}))["project_id"]
        await c.post(f"/operation/projects/{proj}/qc", headers=adm, json={"decision": "pass"})
        # Packaging done — the delivery WO's own stage gate is met, so the
        # only thing standing in its way is the delivery order.
        async with SessionLocal() as db:
            p = await db.get(Project, uuid.UUID(proj))
            p.status = "packaging"
            await db.commit()
        return proj

    proj = await a_job(TAG)

    async def delivery_wo(code):
        return await c.post(f"/operation/projects/{proj}/work-orders", headers=adm,
                            json={"code": code, "stage": "delivery"})

    print("\n── no delivery order yet ──")
    r = await delivery_wo(f"WO-DLV-{TAG}-1")
    check("a delivery work order is refused while there is no delivery order",
          r.status_code == 409, f"{r.status_code} {why(r)}")
    check("...and says to raise the delivery order first",
          "raise the delivery order" in why(r).lower(), why(r)[:160])

    pk = J(await c.post(f"/operation/projects/{proj}/work-orders", headers=adm,
                        json={"code": f"WO-PK-{TAG}", "stage": "packaging"}))
    check("other stages are not affected — a packaging WO files as before",
          bool(pk.get("id")), str(pk)[:160])

    print("\n── raised, not yet released ──")
    r = await c.post(f"/operation/projects/{proj}/delivery-order", headers=adm,
                     json={"items": [{"description": f"CHAIN {TAG}", "qty": 4, "uom": "pcs"}]})
    check("admin raises the delivery order", r.status_code == 201, f"{r.status_code} {why(r)}")
    do_id = J(r)["delivery_order"]["id"]
    r = await delivery_wo(f"WO-DLV-{TAG}-2")
    check("a raised but unreleased delivery order still holds the WO back",
          r.status_code == 409 and "finance" in why(r).lower(), f"{r.status_code} {why(r)}")
    r = await c.patch(f"/operation/work-orders/{pk['id']}", headers=adm,
                      params={"stage": "delivery"})
    check("...and moving another WO into delivery is refused the same way",
          r.status_code == 409, f"{r.status_code} {why(r)}")

    print("\n── only finance releases it ──")
    r = await c.post(f"/operation/deliveries/{do_id}/approve", headers=d)
    check("the director cannot release a delivery order", r.status_code == 403,
          str(r.status_code))
    r = await c.post(f"/operation/deliveries/{do_id}/approve", headers=adm)
    check("...nor can admin", r.status_code == 403, str(r.status_code))
    reqs = [x for x in J(await c.get("/approvals", headers=d))
            if x.get("target_id") == do_id]
    check("it is not in the director's approvals inbox", not reqs, str(reqs)[:120])
    freqs = [x for x in J(await c.get("/approvals", headers=fin))
             if x.get("target_id") == do_id]
    check("...it is in finance's", len(freqs) == 1, str(len(freqs)))
    if freqs:
        r = await c.post(f"/approvals/{freqs[0]['id']}/approve", headers=d)
        check("the director is refused through the approvals API too",
              r.status_code == 403, f"{r.status_code} {why(r)}")
    r = await c.post(f"/operation/deliveries/{do_id}/approve", headers=fin)
    check("finance releases it", r.status_code == 200, f"{r.status_code} {why(r)}")

    print("\n── released: the delivery WO can go ──")
    r = await delivery_wo(f"WO-DLV-{TAG}-3")
    check("the delivery work order files now", r.status_code == 201, f"{r.status_code} {why(r)}")
    wo = J(r)
    r = await c.patch(f"/operation/work-orders/{pk['id']}", headers=adm,
                      params={"stage": "delivery"})
    check("...and a WO can be moved into delivery", r.status_code == 200,
          f"{r.status_code} {why(r)}")
    r = await c.patch(f"/operation/work-orders/{wo['id']}", headers=adm,
                      params={"completed": True})
    check("...and completed", r.status_code == 200 and J(r).get("completed_at"),
          f"{r.status_code} {why(r)}")

    print("\n── a delivery WO from before the rule ──")
    proj2 = await a_job(f"B{TAG}")
    async with SessionLocal() as db:
        old = WorkOrder(project_id=uuid.UUID(proj2), code=f"WO-OLD-{TAG}", stage="delivery")
        db.add(old)
        await db.commit()
        old_id = old.id
    r = await c.patch(f"/operation/work-orders/{old_id}", headers=adm,
                      params={"completed": True})
    check("it cannot be completed on a job with no released delivery order",
          r.status_code == 409, f"{r.status_code} {why(r)}")
    r = await c.patch(f"/operation/work-orders/{old_id}", headers=adm,
                      params={"notes": "truck booked"})
    check("...but its notes can still be edited", r.status_code == 200,
          f"{r.status_code} {why(r)}")

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        sys.exit(1)

asyncio.run(main())

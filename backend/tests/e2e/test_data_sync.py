"""Older records and side paths brought in line with today's rules.

An audit of where the system's newer rules depend on a record that older
rows, or a side path, never wrote:

* pending Mark-won / delivery-order requests still addressed to the director
  after both moved to finance — the delivery-order ones decidable by nobody;
* a PO set to Received (or Closed) by hand, and the purchasing "Receive
  goods" form — neither put stock in nor made the supplier owed;
* an approved cancellation that left the order's goods on the shelf;
* a delivery order whose lines were edited, or which was renamed, leaving its
  stock movement out of step; and the older endpoint that raised a bare DO;
* orders marked received, and delivery orders that never took stock out,
  fixed once; and a read-only report of what a person still has to decide.
"""
import asyncio, os, sys, uuid
from datetime import datetime, UTC
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
    from app.models.approval import ApprovalRequest
    from app.models.operation import DeliveryOrder, Project
    from app.models.purchasing import SupplierPO
    from sqlalchemy import select, text
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)

    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    adm = await login("admin@demo.local")
    fin = await login("finance@demo.local")
    s1 = await login("sales1@demo.local")
    pur = await login("purchasing@demo.local")

    async def stock(name):
        inv = J(await c.get("/inventory", headers=d, params={"q": name}))
        it = next((x for x in inv["items"] if x["name"] == name), None)
        return float(it["current_stock"]) if it else None

    async def payable(po_id):
        async with SessionLocal() as db:
            p = await db.get(SupplierPO, uuid.UUID(po_id))
            return float(p.payable_amount or 0), p.status

    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Sinkron {TAG}", "industry": "mining"}))["id"]
    pr = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust, "items": [{"description": f"GEAR {TAG}", "qty": 10, "uom": "pcs"}]}))["id"]
    await c.post(f"/price-requests/{pr}/submit", headers=s1)
    await c.post(f"/price-requests/{pr}/price", headers=d, json={
        "items": [{"line_no": 1, "cost_price": 10_000, "basis": "unit"}]})
    await c.post(f"/price-requests/{pr}/approve", headers=d, json={
        "items": [{"line_no": 1, "sell_price": 20_000, "basis": "unit"}]})
    q = J(await c.post(f"/quotations/from-price-request/{pr}", headers=s1))
    await c.post(f"/quotations/{q['id']}/submit", headers=s1)
    await c.post(f"/quotations/{q['id']}/approve", headers=d, json={"notes": ""})
    cpo = J(await c.post("/customer-pos", headers=s1, json={
        "customer_id": cust, "quotation_id": q["id"], "number": f"CPO-{TAG}",
        "items": [{"description": f"GEAR {TAG}", "qty": 10, "uom": "pcs", "unit_price": 20_000}],
        "is_downpayment": False}))
    await c.post(f"/quotations/{q['id']}/won", headers=d)
    proj = J(await c.post(f"/customer-pos/{cpo['id']}/approve", headers=d, json={"notes": ""}))["project_id"]
    sup = J(await c.post("/purchasing/suppliers", headers=pur, json={"name": f"CV Sinkron {TAG}"}))["id"]

    async def a_po(desc, qty, price, project=True):
        body = {"supplier_id": sup, "po_date": "2026-09-01",
                "items": [{"description": desc, "qty": qty, "uom": "pcs", "unit_price": price}]}
        if project:
            body["project_id"] = proj
        return J(await c.post("/purchasing/po", headers=d, json=body))

    # ══ stuck approvals ══════════════════════════════════════════════════
    print("\n── pending requests addressed to the old desk ──")
    from app.models.user import User
    async with SessionLocal() as db:
        who = await db.scalar(select(User.id).where(User.email == "admin@demo.local"))
        stale = ApprovalRequest(target_type="delivery_order", target_id=uuid.uuid4(),
                                requested_by=who, required_role="director",
                                reason=f"old DO {TAG}", payload={}, status="pending")
        db.add(stale); await db.commit(); stale_id = stale.id
    await ensure_schema()
    async with SessionLocal() as db:
        got = await db.get(ApprovalRequest, stale_id)
        check("a delivery-order request left with the director is re-addressed to finance",
              got.required_role == "finance", got.required_role)
        await db.delete(got); await db.commit()

    # ══ a PO set to Received by hand ═════════════════════════════════════
    print("\n── setting a PO to Received by hand ──")
    A = f"SHAFT {TAG}"
    po = await a_po(A, 5, 100_000, project=False)
    r = await c.patch(f"/purchasing/po/{po['id']}", headers=d, json={"status": "received"})
    check("the director marks an order with no project as received", r.status_code == 200,
          f"{r.status_code} {why(r)}")
    check("...its goods are in stock", await stock(A) == 5, str(await stock(A)))
    owed, st = await payable(po["id"])
    check("...and the supplier is owed for them", owed == 500_000, str(owed))

    # ══ the purchasing "Receive goods" form ══════════════════════════════
    print("\n── the purchasing Receive goods form ──")
    B = f"BEARING {TAG}"
    po2 = await a_po(B, 8, 50_000)
    r = await c.post(f"/purchasing/po/{po2['id']}/gr", headers=pur, json={
        "received_at": "2026-09-20", "items": [{"description": B, "qty": 3}]})
    check("the form records a receipt", r.status_code == 201, f"{r.status_code} {why(r)}")
    check("...three into stock", await stock(B) == 3, str(await stock(B)))
    r = await c.post(f"/purchasing/po/{po2['id']}/gr", headers=pur, json={
        "items": [{"description": B, "qty": 5}]})
    check("...a second delivery adds on top", await stock(B) == 8, str(await stock(B)))
    owed, _ = await payable(po2["id"])
    check("...and all eight are owed", owed == 400_000, str(owed))
    r = await c.post(f"/purchasing/po/{po2['id']}/gr", headers=pur, json={
        "items": [{"description": "NOT ON THE ORDER", "qty": 1}]})
    check("a line not on the order is refused", r.status_code == 400, str(r.status_code))

    # ══ an approved cancellation ═════════════════════════════════════════
    print("\n── a cancellation approved from the inbox ──")
    C = f"CHAIN {TAG}"
    po3 = await a_po(C, 4, 10_000, project=False)
    await c.patch(f"/purchasing/po/{po3['id']}", headers=d, json={"status": "received"})
    check("four received", await stock(C) == 4, str(await stock(C)))
    r = await c.patch(f"/purchasing/po/{po3['id']}", headers=pur, json={"status": "cancelled"})
    reqs = [a for a in J(await c.get("/approvals", headers=d)) if a.get("target_id") == po3["id"]]
    check("purchasing's cancellation goes to the director", len(reqs) == 1, str(len(reqs)))
    if reqs:
        await c.post(f"/approvals/{reqs[0]['id']}/approve", headers=d)
    check("...and approving it takes the goods back off the shelf", await stock(C) == 0,
          str(await stock(C)))

    # ══ delivery orders ══════════════════════════════════════════════════
    print("\n── delivery orders stay in step with stock ──")
    async with SessionLocal() as db:
        p = await db.get(Project, uuid.UUID(proj))
        p.status = "packaging"; p.qc_passed_at = datetime.now(UTC); p.qc_decision = "pass"
        await db.commit()
    r = await c.post(f"/operation/projects/{proj}/delivery-order", headers=adm,
                     json={"items": [{"description": B, "qty": 2, "uom": "pcs"}]})
    do = J(r)["delivery_order"]
    check("a delivery order for two takes two out", await stock(B) == 6, str(await stock(B)))
    r = await c.patch(f"/operation/deliveries/{do['id']}", headers=adm,
                      json={"items": [{"description": B, "qty": 5, "uom": "pcs"}]})
    check("editing it to five takes five out, not seven",
          r.status_code == 200 and await stock(B) == 3, f"{r.status_code} {await stock(B)}")
    new_no = f"DO-RENAMED-{TAG}"
    await c.patch(f"/operation/deliveries/{do['id']}", headers=adm, json={"number": new_no})
    r = await c.delete(f"/operation/deliveries/{do['id']}", headers=adm)
    check("renamed then withdrawn, its goods still come back",
          r.status_code == 204 and await stock(B) == 8, f"{r.status_code} {await stock(B)}")

    r = await c.post(f"/operation/projects/{proj}/delivery", headers=adm,
                     json={"number": f"DO-OLD-{TAG}"})
    check("the older endpoint raises a delivery order", r.status_code == 201,
          f"{r.status_code} {why(r)}")
    old_id = J(r)["id"]
    async with SessionLocal() as db:
        n = await db.scalar(select(ApprovalRequest).where(
            ApprovalRequest.target_type == "delivery_order",
            ApprovalRequest.target_id == uuid.UUID(old_id)))
        check("...which now files its approval like every other", n is not None, str(n))

    print("\n── delivery orders that never took stock out ──")
    D = f"PULLEY {TAG}"
    po4 = await a_po(D, 6, 1_000)
    await c.patch(f"/purchasing/po/{po4['id']}", headers=d, json={"status": "received"})
    async with SessionLocal() as db:
        db.add(DeliveryOrder(project_id=uuid.UUID(proj), number=f"DO-LEGACY-{TAG}",
                             status="pending", items=[{"description": D, "qty": 4, "uom": "pcs"}]))
        await db.commit()
    check("a legacy delivery order sits there with nothing taken out", await stock(D) == 6,
          str(await stock(D)))
    from app.services.receiving import sync_delivery_stock
    async with SessionLocal() as db:
        await sync_delivery_stock(db); await db.commit()
    check("...until the sync takes its four out", await stock(D) == 2, str(await stock(D)))
    async with SessionLocal() as db:
        await sync_delivery_stock(db); await db.commit()
    check("...once", await stock(D) == 2, str(await stock(D)))

    print("\n── orders marked received before this ──")
    E = f"COLLAR {TAG}"
    po5 = await a_po(E, 7, 3_000, project=False)
    async with SessionLocal() as db:
        p = await db.get(SupplierPO, uuid.UUID(po5["id"])); p.status = "received"; await db.commit()
    from app.services.receiving import sync_orders_marked_received
    async with SessionLocal() as db:
        await sync_orders_marked_received(db); await db.commit()
    owed, _ = await payable(po5["id"])
    check("an order marked received with no receipt is received by the sync",
          await stock(E) == 7 and owed == 21_000, f"{await stock(E)} {owed}")

    # ══ the report ═══════════════════════════════════════════════════════
    print("\n── the data health report ──")
    r = await c.get("/maintenance/data-health", headers=d)
    check("the director can read it", r.status_code == 200, f"{r.status_code} {why(r)}")
    keys = {x["key"] for x in J(r).get("checks", [])}
    check("...covering duplicates, rates, receiving, stock and invoicing",
          {"duplicate_customer_pos", "duplicate_invoices", "duplicate_work_orders",
           "po_without_rate", "unreceived_past_receiving", "open_po_without_project",
           "negative_stock", "stock_drift", "invoiced_not_moved"} <= keys, str(keys))
    r = await c.get("/maintenance/data-health", headers=fin)
    check("finance cannot", r.status_code == 403, str(r.status_code))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        sys.exit(1)

asyncio.run(main())

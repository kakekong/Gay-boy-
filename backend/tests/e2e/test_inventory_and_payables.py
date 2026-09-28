"""Inventory that can be traced, priced in its own currency, and paid for.

* **Every stock item has its own page** — `/inventory/{id}/history`: the item,
  and every movement oldest-to-newest with the balance after it, each naming
  (and linking) the document that caused it.
* **A price keeps its currency.** A part bought in RMB is priced in RMB, with
  its rupiah equivalent at the order's rate beside it — never the RMB figure
  labelled as rupiah. The stock value total is in rupiah.
* **Completing the receiving work order receives the goods.** An order for 200
  ticked off as received put nothing on the shelf, so a delivery order that
  shipped 100 had nothing to come out of. Completing it now receives every
  line nobody counted, at its ordered quantity — and makes it owed.
* **Every purchasing PO shows under utang usaha** — received or not — with
  what was ordered, received (owed), paid; a payment can go ahead of delivery
  up to the order's value. Orders received before receiving posted payables
  are brought in from their goods receipts, once.
"""
import asyncio, os, sys, uuid
from datetime import date
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
    from app.models.operation import Project
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

    PART = f"ROLLER CHAIN RS80 {TAG}"
    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Gudang {TAG}", "industry": "mining"}))["id"]
    pr = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [{"description": PART, "qty": 100, "uom": "meter"}]}))["id"]
    await c.post(f"/price-requests/{pr}/submit", headers=s1)
    await c.post(f"/price-requests/{pr}/price", headers=d, json={
        "items": [{"line_no": 1, "cost_price": 20_000, "basis": "unit"}]})
    await c.post(f"/price-requests/{pr}/approve", headers=d, json={
        "items": [{"line_no": 1, "sell_price": 40_000, "basis": "unit"}]})
    sku = J(await c.get(f"/price-requests/{pr}", headers=d))["items"][0]["sku"]
    q = J(await c.post(f"/quotations/from-price-request/{pr}", headers=s1))
    await c.post(f"/quotations/{q['id']}/submit", headers=s1)
    await c.post(f"/quotations/{q['id']}/approve", headers=d, json={"notes": ""})
    cpo = J(await c.post("/customer-pos", headers=s1, json={
        "customer_id": cust, "quotation_id": q["id"], "number": f"CPO-{TAG}",
        "items": [{"description": PART, "qty": 100, "uom": "meter", "unit_price": 40_000}],
        "is_downpayment": False}))
    await c.post(f"/quotations/{q['id']}/won", headers=d)
    proj = J(await c.post(f"/customer-pos/{cpo['id']}/approve", headers=d,
                          json={"notes": ""}))["project_id"]

    sup = J(await c.post("/purchasing/suppliers", headers=pur, json={
        "name": f"Guangzhou Chain {TAG}", "country": "CN"}))["id"]

    # ══ an RMB order for 200 ═════════════════════════════════════════════
    print("\n── an order for 200, bought in RMB ──")
    po = J(await c.post("/purchasing/po", headers=d, json={
        "supplier_id": sup, "project_id": proj, "po_date": "2026-09-01",
        "currency": "CNY", "fx_rate": 2200,
        "items": [{"description": PART, "qty": 200, "uom": "meter",
                   "unit_price": 10, "sku": sku}]}))
    check("the order is raised", bool(po.get("id")), str(po)[:160])

    pay = J(await c.get("/finance/payables", headers=fin, params={"show": "all"}))
    row = next((x for x in pay["items"] if x["po_id"] == po["id"]), None)
    check("every purchasing PO shows under utang usaha — even before anything arrives",
          row is not None and row["status"] == "not_received", str(row))
    if row:
        check("...with its order value in its own currency and in rupiah",
              row["order_total"] == 2000 and row["currency"] == "CNY"
              and row["order_total_idr"] == 4_400_000, str(row))

    # ══ completing the receiving work order receives it ══════════════════
    print("\n── completing the receiving work order ──")
    async with SessionLocal() as db:
        p = await db.get(Project, uuid.UUID(proj)); p.status = "production"; await db.commit()
    wo = J(await c.post(f"/operation/projects/{proj}/work-orders", headers=adm,
                        json={"code": f"WO-RCV-{TAG}", "stage": "receiving"}))
    check("a receiving work order is filed", bool(wo.get("id")), str(wo)[:160])
    r = await c.patch(f"/operation/work-orders/{wo['id']}", headers=adm,
                      params={"completed": True})
    check("completing it is accepted", r.status_code == 200, f"{r.status_code} {why(r)}")
    got = J(r).get("received") or []
    check("...and it received the order nobody counted by hand",
          any(x["po_number"] == po["number"] for x in got), str(got))

    inv = J(await c.get("/inventory", headers=fin, params={"q": PART}))
    item = next((x for x in inv["items"] if x["name"] == PART), None)
    check("the 200 are on the shelf", item and item["current_stock"] == 200, str(item))
    check("...priced in RMB, not as rupiah",
          item and item["unit_cost"] == 10 and item["cost_currency"] == "CNY", str(item))
    check("...with the rupiah equivalent at the order's rate",
          item and item["unit_cost_idr"] == 22_000, str(item))

    pay = J(await c.get("/finance/payables", headers=fin))
    row = next((x for x in pay["items"] if x["po_id"] == po["id"]), None)
    check("receiving made the order owed — 200 × CNY 10 × 2.200",
          row is not None and row["received_value"] == 4_400_000
          and row["outstanding"] == 4_400_000 and row["status"] == "unpaid", str(row))

    # ══ the delivery order takes 100 out ═════════════════════════════════
    print("\n── a delivery order ships 100 ──")
    async with SessionLocal() as db:
        p = await db.get(Project, uuid.UUID(proj))
        p.status = "packaging"
        from datetime import datetime, UTC
        p.qc_passed_at = datetime.now(UTC); p.qc_decision = "pass"
        await db.commit()
    r = await c.post(f"/operation/projects/{proj}/delivery-order", headers=adm,
                     json={"items": [{"description": PART, "qty": 100, "uom": "meter"}]})
    check("the delivery order is raised", r.status_code == 201, f"{r.status_code} {why(r)}")
    do = J(r)["delivery_order"]
    inv = J(await c.get("/inventory", headers=fin, params={"q": PART}))
    item = next((x for x in inv["items"] if x["name"] == PART), None)
    check("100 are left — not none", item and item["current_stock"] == 100, str(item))

    # ══ the item's own page ══════════════════════════════════════════════
    print("\n── the item's page ──")
    h = J(await c.get(f"/inventory/{item['id']}/history", headers=fin))
    moves = h.get("movements") or []
    check("it lists every movement, newest first",
          len(moves) == 2 and moves[0]["delta"] == -100 and moves[1]["delta"] == 200,
          str([(m["reason"], m["delta"]) for m in moves]))
    check("...with the balance after each", [m["balance"] for m in moves] == [100, 200],
          str([m["balance"] for m in moves]))
    check("...linking the receipt to its purchase order",
          moves[1]["link"] == f"/purchase-orders/{po['id']}", str(moves[1]))
    check("...and the shipment to its delivery order",
          moves[0]["link"] == f"/deliveries/{do['id']}", str(moves[0]))
    check("...and the total is in step with them", h.get("in_step") is True, str(h.get("in_step")))
    check("...pricing it in both currencies", h["item"]["cost_currency"] == "CNY"
          and h["item"]["unit_cost_idr"] == 22_000, str(h["item"]))
    hs = J(await c.get(f"/inventory/{item['id']}/history", headers=s1))
    check("sales can open the page but not the price",
          hs.get("item") and hs["item"]["unit_cost"] is None, str(hs.get("item"))[:160])

    # ══ paying ═══════════════════════════════════════════════════════════
    print("\n── paying the supplier, and paying ahead ──")
    po2 = J(await c.post("/purchasing/po", headers=d, json={
        "supplier_id": sup, "project_id": proj, "po_date": "2026-09-02",
        "items": [{"description": f"SPROCKET {TAG}", "qty": 4, "uom": "pcs",
                   "unit_price": 250_000}]}))
    r = await c.post(f"/finance/payables/{po2['id']}/pay", headers=fin,
                     json={"amount": 400_000, "reference": f"DP-{TAG}"})
    check("a down payment ahead of delivery is accepted",
          r.status_code == 201, f"{r.status_code} {why(r)}")
    r = await c.post(f"/finance/payables/{po2['id']}/pay", headers=fin,
                     json={"amount": 700_000})
    check("...but not more than the order is worth", r.status_code == 409,
          f"{r.status_code} {why(r)}")
    pay = J(await c.get("/finance/payables", headers=fin, params={"show": "all"}))
    row = next((x for x in pay["items"] if x["po_id"] == po2["id"]), None)
    check("...and the order reads as paid ahead", row and row["status"] == "prepaid", str(row))

    # ══ current data ═════════════════════════════════════════════════════
    print("\n── orders received before this change ──")
    from app.models.purchasing import GoodsReceipt, SupplierPO
    po3 = J(await c.post("/purchasing/po", headers=d, json={
        "supplier_id": sup, "project_id": proj, "po_date": "2026-08-01",
        "items": [{"description": f"PIN {TAG}", "qty": 50, "uom": "pcs",
                   "unit_price": 1_000}]}))
    async with SessionLocal() as db:
        db.add(GoodsReceipt(po_id=uuid.UUID(po3["id"]), received_at=date(2026, 8, 20),
                            items=[{"line_no": 1, "qty": 50, "ordered": 50}],
                            status="received"))
        await db.commit()
    from app.services.payables import backfill_payables
    async with SessionLocal() as db:
        res = await backfill_payables(db); await db.commit()
    async with SessionLocal() as db:
        got = await db.get(SupplierPO, uuid.UUID(po3["id"]))
        check("an order received before receiving posted payables is brought in",
              float(got.payable_amount or 0) == 50_000, str(got.payable_amount))
    async with SessionLocal() as db:
        res2 = await backfill_payables(db); await db.commit()
    async with SessionLocal() as db:
        got = await db.get(SupplierPO, uuid.UUID(po3["id"]))
        check("...once — running it again adds nothing",
              float(got.payable_amount or 0) == 50_000, str(got.payable_amount))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        sys.exit(1)

asyncio.run(main())

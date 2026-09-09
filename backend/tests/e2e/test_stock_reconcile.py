"""Putting the shelf back in line with the paperwork.

Stock here is a ledger: every change is a movement naming the document that
caused it, and `current_stock` is a running total kept on the item for speed.
Things predate that. Items were typed in with an opening figure and no movement
behind it; quantities were set straight onto the row; orders went through
mechanisms since replaced. What is left is a count that no longer follows from
anything you can read, which is the state where people stop trusting it.

Reconciliation fixes three faults, and the point of separating them is that
they have three different right answers:

* **Drift** — the total disagrees with the movements behind it. The movements
  each name a document; the total is a cache. So the total is what is wrong.
* **A quantity with no history at all** — an opening balance somebody typed
  before the ledger existed. The figure is probably right and the explanation
  is missing, so the explanation gets written and the count does not move.
  Deleting these because no document justifies them throws away real stock.
* **A live order never counted in** — the shelf is short by goods somebody
  ordered. Replayed through the ordinary path, so it is indistinguishable from
  an order that worked first time.

And the one it must NOT touch: a hand adjustment after a physical count is a
legitimate movement with no order behind it. A reconciliation that "corrects"
those silently deletes the stocktake, so that is checked explicitly.

Everything previews first, and the preview has to be what runs — a dry run
computed by a different code path from the fix is one that eventually stops
matching it.
"""
import asyncio, os, sys, uuid
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123",
    STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import httpx, logging; logging.disable(logging.INFO)
TAG = uuid.uuid4().hex[:6]
PASS, FAIL = [], []
def check(n, c, d=""):
    (PASS if c else FAIL).append(n); print(("  PASS " if c else "  FAIL ")+n+(f"  [{d}]" if d and not c else ""))
def J(r):
    try: return r.json()
    except Exception: return {"_": r.text[:200]}
def why(r):
    b = J(r)
    return str(b.get("detail") or (b.get("errors") or [{}])[0].get("message", "")).lower()


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    from app.core.db import SessionLocal
    from app.models.inventory import InventoryItem, InventoryMovement
    from app.models.purchasing import SupplierPO
    from sqlalchemy import select

    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)

    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    s1 = await login("sales1@demo.local")
    pur = await login("purchasing@demo.local")

    async def stock_of(sku):
        rows = J(await c.get("/inventory", headers=d, params={"limit": 500}))
        rows = rows if isinstance(rows, list) else rows.get("items", [])
        it = next((x for x in rows if x.get("sku") == sku), None)
        return float(it["current_stock"]) if it else None

    sup = J(await c.post("/purchasing/suppliers", headers=pur, json={
        "name": f"PT Lama {TAG}", "country": "ID"}))["id"]

    # A supplier order has to belong to a job, so there is one to hang these on.
    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Rekon {TAG}", "industry": "mining"}))["id"]
    pr = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [{"description": f"Anchor {TAG}", "qty": 1, "uom": "pcs",
                   "category": "others"}]}))
    await c.post(f"/price-requests/{pr['id']}/submit", headers=s1)
    await c.post(f"/price-requests/{pr['id']}/price", headers=pur,
                 json={"items": [{"line_no": 1, "cost_price": 10, "basis": "unit"}]})
    await c.post(f"/price-requests/{pr['id']}/approve", headers=d,
                 json={"items": [{"line_no": 1, "sell_price": 20, "basis": "unit"}]})
    quo = J(await c.post(f"/quotations/from-price-request/{pr['id']}", headers=s1))
    await c.post(f"/quotations/{quo['id']}/submit", headers=s1)
    await c.post(f"/quotations/{quo['id']}/approve", headers=d, json={"decision": "approve"})
    cpo = J(await c.post("/customer-pos", headers=s1, json={
        "customer_id": cust, "quotation_id": quo["id"], "number": f"CPO-{TAG}",
        "po_date": "2026-09-08",
        "items": [{"description": f"Anchor {TAG}", "qty": 1, "unit_price": 20}]}))
    await c.post(f"/customer-pos/{cpo['id']}/approve", headers=d, json={"decision": "approve"})
    proj = J(await c.get(f"/customer-pos/{cpo['id']}", headers=d))["project_id"]

    # ══ build the three faults, the way the old system left them ═════════
    print("\n── a stock list carrying the old system's leftovers ──")

    # (1) DRIFT: movements say one thing, the cached total says another. This
    #     is what a direct edit to the row looks like afterwards.
    po = J(await c.post("/purchasing/po", headers=d, json={
        "supplier_id": sup, "project_id": proj, "po_date": "2026-09-08",
        "items": [{"description": f"Drift Part {TAG}", "qty": 12,
                   "unit_price": 1000, "uom": "pcs"}]}))
    drift_sku = None
    async with SessionLocal() as db:
        item = await db.scalar(select(InventoryItem).where(
            InventoryItem.name == f"Drift Part {TAG}"))
        drift_sku = item.sku
        item.current_stock = 3          # somebody edited the number directly
        await db.commit()
    check("an item's total was edited away from its movements",
          await stock_of(drift_sku) == 3, str(await stock_of(drift_sku)))

    # (2) OPENING BALANCE: a quantity with no movements at all.
    opening_sku = f"OLD{TAG}"
    async with SessionLocal() as db:
        db.add(InventoryItem(sku=opening_sku, name=f"Opening Part {TAG}",
                             uom="pcs", unit_cost=500, current_stock=40,
                             is_active=True))
        await db.commit()
    check("an item holds a figure nothing explains",
          await stock_of(opening_sku) == 40, str(await stock_of(opening_sku)))

    # (3) A LIVE ORDER NEVER COUNTED IN: an open PO with no po_in behind it.
    po2 = J(await c.post("/purchasing/po", headers=d, json={
        "supplier_id": sup, "project_id": proj, "po_date": "2026-09-08",
        "items": [{"description": f"Missed Part {TAG}", "qty": 7,
                   "unit_price": 900, "uom": "pcs"}]}))
    missed_sku = None
    async with SessionLocal() as db:
        item = await db.scalar(select(InventoryItem).where(
            InventoryItem.name == f"Missed Part {TAG}"))
        missed_sku = item.sku
        # Strip the order's effect entirely, as if it had never landed.
        for m in (await db.scalars(select(InventoryMovement).where(
                InventoryMovement.reference == po2["number"]))).all():
            await db.delete(m)
        item.current_stock = 0
        await db.commit()
    check("a live order left no trace on the shelf",
          await stock_of(missed_sku) == 0, str(await stock_of(missed_sku)))

    # (4) THE ONE THAT MUST SURVIVE: a hand count with no document behind it.
    counted_sku = f"CNT{TAG}"
    async with SessionLocal() as db:
        it = InventoryItem(sku=counted_sku, name=f"Counted Part {TAG}",
                           uom="pcs", unit_cost=100, current_stock=0,
                           is_active=True)
        db.add(it); await db.flush()
        counted_id = str(it.id)
        await db.commit()
    r = await c.post(f"/inventory/{counted_id}/adjust", headers=d, json={
        "delta": 25, "reason": "adjust", "notes": "physical count"})
    check("a stocktake is recorded as an ordinary movement", r.status_code == 200,
          f"{r.status_code} {why(r)}")
    check("...and stands at what was counted", await stock_of(counted_sku) == 25,
          str(await stock_of(counted_sku)))

    # ══ the preview ══════════════════════════════════════════════════════
    print("\n── the preview says what is wrong, and changes nothing ──")
    r = await c.get("/inventory/reconcile", headers=pur)
    check("purchasing can look", r.status_code == 200, f"{r.status_code} {why(r)}")
    rep = J(r)
    check("...it is marked as not applied", rep["applied"] is False, str(rep.get("applied")))
    check("the drifted total is listed",
          any(x["sku"] == drift_sku for x in rep["drift"]),
          str([x["sku"] for x in rep["drift"]])[:160])
    row = next(x for x in rep["drift"] if x["sku"] == drift_sku)
    check("...saying what it is and what it should be",
          row["was"] == 3 and row["now"] == 12, str(row))
    check("the unexplained figure is listed as an opening balance",
          any(x["sku"] == opening_sku and x["qty"] == 40
              for x in rep["opening_balances"]),
          str(rep["opening_balances"])[:200])
    check("the order that never landed is listed",
          any(x["number"] == po2["number"] for x in rep["replayed_orders"]),
          str([x["number"] for x in rep["replayed_orders"]])[:160])
    check("the hand count is left out of all three",
          not any(x["sku"] == counted_sku for x in rep["drift"] + rep["opening_balances"]),
          counted_sku)

    check("nothing moved while previewing",
          await stock_of(drift_sku) == 3 and await stock_of(missed_sku) == 0,
          f"{await stock_of(drift_sku)} / {await stock_of(missed_sku)}")

    r = await c.get("/inventory/reconcile", headers=s1)
    check("sales cannot", r.status_code == 403, str(r.status_code))
    r = await c.post("/inventory/reconcile", headers=pur)
    check("...and purchasing may look but not apply", r.status_code == 403,
          str(r.status_code))

    # ══ applying it ══════════════════════════════════════════════════════
    print("\n── the director applies it ──")
    r = await c.post("/inventory/reconcile", headers=d)
    check("it runs", r.status_code == 200, f"{r.status_code} {why(r)}")
    done = J(r)
    check("...and says so", done["applied"] is True, str(done.get("applied")))

    check("the drifted total now matches its own movements",
          await stock_of(drift_sku) == 12, str(await stock_of(drift_sku)))
    check("the order that never landed is on the shelf",
          await stock_of(missed_sku) == 7, str(await stock_of(missed_sku)))
    check("the opening balance is unchanged — it was never in doubt",
          await stock_of(opening_sku) == 40, str(await stock_of(opening_sku)))
    check("the hand count is untouched",
          await stock_of(counted_sku) == 25, str(await stock_of(counted_sku)))

    print("\n── and every figure now follows from something written down ──")
    async with SessionLocal() as db:
        item = await db.scalar(select(InventoryItem).where(
            InventoryItem.sku == opening_sku))
        moves = (await db.scalars(select(InventoryMovement).where(
            InventoryMovement.item_id == item.id))).all()
    check("the opening balance was given a movement explaining it",
          len(moves) == 1 and float(moves[0].delta) == 40
          and moves[0].reason == "opening", str([(m.reason, float(m.delta)) for m in moves]))

    async with SessionLocal() as db:
        item = await db.scalar(select(InventoryItem).where(
            InventoryItem.sku == drift_sku))
        total = sum(float(m.delta) for m in (await db.scalars(
            select(InventoryMovement).where(
                InventoryMovement.item_id == item.id))).all())
    check("the drift fix wrote no movement — the existing ones already add up",
          total == 12 and float(item.current_stock) == 12,
          f"ledger={total} stock={item.current_stock}")

    # ══ running it twice ═════════════════════════════════════════════════
    print("\n── and running it again has nothing left to do ──")
    rep2 = J(await c.get("/inventory/reconcile", headers=d))
    check("the preview is clean for the items we broke",
          not any(x["sku"] in (drift_sku, opening_sku)
                  for x in rep2["drift"] + rep2["opening_balances"])
          and not any(x["number"] == po2["number"] for x in rep2["replayed_orders"]),
          str(rep2["summary"]))
    r = await c.post("/inventory/reconcile", headers=d)
    check("applying twice is safe", r.status_code == 200, f"{r.status_code} {why(r)}")
    check("...and moves nothing the second time",
          await stock_of(drift_sku) == 12 and await stock_of(missed_sku) == 7
          and await stock_of(opening_sku) == 40 and await stock_of(counted_sku) == 25,
          f"{await stock_of(drift_sku)}/{await stock_of(missed_sku)}/"
          f"{await stock_of(opening_sku)}/{await stock_of(counted_sku)}")

    # ══ what it refuses to count ═════════════════════════════════════════
    print("\n── an order nobody released is not goods on a shelf ──")
    po3 = J(await c.post("/purchasing/po", headers=pur, json={
        "supplier_id": sup, "project_id": proj, "po_date": "2026-09-08",
        "items": [{"description": f"Pending Part {TAG}", "qty": 5,
                   "unit_price": 100, "uom": "pcs"}]}))
    async with SessionLocal() as db:
        row = await db.scalar(select(SupplierPO).where(
            SupplierPO.number == po3["number"]))
        check("the order is waiting on the director",
              row.status == "pending_approval", row.status)
    rep3 = J(await c.get("/inventory/reconcile", headers=d))
    check("...so reconciliation leaves it alone",
          not any(x["number"] == po3["number"] for x in rep3["replayed_orders"]),
          str([x["number"] for x in rep3["replayed_orders"]])[:160])

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)


asyncio.run(main())

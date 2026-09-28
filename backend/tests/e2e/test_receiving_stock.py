"""Order ten, receive five, and the shelf says five — and the supplier is owed.

Goods enter stock when they are **received**, not when they are ordered. A
supplier PO opening registers its parts in the catalogue and moves no
quantity; the receiving work order records what actually arrived, and that is
what goes into inventory. The same receipt makes the supplier owed for it:
utang usaha, posted to the ledger and listed for finance, who pay it down.

The receiving work order lists every line on every supplier order feeding the
job; you tick what arrived, set the quantities, and record. What that must get
right:

* **Stock is what arrived.** Ordered ten, received five: the shelf gains five.
  Recording the same figure again moves nothing.
* **It is idempotent.** The delta is computed from what the order currently
  contributes, so the second press is a no-op and the tenth is too.
* **A line nobody has counted yet is not a line that received nothing.** Only
  ticked lines move; leaving one out must not empty the shelf of it.
* **The rest arriving later adds it back**, without anyone re-deriving what is
  outstanding by hand.
* **Cancelling a partly-received order leaves zero, not minus five.** The old
  reversal undid the ordered quantity, which was exact only while receiving
  did nothing.

And the document survives: every sync files a goods receipt, so what was
counted in and when is on the record separately from the running total.
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
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)

    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    s1 = await login("sales1@demo.local")
    pur = await login("purchasing@demo.local")

    # ── a project to hang the order on ───────────────────────────────────
    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Terima {TAG}", "industry": "mining"}))["id"]
    pr = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [{"description": f"Chain A {TAG}", "qty": 10, "uom": "pcs",
                   "category": "roller_chain"},
                  {"description": f"Chain B {TAG}", "qty": 4, "uom": "pcs",
                   "category": "sprocket"}]}))
    await c.post(f"/price-requests/{pr['id']}/submit", headers=s1)
    await c.post(f"/price-requests/{pr['id']}/price", headers=pur, json={
        "items": [{"line_no": 1, "cost_price": 100_000, "basis": "unit"},
                  {"line_no": 2, "cost_price": 50_000, "basis": "unit"}]})
    await c.post(f"/price-requests/{pr['id']}/approve", headers=d, json={
        "items": [{"line_no": 1, "sell_price": 200_000, "basis": "unit"},
                  {"line_no": 2, "sell_price": 100_000, "basis": "unit"}]})
    q = J(await c.post(f"/quotations/from-price-request/{pr['id']}", headers=s1))
    await c.post(f"/quotations/{q['id']}/submit", headers=s1)
    await c.post(f"/quotations/{q['id']}/approve", headers=d, json={"decision": "approve"})
    cpo = J(await c.post("/customer-pos", headers=s1, json={
        "customer_id": cust, "quotation_id": q["id"], "number": f"CPO-{TAG}",
        "po_date": "2026-09-08",
        "items": [{"description": f"Chain A {TAG}", "qty": 10, "unit_price": 200_000}]}))
    await c.post(f"/customer-pos/{cpo['id']}/approve", headers=d, json={"decision": "approve"})
    proj = J(await c.get(f"/customer-pos/{cpo['id']}", headers=d))["project_id"]

    sup = J(await c.post("/purchasing/suppliers", headers=pur, json={
        "name": f"PT Pemasok {TAG}", "country": "ID"}))["id"]
    po = J(await c.post("/purchasing/po", headers=d, json={
        "supplier_id": sup, "project_id": proj, "po_date": "2026-09-08",
        "items": [{"description": f"Chain A {TAG}", "qty": 10, "unit_price": 100_000,
                   "uom": "pcs"},
                  {"description": f"Chain B {TAG}", "qty": 4, "unit_price": 50_000,
                   "uom": "pcs"}]}))
    check("a supplier order is raised", bool(po.get("id")), str(po)[:160])

    async def stock(name_part):
        rows = J(await c.get("/inventory", headers=d, params={"limit": 400}))
        rows = rows if isinstance(rows, list) else rows.get("items", [])
        it = next((x for x in rows if name_part in (x.get("name") or "")), None)
        return float(it.get("current_stock") or 0) if it else None

    A, B = f"Chain A {TAG}", f"Chain B {TAG}"
    check("opening the order puts nothing on the shelf — stock enters on receiving",
          (await stock(A) or 0) == 0 and (await stock(B) or 0) == 0,
          f"A={await stock(A)} B={await stock(B)}")

    # ══ the receiving work order's list ══════════════════════════════════
    print("\n── what the receiving work order offers ──")
    r = await c.get(f"/operation/projects/{proj}/receiving", headers=pur)
    check("purchasing can read it", r.status_code == 200, f"{r.status_code} {why(r)}")
    view = J(r)
    check("...and it finds the order on this job",
          len(view["purchase_orders"]) == 1, str(len(view["purchase_orders"])))
    lines = view["purchase_orders"][0]["lines"]
    check("...listing both lines with what was ordered",
          [l["ordered"] for l in lines] == [10, 4], str([l["ordered"] for l in lines]))
    check("...and that nothing has been received into stock yet",
          all((l["counted_in"] or 0) == 0 for l in lines),
          str([l["counted_in"] for l in lines]))
    check("...with nothing received against it yet",
          all(l["last_received"] is None for l in lines),
          str([l["last_received"] for l in lines]))

    r = await c.get(f"/operation/projects/{proj}/receiving", headers=s1)
    check("sales cannot", r.status_code == 403, str(r.status_code))

    # ══ order ten, receive five ══════════════════════════════════════════
    print("\n── five of the ten turn up ──")
    r = await c.post(f"/operation/projects/{proj}/receiving", headers=pur, json={
        "po_id": po["id"], "received_at": "2026-09-20",
        "lines": [{"line_no": 1, "qty": 5}]})
    check("the receipt is recorded", r.status_code == 200, f"{r.status_code} {why(r)}")
    body = J(r)
    check("...and it says what moved: five into stock",
          body["lines"][0]["delta"] == 5, str(body["lines"][0]))
    check("the shelf now says five", await stock(A) == 5, str(await stock(A)))
    check("...and the line nobody counted is untouched",
          (await stock(B) or 0) == 0, str(await stock(B)))

    # Received goods are owed for: five at Rp 100.000 is Rp 500.000 of utang usaha.
    check("the receipt makes the supplier owed for what arrived",
          body.get("payable_added") == 500_000, str(body.get("payable_added")))
    fin = await login("finance@demo.local")
    pay = J(await c.get("/finance/payables", headers=fin))
    row = next((x for x in pay.get("items", []) if x["po_id"] == po["id"]), None)
    check("...and it is on finance's utang usaha list",
          row is not None and row["outstanding"] == 500_000, str(row))
    r = await c.get("/finance/payables", headers=pur)
    check("...which purchasing cannot open", r.status_code == 403, str(r.status_code))

    check("a goods receipt exists for it", bool(body.get("goods_receipt_id")),
          str(body.get("goods_receipt_id")))
    grs = J(await c.get("/purchasing/gr", headers=pur, params={"po_id": po["id"]}))
    check("...and it is on the order's receipt list", len(grs) == 1, str(len(grs)))
    check("...recording ordered and received side by side",
          grs[0]["items"][0]["ordered"] == 10 and grs[0]["items"][0]["qty"] == 5,
          str(grs[0]["items"][0]))

    # ══ pressing it again ════════════════════════════════════════════════
    print("\n── pressing sync again changes nothing ──")
    r = await c.post(f"/operation/projects/{proj}/receiving", headers=pur, json={
        "po_id": po["id"], "lines": [{"line_no": 1, "qty": 5}]})
    check("the second sync is accepted", r.status_code == 200, f"{r.status_code} {why(r)}")
    check("...moves nothing", J(r)["stock_changed"] == [], str(J(r)["stock_changed"]))
    check("...and the shelf still says five", await stock(A) == 5, str(await stock(A)))

    # ══ the rest arrives ═════════════════════════════════════════════════
    print("\n── the missing five arrive later ──")
    view = J(await c.get(f"/operation/projects/{proj}/receiving", headers=pur))
    l1 = view["purchase_orders"][0]["lines"][0]
    check("the form remembers what was entered last time", l1["last_received"] == 5,
          str(l1["last_received"]))
    check("...and shows the shelf standing at five", l1["counted_in"] == 5,
          str(l1["counted_in"]))

    r = await c.post(f"/operation/projects/{proj}/receiving", headers=pur, json={
        "po_id": po["id"], "lines": [{"line_no": 1, "qty": 10},
                                     {"line_no": 2, "qty": 4}]})
    check("recording the full quantity works", r.status_code == 200,
          f"{r.status_code} {why(r)}")
    check("...the shelf is back to ten", await stock(A) == 10, str(await stock(A)))
    check("...and the second line's four are in too",
          await stock(B) == 4, str(await stock(B)))
    changed = {m["line_no"]: m["delta"] for m in J(r)["stock_changed"]}
    check("...each line reports what it added",
          changed == {1: 5, 2: 4}, str(changed))
    check("...and the payable grows by what arrived: 5 × 100.000 + 4 × 50.000",
          J(r).get("payable_added") == 700_000 and J(r).get("payable_amount") == 1_200_000,
          f"{J(r).get('payable_added')} / {J(r).get('payable_amount')}")

    print("\n── finance pays the supplier ──")
    r = await c.post(f"/finance/payables/{po['id']}/pay", headers=fin,
                     json={"amount": 2_000_000, "paid_at": "2026-09-25"})
    check("paying more than is owed is refused", r.status_code == 409,
          f"{r.status_code} {why(r)}")
    r = await c.post(f"/finance/payables/{po['id']}/pay", headers=pur,
                     json={"amount": 100_000})
    check("purchasing cannot record a supplier payment", r.status_code == 403,
          str(r.status_code))
    r = await c.post(f"/finance/payables/{po['id']}/pay", headers=fin,
                     json={"amount": 1_000_000, "paid_at": "2026-09-25",
                           "reference": f"TRF-{TAG}"})
    check("finance records a part payment", r.status_code == 201 and
          J(r).get("outstanding") == 200_000, f"{r.status_code} {J(r)}")
    pay = J(await c.get("/finance/payables", headers=fin))
    row = next((x for x in pay.get("items", []) if x["po_id"] == po["id"]), None)
    check("...and the list shows what is left", row is not None
          and row["paid"] == 1_000_000 and row["status"] == "partial", str(row))

    # ══ more than ordered ════════════════════════════════════════════════
    print("\n── and an over-delivery is recorded, not argued with ──")
    r = await c.post(f"/operation/projects/{proj}/receiving", headers=pur, json={
        "po_id": po["id"], "lines": [{"line_no": 2, "qty": 6}]})
    check("six against an order for four is accepted", r.status_code == 200,
          f"{r.status_code} {why(r)}")
    check("...and the shelf says six, because six is what is there",
          await stock(B) == 6, str(await stock(B)))

    # ══ what it refuses ══════════════════════════════════════════════════
    print("\n── what it will not take ──")
    r = await c.post(f"/operation/projects/{proj}/receiving", headers=pur, json={
        "po_id": po["id"], "lines": []})
    check("an empty tick list is refused", r.status_code == 400, str(r.status_code))
    r = await c.post(f"/operation/projects/{proj}/receiving", headers=pur, json={
        "po_id": po["id"], "lines": [{"line_no": 9, "qty": 1}]})
    check("a line that does not exist is refused", r.status_code == 400,
          str(r.status_code))
    r = await c.post(f"/operation/projects/{proj}/receiving", headers=pur, json={
        "po_id": po["id"], "lines": [{"line_no": 1, "qty": -2}]})
    check("a negative quantity is refused", r.status_code == 400, str(r.status_code))
    r = await c.post(f"/operation/projects/{proj}/receiving", headers=s1, json={
        "po_id": po["id"], "lines": [{"line_no": 1, "qty": 1}]})
    check("sales cannot receive goods", r.status_code == 403, str(r.status_code))

    # ══ cancelling what was partly received ══════════════════════════════
    print("\n── cancelling a partly-received order leaves zero, not a deficit ──")
    po2 = J(await c.post("/purchasing/po", headers=d, json={
        "supplier_id": sup, "project_id": proj, "po_date": "2026-09-08",
        "items": [{"description": f"Chain C {TAG}", "qty": 10, "unit_price": 90_000,
                   "uom": "pcs"}]}))
    C = f"Chain C {TAG}"
    check("the second order puts nothing on the shelf yet",
          (await stock(C) or 0) == 0, str(await stock(C)))
    await c.post(f"/operation/projects/{proj}/receiving", headers=pur, json={
        "po_id": po2["id"], "lines": [{"line_no": 1, "qty": 5}]})
    check("...five arrive", await stock(C) == 5, str(await stock(C)))
    r = await c.patch(f"/purchasing/po/{po2['id']}", headers=d,
                      json={"status": "cancelled"})
    check("the order is cancelled", r.status_code == 200, f"{r.status_code} {why(r)}")
    check("...and the shelf lands on zero, not minus five",
          await stock(C) == 0, str(await stock(C)))

    print("\n── and reopening it, then syncing, gets back to the truth ──")
    r = await c.patch(f"/purchasing/po/{po2['id']}", headers=d, json={"status": "open"})
    check("it reopens", r.status_code == 200, f"{r.status_code} {why(r)}")
    check("...and reopening puts nothing on the shelf — nothing new arrived",
          (await stock(C) or 0) == 0, str(await stock(C)))
    await c.post(f"/operation/projects/{proj}/receiving", headers=pur, json={
        "po_id": po2["id"], "lines": [{"line_no": 1, "qty": 5}]})
    check("...and recording the receipt puts the five back",
          await stock(C) == 5, str(await stock(C)))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)


asyncio.run(main())

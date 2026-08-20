"""Stock that follows the paperwork, and two walls that were missing.

Three things asked for on three screenshots.

**"Every purchasing PO: item become SKU (number auto generate); Qty Order
Become stock add; every Delivery order minus the stock."** The inventory was
a list somebody typed once: fifteen items, every one reading zero, while the
POs and delivery orders that actually move goods went past it all day. A
stock figure nobody maintains is worse than none — people check it, find it
wrong, and stop checking, and a page headed "check what's in stock before
promising delivery" then helps you promise wrong.

**"At Sales: they only can see their own customer list."** The operation
board listed every project in the company by customer name, to any sales
login. The projects list has drawn that boundary for a long time; the board
was the one surface that skipped it, so a rep opening a stage read the whole
order book — every other rep's customers, what each is waiting for, and when
it was promised.

**"At ADMIN: cannot see Unit Cost."** Admin is kept away from procurement
cost everywhere else — the project page, supplier POs, supplier drawings —
because they run the customer side and the buy price is the figure that maps
a customer's job to a supplier's price. The inventory list handed it to them
in a column.

What this pins down beyond "the number moved":

**Stock rises when the PO is open, not when it is typed.** An order waiting
for the director may be cancelled, and goods nobody was told to send are not
on a shelf.

**Reversal is exact and idempotent.** Cancelling a PO or withdrawing a
delivery order undoes precisely the movements carrying that document's
number, once — and reopening the PO puts them back, which a naive "have we
ever moved this?" guard would refuse to do forever.
"""
import asyncio, os, sys, uuid
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123",
    STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import httpx, logging; logging.disable(logging.INFO)
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
    tag = uuid.uuid4().hex[:5]

    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    adm = await login("admin@demo.local")
    pur = await login("purchasing@demo.local")
    s1 = await login("sales1@demo.local")
    s2 = await login("sales2@demo.local")
    fin = await login("finance@demo.local")

    part = f"CHAIN SPROCKET TYPE B {tag}"

    async def a_project(rep, label):
        cust = J(await c.post("/customers", headers=rep, json={
            "company_name": f"PT Gudang {label} {tag}", "industry": "mining",
            "delivery_address": "SITE, KALIMANTAN"}))["id"]
        pr = J(await c.post("/price-requests", headers=rep, json={
            "customer_id": cust,
            "items": [{"description": part, "qty": 10, "uom": "EA"}]}))["id"]
        await c.post(f"/price-requests/{pr}/submit", headers=rep)
        await c.post(f"/price-requests/{pr}/price", headers=d, json={
            "items": [{"line_no": 1, "cost_price": 250_000, "basis": "unit"}]})
        await c.post(f"/price-requests/{pr}/approve", headers=d, json={
            "items": [{"line_no": 1, "sell_price": 500_000, "basis": "unit"}]})
        q = J(await c.post(f"/quotations/from-price-request/{pr}", headers=rep))["id"]
        await c.post(f"/quotations/{q}/submit", headers=rep)
        await c.post(f"/quotations/{q}/approve", headers=d, json={"notes": ""})
        cpo = J(await c.post("/customer-pos", headers=rep, json={
            "customer_id": cust, "quotation_id": q, "number": f"PO-{label}-{tag}",
            "items": [{"description": part, "qty": 10, "uom": "EA",
                       "unit_price": 500_000}],
            "is_downpayment": False}))["id"]
        await c.post(f"/quotations/{q}/won", headers=d)
        proj = J(await c.post(f"/customer-pos/{cpo}/approve", headers=d,
                              json={"notes": ""}))["project_id"]
        await c.post(f"/operation/projects/{proj}/qc", headers=adm,
                     json={"decision": "pass"})
        return proj

    async def stock_of(name, headers=None):
        rows = J(await c.get("/inventory", headers=headers or d,
                             params={"q": name}))
        rows = [r for r in rows if r["name"] == name]
        return (rows[0]["current_stock"], rows[0]["sku"]) if rows else (None, None)

    proj = await a_project(s1, "A")

    # ══ a purchase order puts goods on the shelf ═════════════════════════════
    print("\n── ordering ──")
    have, _ = await stock_of(part)
    check("the part is not in the catalogue yet", have is None, str(have))
    sup = J(await c.post("/purchasing/suppliers", headers=pur,
                         json={"name": f"PT Pemasok {tag}"}))["id"]
    r = await c.post("/purchasing/po", headers=pur, json={
        "supplier_id": sup, "project_id": proj, "total": 2_500_000,
        "items": [{"description": part, "qty": 10, "uom": "EA",
                   "unit_price": 250_000}]})
    check("purchasing files a PO", r.status_code in (200, 201),
          f"{r.status_code} {J(r)}"[:170])
    po = J(r)
    check("...which waits for the director", po["status"] == "pending_approval",
          po["status"])
    have, _ = await stock_of(part)
    check("...and moves no stock while it waits", have is None, str(have))

    appr = [a for a in J(await c.get("/approvals", headers=d))
            if a.get("target_id") == po["id"]]
    check("the director has it to approve", len(appr) == 1, str(len(appr)))
    r = await c.post(f"/approvals/{appr[0]['id']}/approve", headers=d)
    check("...and approves it", r.status_code == 200, f"{r.status_code} {J(r)}"[:150])

    have, sku = await stock_of(part)
    check("the part is now in the catalogue", have is not None, "not created")
    check("...with a generated SKU in the company's own series",
          bool(sku) and sku.isdigit() and int(sku) > 100_000, str(sku))
    check("...and the ordered quantity on the shelf", have == 10.0, str(have))
    row = [x for x in J(await c.get("/inventory", headers=d, params={"q": part}))
           if x["name"] == part][0]
    check("...costed at what we are paying for it",
          float(row["unit_cost"]) == 250_000.0, str(row["unit_cost"]))
    movs = J(await c.get(f"/inventory/{row['id']}/movements", headers=d))
    check("...written down as a movement naming the PO",
          any(m["reason"] == "po_in" and m["reference"] == po["number"]
              for m in movs), str(movs)[:200])

    # ══ a delivery order takes them off it ═══════════════════════════════════
    print("\n── delivering ──")
    r = await c.post(f"/operation/projects/{proj}/delivery-order", headers=adm,
                     json={"items": [{"description": part, "qty": 4, "uom": "EA"}]})
    check("a delivery order goes out for four", r.status_code == 201,
          f"{r.status_code} {J(r)}"[:170])
    do = J(r)["delivery_order"]
    have, _ = await stock_of(part)
    check("...and the shelf is four lighter", have == 6.0, str(have))
    movs = J(await c.get(f"/inventory/{row['id']}/movements", headers=d))
    check("...under the delivery order's own number",
          any(m["reason"] == "do_out" and m["reference"] == do["number"]
              and m["delta"] == -4.0 for m in movs), str(movs)[:250])

    r = await c.delete(f"/operation/deliveries/{do['id']}", headers=adm)
    check("withdrawing the shipment is allowed before sign-off",
          r.status_code == 204, str(r.status_code))
    have, _ = await stock_of(part)
    check("...and puts the four back", have == 10.0, str(have))

    # ══ cancelling the order takes them back ═════════════════════════════════
    print("\n── cancelling the order ──")
    r = await c.patch(f"/purchasing/po/{po['id']}", headers=d,
                      json={"status": "cancelled"})
    check("the director cancels the PO", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:150])
    have, _ = await stock_of(part)
    check("...and the goods come off the shelf", have == 0.0, str(have))
    r = await c.patch(f"/purchasing/po/{po['id']}", headers=d,
                      json={"status": "cancelled"})
    have, _ = await stock_of(part)
    check("cancelling twice does not take them off twice", have == 0.0, str(have))
    r = await c.patch(f"/purchasing/po/{po['id']}", headers=d,
                      json={"status": "open"})
    have, _ = await stock_of(part)
    check("reopening it puts them back", have == 10.0, str(have))

    # ══ what admin and sales may see of the cost ═════════════════════════════
    print("\n── the unit cost column ──")
    for who, hdr, may in (("the director", d, True), ("purchasing", pur, True),
                          ("finance", fin, True), ("admin", adm, False),
                          ("sales", s1, False)):
        rows = [x for x in J(await c.get("/inventory", headers=hdr,
                                         params={"q": part}))
                if x["name"] == part]
        got = rows[0]["unit_cost"] if rows else "missing"
        check(f"{who} {'sees' if may else 'does not see'} what it cost",
              (got is not None) == may and rows != [], str(got))
    item = J(await c.get(f"/inventory/{row['id']}", headers=adm))
    check("...on the single item too, not just the list",
          item["unit_cost"] is None, str(item["unit_cost"]))
    check("...while the stock figure itself is still theirs to read",
          item["current_stock"] == 10.0, str(item["current_stock"]))

    # ══ the operation board ══════════════════════════════════════════════════
    print("\n── the operation board ──")
    other = await a_project(s2, "B")
    await c.post(f"/operation/projects/{proj}/work-orders", headers=adm,
                 json={"code": f"WO-A-{tag}", "stage": "receiving"})
    await c.post(f"/operation/projects/{other}/work-orders", headers=adm,
                 json={"code": f"WO-B-{tag}", "stage": "receiving"})
    mine = J(await c.get("/operation/work-orders", headers=s1,
                         params={"stage": "receiving"}))
    codes = [w.get("code") for w in mine]
    check("a rep sees their own customer's work order",
          f"WO-A-{tag}" in codes, str(codes)[:200])
    check("...and not the other rep's", f"WO-B-{tag}" not in codes,
          str(codes)[:200])
    names = {w.get("customer_name") for w in mine}
    check("...so no other rep's customer is named to them",
          not any((n or "").endswith(f"B {tag}") for n in names), str(names)[:200])
    theirs = J(await c.get("/operation/work-orders", headers=s2,
                           params={"stage": "receiving"}))
    check("the other rep sees theirs, and only theirs",
          f"WO-B-{tag}" in [w.get("code") for w in theirs]
          and f"WO-A-{tag}" not in [w.get("code") for w in theirs],
          str([w.get("code") for w in theirs])[:200])
    both = J(await c.get("/operation/work-orders", headers=d,
                         params={"stage": "receiving"}))
    check("the director still sees the whole board",
          {f"WO-A-{tag}", f"WO-B-{tag}"} <= {w.get("code") for w in both},
          str([w.get("code") for w in both])[:200])
    ops = J(await c.get("/operation/work-orders", headers=adm,
                        params={"stage": "receiving"}))
    check("...and so does admin, who work every job",
          {f"WO-A-{tag}", f"WO-B-{tag}"} <= {w.get("code") for w in ops},
          str([w.get("code") for w in ops])[:200])

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)


asyncio.run(main())

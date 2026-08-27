"""Price request → catalogue → purchase order → delivery order.

Asked for: *"For price request to inventory link I want it to be that it
starts from PR where the sales have to put the no. SKU and product name,
category, and unit — there's pcs, meter, set, roll — and link. When a price
request is submitted put the product in the price request into the inventory
and not the quantity. For quantity it comes from the purchasing PR. And when
a delivery order is submitted the quantity of that product will be deducted
based on how much the DO is sending out."*

The whole design is one sentence: **quantity has exactly one source on the
way in.** A price request introduces the part and moves nothing; the
purchase order is the only thing that adds; the delivery order subtracts.
So the checks below are mostly about what does *not* happen:

- submitting a price request creates the catalogue row **and leaves the
  count at zero** — and writes no stock movement at all, because a movement
  of nought still says something happened;
- submitting it twice does not introduce the part twice;
- the purchase order lands its quantity on the row the price request
  created, by SKU, rather than on a second row that happens to share a name;
- the delivery order takes out exactly what it ships, no more.

The unit is checked because it is the field that silently corrupts a
quantity: 30 metres of cable defaulted to 30 pieces looks entirely
plausible and is wrong by whatever a metre costs.
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
def why(r):
    b = J(r)
    return str(b.get("detail")
               or (b.get("errors") or [{}])[0].get("message", "")).lower()


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)
    tag = uuid.uuid4().hex[:6]

    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    s1 = await login("sales1@demo.local")
    pur = await login("purchasing@demo.local")
    adm = await login("admin@demo.local")

    async def find_item(sku=None, name=None):
        payload = J(await c.get("/inventory", headers=d,
                                params={"limit": 500, "q": sku or name}))
        rows = payload.get("items", payload if isinstance(payload, list) else [])
        for it in rows:
            if sku and it.get("sku") == sku:
                return it
            if name and (it.get("name") or "").strip().lower() == name.lower():
                return it
        return None

    async def movements(item_id):
        payload = J(await c.get(f"/inventory/{item_id}/movements", headers=d,
                                params={"limit": 200}))
        return payload if isinstance(payload, list) else payload.get("items", [])

    r = await c.post("/customers", headers=s1, json={
        "company_name": f"PT Rantai {tag}", "industry": "mining",
        "delivery_address": "SITE, KALIMANTAN"})
    cust = J(r)
    check("a customer to quote for", r.status_code in (200, 201), str(r.status_code))

    CABLE = f"Kabel Baja {tag}"
    CHAIN = f"Rantai Angkat {tag}"
    MY_SKU = f"SKU-{tag.upper()}"

    print("\n=== Sales fills in what the catalogue needs ===")
    r = await c.post("/price-requests", headers=s1, json={
        "customer_id": cust["id"],
        "items": [
            # A SKU sales already has, from the customer's own part list.
            {"description": CABLE, "qty": 30, "uom": "meter",
             "category": "Sling & Kabel", "sku": MY_SKU,
             "link": "https://example.com/kabel-baja"},
            # And one with no SKU — the series issues it on submit.
            {"description": CHAIN, "qty": 4, "uom": "set",
             "category": "Rantai"},
        ]})
    check("the request is created", r.status_code == 201, f"{r.status_code} {J(r)}")
    pr = J(r)
    lines = {i["description"]: i for i in pr["items"]}
    check("...carrying the category sales typed",
          lines[CABLE]["category"] == "Sling & Kabel", str(lines[CABLE]))
    check("...and the link", lines[CABLE]["link"] == "https://example.com/kabel-baja",
          str(lines[CABLE].get("link")))
    check("...and the SKU sales already had",
          lines[CABLE]["sku"] == MY_SKU, str(lines[CABLE].get("sku")))
    check("...with the line that has no SKU left blank until submit",
          lines[CHAIN].get("sku") is None, str(lines[CHAIN].get("sku")))

    print("\n=== The unit is one of four, not free text ===")
    r = await c.post("/price-requests", headers=s1, json={
        "customer_id": cust["id"],
        "items": [{"description": f"Salah {tag}", "qty": 1, "uom": "lusin"}]})
    check("a unit nobody counts in is refused", r.status_code == 400,
          f"{r.status_code} {J(r)}")
    check("...and the refusal names the four", "roll" in why(r), str(J(r))[:200])
    # A blank unit survives a draft — half-written requests are the normal
    # state of one somebody is still assembling — but it does not survive
    # submit, which is where the catalogue row is created with it.
    r = await c.post("/price-requests", headers=s1, json={
        "customer_id": cust["id"],
        "items": [{"description": f"Kosong {tag}", "qty": 1}]})
    check("a draft may be saved with the unit still blank",
          r.status_code == 201, f"{r.status_code} {J(r)}")
    blank = J(r)
    r = await c.post(f"/price-requests/{blank['id']}/submit", headers=s1)
    check("...but it cannot be submitted that way", r.status_code == 400,
          f"{r.status_code} {J(r)}")
    check("...and the refusal names the line and the four units",
          "roll" in why(r) and "line" in why(r), str(J(r))[:200])
    # The spellings already in the data still work — the point is one part
    # meaning one thing, not making anybody retype history.
    r = await c.post("/price-requests", headers=s1, json={
        "customer_id": cust["id"],
        "items": [{"description": f"Lama {tag}", "qty": 1, "uom": "EA"},
                  {"description": f"Lama2 {tag}", "qty": 1, "uom": "m"},
                  {"description": f"Lama3 {tag}", "qty": 1, "uom": "Rolls"}]})
    legacy = J(r)
    check("old spellings are mapped, not rejected", r.status_code == 201,
          f"{r.status_code} {legacy}")
    check("...EA becomes pcs, m becomes meter, Rolls becomes roll",
          [i["uom"] for i in legacy["items"]] == ["pcs", "meter", "roll"],
          str([i.get("uom") for i in legacy.get("items", [])]))

    print("\n=== A link has to be a link ===")
    r = await c.post("/price-requests", headers=s1, json={
        "customer_id": cust["id"],
        "items": [{"description": f"Jahat {tag}", "qty": 1, "uom": "pcs",
                   "link": "javascript:alert(1)"}]})
    check("something that is not a web address is refused",
          r.status_code == 400, f"{r.status_code} {J(r)}")
    check("...and it says what a link looks like", "http" in why(r),
          str(J(r))[:180])

    print("\n=== Submitting puts the product in — and not the quantity ===")
    before = await find_item(name=CABLE)
    check("the part is not in the catalogue yet", before is None, str(before))

    r = await c.post(f"/price-requests/{pr['id']}/submit", headers=s1)
    check("the request submits", r.status_code == 200, f"{r.status_code} {J(r)}")
    submitted = J(r)

    cable = await find_item(sku=MY_SKU)
    check("the product is now in the catalogue", cable is not None, str(cable))
    check("...under the SKU sales chose", cable and cable["sku"] == MY_SKU,
          str(cable))
    check("...with its name", cable and cable["name"] == CABLE, str(cable))
    check("...its category", cable and cable["category"] == "Sling & Kabel",
          str(cable))
    check("...its unit", cable and cable["uom"] == "meter", str(cable))
    check("...and its link", cable and cable["link"] == "https://example.com/kabel-baja",
          str(cable))
    check("**and no quantity at all** — 30 metres were wanted, not held",
          cable and cable["current_stock"] == 0, str(cable))

    rows = await movements(cable["id"])
    check("...with no stock movement written either, not even a zero",
          len(rows) == 0, str(rows)[:200])

    chain = await find_item(name=CHAIN)
    check("the line with no SKU got one from the series", chain is not None,
          str(chain))
    check("...a number, continuing the series the POs use",
          chain and (chain["sku"] or "").isdigit(), str(chain and chain["sku"]))
    check("...and it is at zero too", chain and chain["current_stock"] == 0,
          str(chain))
    back = {i["description"]: i for i in submitted["items"]}
    check("...and the request's own line now points at it",
          back[CHAIN]["sku"] == chain["sku"],
          f"{back[CHAIN].get('sku')} vs {chain['sku']}")

    print("\n=== Submitting again does not introduce it twice ===")
    r = await c.post(f"/price-requests/{pr['id']}/submit", headers=s1)
    check("a second submit is refused outright", r.status_code == 409,
          str(r.status_code))
    payload = J(await c.get("/inventory", headers=d, params={"limit": 500, "q": CABLE}))
    hits = [i for i in payload.get("items", []) if i["name"] == CABLE]
    check("...and there is still exactly one catalogue row for the part",
          len(hits) == 1, str(len(hits)))

    print("\n=== A job to buy for and ship against ===")
    # A project to ship against — the ordinary route, so the delivery order
    # is filed the way one really is.
    await c.post(f"/price-requests/{pr['id']}/price", headers=d, json={
        "items": [{"line_no": 1, "cost_price": 25_000, "basis": "unit"},
                  {"line_no": 2, "cost_price": 1_000_000, "basis": "unit"}]})
    await c.post(f"/price-requests/{pr['id']}/approve", headers=d, json={
        "items": [{"line_no": 1, "sell_price": 40_000, "basis": "unit"},
                  {"line_no": 2, "sell_price": 1_500_000, "basis": "unit"}]})
    q = J(await c.post(f"/quotations/from-price-request/{pr['id']}",
                       headers=s1))["id"]
    await c.post(f"/quotations/{q}/submit", headers=s1)
    await c.post(f"/quotations/{q}/approve", headers=d, json={"notes": ""})
    cpo = J(await c.post("/customer-pos", headers=s1, json={
        "customer_id": cust["id"], "quotation_id": q,
        "number": f"PO-CUST-{tag}",
        "items": [{"description": CABLE, "qty": 30, "uom": "meter",
                   "unit_price": 40_000, "sku": MY_SKU}],
        "is_downpayment": False}))["id"]
    await c.post(f"/quotations/{q}/won", headers=d)
    proj = J(await c.post(f"/customer-pos/{cpo}/approve", headers=d,
                          json={"notes": ""}))["project_id"]
    # A delivery order only issues once QC has passed — it states the goods
    # left in that condition.
    await c.post(f"/operation/projects/{proj}/qc", headers=adm,
                 json={"decision": "pass"})
    check("a project to deliver against", bool(proj), str(proj))

    print("\n=== Quantity comes from purchasing, on the same row ===")
    r = await c.post("/purchasing/suppliers", headers=pur, json={
        "name": f"CV Pemasok {tag}"})
    supplier = J(r)
    check("a supplier to order from", r.status_code in (200, 201),
          f"{r.status_code} {supplier}")
    r = await c.post("/purchasing/po", headers=pur, json={
        "supplier_id": supplier["id"], "project_id": proj, "total": 2_500_000,
        # The SKU rides on the order line, straight off the price request.
        "items": [{"description": CABLE, "qty": 100, "uom": "meter",
                   "unit_price": 25_000, "sku": MY_SKU}]})
    check("the purchase order is raised", r.status_code in (200, 201),
          f"{r.status_code} {J(r)}"[:180])
    po = J(r)
    check("...and waits for the director before it moves anything",
          po.get("status") == "pending_approval", str(po.get("status")))
    waiting = await find_item(sku=MY_SKU)
    check("...so the shelf is still empty while it waits",
          waiting and waiting["current_stock"] == 0, str(waiting))
    appr = [a for a in J(await c.get("/approvals", headers=d))
            if a.get("target_id") == po["id"]]
    r = await c.post(f"/approvals/{appr[0]['id']}/approve", headers=d)
    check("the director releases it", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:150])

    cable2 = await find_item(sku=MY_SKU)
    check("the goods land on the row the price request created",
          cable2 and cable2["current_stock"] == 100, str(cable2))
    payload = J(await c.get("/inventory", headers=d, params={"limit": 500, "q": CABLE}))
    hits = [i for i in payload.get("items", []) if i["name"] == CABLE]
    check("...and not on a second row that shares the name", len(hits) == 1,
          str([(i["sku"], i["current_stock"]) for i in hits]))
    rows = await movements(cable2["id"])
    check("...as one movement, referencing the order that caused it",
          len(rows) == 1 and rows[0]["reference"] == po["number"],
          str(rows)[:220])

    print("\n=== A delivery order takes out what it ships ===")
    r = await c.post(f"/operation/projects/{proj}/delivery-order", headers=d,
                     json={"items": [{"description": CABLE, "qty": 12,
                                      "uom": "meter", "sku": MY_SKU}]})
    check("the delivery order is filed", r.status_code in (200, 201),
          f"{r.status_code} {J(r)}"[:180])
    do = J(r).get("delivery_order") or J(r)

    cable3 = await find_item(sku=MY_SKU)
    check("stock falls by exactly what was shipped",
          cable3 and cable3["current_stock"] == 88, str(cable3))
    rows = await movements(cable3["id"])
    out = [m for m in rows if float(m["delta"]) < 0]
    check("...as its own movement, on the delivery order's number",
          len(out) == 1 and out[0]["reference"] == do.get("number"),
          str(rows)[:250])
    check("...for the amount the sheet says, not the amount ordered",
          out and float(out[0]["delta"]) == -12, str(out)[:150])

    print("\n=== The count is the arithmetic, and it is checkable ===")
    total = sum(float(m["delta"]) for m in rows)
    check("what is on the shelf is the sum of every movement",
          total == cable3["current_stock"], f"{total} vs {cable3['current_stock']}")

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)


asyncio.run(main())

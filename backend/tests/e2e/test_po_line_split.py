"""One price request, several vendors, a line at a time.

The chain comes from the mill that makes chain and the drag wheel from
somebody else, but a price request is costed as one document — so raising a
purchase order from it used to mean taking every line on it. Purchasing had
no way to say "this vendor is getting these two lines", short of raising the
PO and editing the items back out afterwards.

Lines are picked per order now. What this driver holds down is the half that
can go quietly wrong: the *second* PO. Prefill reports which lines an
existing order already covers, so the picker can bring them up unticked and
name the PO that has them — without that, the second order buys the first
one's goods again and nobody finds out until two lots arrive.

A cancelled order is not an order, so its lines go back in the pool.
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
                          base_url="http://t/api/v1", timeout=120)
    tag = uuid.uuid4().hex[:5]

    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    pur = await login("purchasing@demo.local")
    s1 = await login("sales1@demo.local")

    # ── a job whose price request has three costed lines ─────────────────────
    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Pisah {tag}", "industry": "mining"}))["id"]
    pr = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [
            {"description": f"CHAIN {tag}", "qty": 90, "uom": "meter"},
            {"description": f"DRAG WHEEL {tag}", "qty": 2, "uom": "pcs"},
            {"description": f"SPROCKET {tag}", "qty": 4, "uom": "pcs"},
        ]}))
    await c.post(f"/price-requests/{pr['id']}/submit", headers=s1)
    await c.post(f"/price-requests/{pr['id']}/price", headers=pur, json={
        "items": [{"line_no": 1, "cost_price": 1000, "basis": "unit"},
                  {"line_no": 2, "cost_price": 3000, "basis": "unit"},
                  {"line_no": 3, "cost_price": 500, "basis": "unit"}]})
    await c.post(f"/price-requests/{pr['id']}/approve", headers=d, json={
        "items": [{"line_no": 1, "sell_price": 2000, "basis": "unit"},
                  {"line_no": 2, "sell_price": 6000, "basis": "unit"},
                  {"line_no": 3, "sell_price": 1000, "basis": "unit"}]})
    q = J(await c.post(f"/quotations/from-price-request/{pr['id']}", headers=s1))
    await c.post(f"/quotations/{q['id']}/submit", headers=s1)
    await c.post(f"/quotations/{q['id']}/approve", headers=d, json={"notes": ""})
    cpo = J(await c.post("/customer-pos", headers=s1, json={
        "customer_id": cust, "quotation_id": q["id"], "number": f"CPO-P{tag}",
        "items": [{"description": f"CHAIN {tag}", "qty": 90, "unit_price": 2000}],
        "is_downpayment": False}))
    await c.post(f"/quotations/{q['id']}/won", headers=d)
    await c.post(f"/customer-pos/{cpo['id']}/approve", headers=d, json={"notes": ""})
    proj = J(await c.get(f"/customer-pos/{cpo['id']}", headers=d))["project_id"]
    check("the job exists", bool(proj), str(proj))

    async def prefill():
        return J(await c.get("/purchasing/po/prefill", headers=pur,
                             params={"project_id": proj}))

    pre = await prefill()
    check("prefill offers all three lines", len(pre.get("items") or []) == 3,
          str(len(pre.get("items") or [])))
    check("...costed from purchasing's own pricing",
          float(pre.get("total") or 0) == 90 * 1000 + 2 * 3000 + 4 * 500,
          str(pre.get("total")))
    check("...and none of them is spoken for yet",
          all(not (x.get("ordered_on") or []) for x in pre["items"]),
          str([(x["description"], x.get("ordered_on")) for x in pre["items"]]))

    # ── the chain goes to the mill ───────────────────────────────────────────
    print("\n── the first vendor takes one line ──")
    mill = J(await c.post("/purchasing/suppliers", headers=pur,
                          json={"name": f"PT Jinqiu {tag}"}))["id"]
    chain = next(x for x in pre["items"] if x["description"].startswith("CHAIN"))
    po1 = J(await c.post("/purchasing/po", headers=d, json={
        "supplier_id": mill, "project_id": proj,
        "price_request_id": pre["price_request_id"],
        "items": [chain], "total": chain["amount"]}))
    check("a PO is raised for the chain alone", bool(po1.get("id")), str(po1)[:140])
    check("...carrying only that line", len(po1.get("items") or []) == 1,
          str([i.get("description") for i in (po1.get("items") or [])]))
    check("...priced at that line, not the whole request",
          float(po1.get("total") or 0) == 90 * 1000.0, str(po1.get("total")))

    # ── the rest is still available, and the chain is now marked ─────────────
    print("\n── the next PO is told what is already ordered ──")
    pre2 = await prefill()
    by_desc = {x["description"]: x for x in pre2["items"]}
    check("the chain says which PO has it",
          by_desc[chain["description"]].get("ordered_on") == [po1["number"]],
          str(by_desc[chain["description"]].get("ordered_on")))
    check("...and the other two are still free",
          all(not by_desc[k].get("ordered_on") for k in by_desc
              if not k.startswith("CHAIN")),
          str([(k, v.get("ordered_on")) for k, v in by_desc.items()]))

    # ── the wheel and sprocket go elsewhere ──────────────────────────────────
    other = J(await c.post("/purchasing/suppliers", headers=pur,
                           json={"name": f"PT Roda {tag}"}))["id"]
    rest = [x for x in pre2["items"] if not x["description"].startswith("CHAIN")]
    po2 = J(await c.post("/purchasing/po", headers=d, json={
        "supplier_id": other, "project_id": proj,
        "price_request_id": pre2["price_request_id"],
        "items": rest, "total": sum(x["amount"] for x in rest)}))
    check("a second PO takes the remaining two", len(po2.get("items") or []) == 2,
          str([i.get("description") for i in (po2.get("items") or [])]))
    check("...from a different supplier", po2.get("supplier_id") != po1.get("supplier_id"),
          f"{po2.get('supplier_id')} vs {po1.get('supplier_id')}")
    check("...priced at those two", float(po2.get("total") or 0) == 2 * 3000 + 4 * 500.0,
          str(po2.get("total")))

    pre3 = await prefill()
    check("every line is now spoken for",
          all(x.get("ordered_on") for x in pre3["items"]),
          str([(x["description"], x.get("ordered_on")) for x in pre3["items"]]))
    check("...each by the right order",
          {x["description"][:5]: x["ordered_on"] for x in pre3["items"]}
          == {"CHAIN": [po1["number"]], "DRAG ": [po2["number"]],
              "SPROC": [po2["number"]]},
          str({x["description"][:5]: x.get("ordered_on") for x in pre3["items"]}))

    # ── both orders hang off the same job ────────────────────────────────────
    print("\n── the project sees both ──")
    ship = J(await c.get(f"/purchasing/po/for-project/{proj}", headers=pur))
    nums = {s.get("number") for s in (ship.get("shipments") or [])}
    check("both POs show on the project", {po1["number"], po2["number"]} <= nums,
          str(nums))

    # ── a cancelled order releases its lines ─────────────────────────────────
    print("\n── cancelling one puts its lines back ──")
    r = await c.patch(f"/purchasing/po/{po1['id']}", headers=d,
                      json={"status": "cancelled"})
    check("the first PO is cancelled", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:140])
    pre4 = await prefill()
    freed = next(x for x in pre4["items"] if x["description"].startswith("CHAIN"))
    check("...and the chain is orderable again",
          not freed.get("ordered_on"), str(freed.get("ordered_on")))
    check("...while the other two stay claimed",
          all(x.get("ordered_on") for x in pre4["items"]
              if not x["description"].startswith("CHAIN")),
          str([(x["description"], x.get("ordered_on")) for x in pre4["items"]]))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        sys.exit(1)


asyncio.run(main())

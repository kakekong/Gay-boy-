"""One item on two lines, and a supplier request whose numbers moved.

The project's order splits CONNECTING LINK into 100 + 30 to suit the
customer's own system; the customer's PO says 130 on one line. The deal check
read the 100 line alone — "not on the quotation", "100 ≠ 130" — and matched
the supplier request by line number, so a stale number set a sprocket against
the connecting link (and its Update button would have overwritten one with the
other).

* A split item is one item: its lines' quantities count together.
* The supplier request's lines are tied to the item they stand for — by number
  and name, then by name — and a split's quantity counts with them.
* Updating the supplier request keeps every item as itself, asks for the whole
  quantity on one line and ties the line to its right number from then on.
"""
import asyncio, os, sys, uuid
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123",
    STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import httpx, logging; logging.disable(logging.INFO)
TAG = uuid.uuid4().hex[:5].upper()
PASS, FAIL = [], []
def check(n, c, d=""):
    (PASS if c else FAIL).append(n); print(("  PASS " if c else "  FAIL ")+n+(f"  [{d}]" if d and not c else ""))
def J(r):
    try: return r.json()
    except Exception: return {"_": r.text[:200]}


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    from app.core.db import SessionLocal
    from app.models.purchasing import SupplierPriceRequest
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d, s1, pur = [await login(f"{x}@demo.local") for x in ("director", "sales1", "purchasing")]

    CHAIN, SPROCKET, LINK = f"ROLLER CHAIN {TAG}", f"SPROCKET RS 50X24TX1L {TAG}", f"CONNECTING LINK {TAG}"
    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Pecah {TAG}", "industry": "mining"}))["id"]
    pr = J(await c.post("/price-requests", headers=s1, json={"customer_id": cust, "items": [
        {"description": CHAIN, "qty": 10, "uom": "pcs"},
        {"description": SPROCKET, "qty": 1, "uom": "pcs"},
        {"description": LINK, "qty": 100, "uom": "pcs"}]}))["id"]
    await c.post(f"/price-requests/{pr}/submit", headers=s1)
    await c.post(f"/price-requests/{pr}/price", headers=pur, json={"items": [
        {"line_no": n, "cost_price": cost, "basis": "unit"}
        for n, cost in ((1, 300_000), (2, 50_000), (3, 10_000))]})
    await c.post(f"/price-requests/{pr}/approve", headers=d, json={"items": [
        {"line_no": n, "sell_price": sell, "basis": "unit"}
        for n, sell in ((1, 500_000), (2, 71_000), (3, 15_000))]})
    q = J(await c.post(f"/quotations/from-price-request/{pr}", headers=s1))["id"]
    await c.post(f"/quotations/{q}/submit", headers=s1)
    await c.post(f"/quotations/{q}/approve", headers=d, json={"notes": ""})
    qd = J(await c.get(f"/quotations/{q}", headers=d))
    cpo = J(await c.post("/customer-pos", headers=s1, json={
        "customer_id": cust, "quotation_id": q, "number": f"PO-{TAG}",
        "items": [{"description": i["description"],
                   "qty": 130.0 if i["description"] == LINK else float(i["qty"]),
                   "unit_price": float(i["unit_price"]), "uom": i["uom"],
                   "line_no": i["line_no"]} for i in qd["items"]],
        "is_downpayment": False}))
    await c.post(f"/quotations/{q}/won", headers=d)
    proj = J(await c.post(f"/customer-pos/{cpo['id']}/approve", headers=d,
                          json={"notes": ""}))["project_id"]
    sup = J(await c.post("/purchasing/suppliers", headers=pur, json={"name": f"PT Rantai {TAG}"}))["id"]
    spr = J(await c.post("/purchasing/price-requests", headers=pur, json={
        "price_request_id": pr, "supplier_ids": [sup]}))
    spr = (spr if isinstance(spr, list) else spr.get("created") or [spr])[0]

    # The supplier request's sprocket remembers a number that has since moved
    # (as when a line was taken off the customer request and the rest renumbered).
    async with SessionLocal() as s:
        row = await s.get(SupplierPriceRequest, uuid.UUID(spr["id"]))
        items = [dict(i) for i in row.items]
        for i in items:
            if i["description"] == SPROCKET:
                i["source_line_no"] = 4
        row.items = items
        await s.commit()

    # The project's order splits the link: 100 + 30.
    r = await c.post(f"/operation/projects/{proj}/order-change", headers=d, json={"lines": [
        {"line_no": 1}, {"line_no": 2}, {"line_no": 3},
        {"description": LINK, "qty": 30, "uom": "pcs", "sell_price": 15_000}]})
    check("the order splits the link into 100 + 30", J(r).get("status") == "applied", str(J(r))[:200])

    async def report():
        return J(await c.get("/consistency", headers=d, params={"project_id": proj}))

    def chk(rep, key):
        return next((x for x in rep.get("checks", []) if x["key"].startswith(key)), None)

    def fields(ck):
        return [(l.get("description"), f["field"], f["left"], f["right"])
                for l in ck["lines"] for f in l.get("fields", [])]

    print("\n── the split reads as one item ──")
    rep = await report()
    pq = chk(rep, "pr_quotation")
    check("request ↔ quotation: no 'line not on the quotation'",
          not any(l["change"] in ("only_left", "only_right") for l in pq["lines"]), str(pq["lines"])[:300])
    check("...just the link: 130 asked for, the quotation still says 100",
          fields(pq) == [(LINK, "qty", 130.0, 100.0)], str(fields(pq)))
    qc = chk(rep, "quotation_cpo:")
    check("quotation ↔ customer PO: the quotation's 100 against the PO's 130",
          fields(qc) == [(LINK, "qty", 100.0, 130.0)], str(qc["lines"])[:300])
    sc = chk(rep, "supplier_request:")
    check("supplier request: no sprocket set against the link",
          not any(f[1] == "description" for f in fields(sc))
          and not any(l["change"] != "differs" for l in sc["lines"]), str(sc["lines"])[:300])
    check("...only the link's quantity: 130 needed, 100 asked for",
          fields(sc) == [(LINK, "qty", 130.0, 100.0)], str(fields(sc)))

    print("\n── fixed in two presses ──")
    r = await c.post("/consistency/fix", headers=d, json={
        "project_id": proj, "check": qc["key"], "action": "use_right"})
    rep = J(r).get("report", {})
    check("the quotation takes the customer PO's 130 — and the request agrees with it",
          r.status_code == 200 and chk(rep, "pr_quotation")["lines"] == []
          and chk(rep, "quotation_cpo:")["lines"] == [], f"{r.status_code} {str(J(r))[:300]}")
    r = await c.post("/consistency/fix", headers=d, json={
        "project_id": proj, "check": sc["key"], "action": "use_left"})
    rep = J(r).get("report", {})
    check("the supplier request is brought up to date", r.status_code == 200
          and chk(rep, "supplier_request:")["lines"] == [], f"{r.status_code} {str(J(r))[:300]}")
    async with SessionLocal() as s:
        row = await s.get(SupplierPriceRequest, uuid.UUID(spr["id"]))
        by = {i["description"]: i for i in row.items}
    check("...the sprocket is still the sprocket, tied to its right line again",
          SPROCKET in by and by[SPROCKET]["qty"] == 1 and by[SPROCKET]["source_line_no"] == 2,
          str(by.get(SPROCKET)))
    check("...the link asks for all 130 on one line, no second line added",
          by[LINK]["qty"] == 130 and len(row.items) == 3, str([(i["description"], i["qty"]) for i in row.items]))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

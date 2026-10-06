"""One deal, written down several times — and a check that they still agree.

The price request, the quotation, the customer PO and the supplier documents
all describe the same order. Some copies follow each other on their own; the
ones that must not (the customer's PO is the customer's paper, a supplier
request is a list the vendor priced) are compared instead, line by line, and
the fix is one button, in either direction, under the same rules as editing
that document by hand.

Here: a won deal with a project; the director changes the request and the
won quotation follows on its own; the customer PO is left saying what it said
and is flagged; the fix is applied each way; cost corrections reach the
quotation's estimate silently; a rep's fix to an approved quotation is filed
for the director rather than applied; purchasing sees only the buy side.
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
    s2 = await login("sales2@demo.local")
    pur = await login("purchasing@demo.local")

    print("\n── a won deal with a project ──")
    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Sepakat {TAG}", "industry": "mining"}))["id"]
    pr = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust, "items": [
            {"description": f"ROLLER CHAIN {TAG}", "qty": 10, "uom": "roll"},
            {"description": f"SPROCKET {TAG}", "qty": 4, "uom": "pcs"}]}))["id"]
    await c.post(f"/price-requests/{pr}/submit", headers=s1)
    await c.post(f"/price-requests/{pr}/price", headers=pur, json={"items": [
        {"line_no": 1, "cost_price": 300_000, "basis": "unit"},
        {"line_no": 2, "cost_price": 200_000, "basis": "unit"}]})
    await c.post(f"/price-requests/{pr}/approve", headers=d, json={"items": [
        {"line_no": 1, "sell_price": 500_000, "basis": "unit"},
        {"line_no": 2, "sell_price": 400_000, "basis": "unit"}]})
    q = J(await c.post(f"/quotations/from-price-request/{pr}", headers=s1))["id"]
    await c.post(f"/quotations/{q}/submit", headers=s1)
    await c.post(f"/quotations/{q}/approve", headers=d, json={"notes": ""})
    qd = J(await c.get(f"/quotations/{q}", headers=d))
    cpo = J(await c.post("/customer-pos", headers=s1, json={
        "customer_id": cust, "quotation_id": q, "number": f"PO-{TAG}",
        "items": [{"description": i["description"], "qty": float(i["qty"]),
                   "unit_price": float(i["unit_price"]), "uom": i["uom"],
                   "line_no": i["line_no"]} for i in qd["items"]],
        "is_downpayment": False}))
    await c.post(f"/quotations/{q}/won", headers=d)
    proj = J(await c.post(f"/customer-pos/{cpo['id']}/approve", headers=d,
                          json={"notes": ""})).get("project_id")
    check("the deal is won and has a project", bool(proj), str(proj))

    async def rep(who=d, **where):
        r = await c.get("/consistency", headers=who, params=where)
        return r.status_code, J(r)

    def chk(report, key):
        return next((x for x in report.get("checks", []) if x["key"].startswith(key)), None)

    for where in ({"price_request_id": pr}, {"quotation_id": q},
                  {"customer_po_id": cpo["id"]}, {"project_id": proj}):
        code, r = await rep(**where)
        check(f"from {list(where)[0]}: the same deal, and it all agrees",
              code == 200 and r["issues"] == 0 and r["documents"]["quotation"]["id"] == q
              and r["documents"]["customer_pos"][0]["id"] == cpo["id"]
              and r["documents"]["price_request"]["id"] == pr, f"{code} {str(r)[:300]}")

    print("\n── the director changes the request: the won quotation follows ──")
    prd = J(await c.get(f"/price-requests/{pr}", headers=d))
    items = [{k: v for k, v in it.items() if k in ("line_no", "description", "qty", "uom",
                                                     "spec", "cost_price", "sell_price")}
             for it in prd["items"]]
    items[0]["qty"] = 12
    r = await c.patch(f"/price-requests/{pr}", headers=d, json={"items": items})
    check("the director's edit is accepted", r.status_code == 200, f"{r.status_code} {J(r)}")
    qd = J(await c.get(f"/quotations/{q}", headers=d))
    l1 = next(i for i in qd["items"] if i["line_no"] == 1)
    check("the won quotation follows on its own", float(l1["qty"]) == 12
          and abs(float(qd["subtotal"]) - (12 * 500_000 + 4 * 400_000)) < 1,
          f"{l1['qty']} {qd['subtotal']}")

    code, r = await rep(quotation_id=q)
    cc = chk(r, "quotation_cpo:")
    check("the customer's PO is left saying what the customer ordered — and is flagged",
          cc and cc["lines"] and cc["lines"][0]["line_no"] == 1
          and cc["lines"][0]["fields"] == [{"field": "qty", "left": 12.0, "right": 10.0}],
          str(cc)[:300])
    check("...with the request and quotation agreeing", chk(r, "pr_quotation")["lines"] == [])
    acts = {a["id"]: a for a in cc["actions"]}
    check("...and a fix offered each way", set(acts) == {"use_left", "use_right"}
          and acts["use_left"]["allowed"] and acts["use_right"]["allowed"], str(acts)[:200])

    code, r = await rep(who=s1, quotation_id=q)
    a = {x["id"]: x for x in chk(r, "quotation_cpo:")["actions"]}
    check("the rep sees it too, but the approved PO is the director's to change",
          a["use_left"]["allowed"] is False and "director" in (a["use_left"]["reason"] or "").lower(),
          str(a)[:200])
    r = await c.post("/consistency/fix", headers=s1, json={
        "quotation_id": q, "check": f"quotation_cpo:{cpo['id']}", "action": "use_left"})
    check("...and pressing it anyway is refused", r.status_code == 409, f"{r.status_code}")

    r = await c.post("/consistency/fix", headers=d, json={
        "quotation_id": q, "check": f"quotation_cpo:{cpo['id']}", "action": "use_left"})
    b = J(r)
    check("the director brings the customer PO into line", r.status_code == 200
          and b["report"]["issues"] == 0, f"{r.status_code} {str(b)[:300]}")
    po_now = J(await c.get(f"/customer-pos/{cpo['id']}", headers=d))
    check("...its quantity and total follow", float(po_now["items"][0]["qty"]) == 12
          and abs(float(po_now["total"]) - (12 * 500_000 + 4 * 400_000)) < 1,
          f"{po_now['items'][0]['qty']} {po_now['total']}")

    print("\n── or the other way: the customer's PO is right ──")
    pitems = [dict(i) for i in po_now["items"]]
    pitems[1]["unit_price"] = 380_000
    await c.patch(f"/customer-pos/{cpo['id']}", headers=d, json={"items": pitems})
    code, r = await rep(customer_po_id=cpo["id"])
    cc = chk(r, "quotation_cpo:")
    check("a price typed differently from the customer's paper is flagged",
          cc["lines"] and cc["lines"][0]["fields"][0] == {"field": "price", "left": 400_000.0,
                                                          "right": 380_000.0}, str(cc)[:250])
    r = await c.post("/consistency/fix", headers=s1, json={
        "customer_po_id": cpo["id"], "check": f"quotation_cpo:{cpo['id']}", "action": "use_right"})
    b = J(r)
    check("the rep's fix to the won quotation goes to the director, not straight in",
          r.status_code == 200 and b.get("queued") is True, f"{r.status_code} {str(b)[:200]}")
    qd = J(await c.get(f"/quotations/{q}", headers=d))
    check("...so nothing has changed yet",
          float(next(i for i in qd["items"] if i["line_no"] == 2)["unit_price"]) == 400_000)
    r = await c.post("/consistency/fix", headers=d, json={
        "customer_po_id": cpo["id"], "check": f"quotation_cpo:{cpo['id']}", "action": "use_right"})
    b = J(r)
    check("the director's applies at once", r.status_code == 200 and b.get("queued") is False
          and b["report"]["issues"] == 0, f"{r.status_code} {str(b)[:300]}")
    prd = J(await c.get(f"/price-requests/{pr}", headers=d))
    check("...and the request follows the quotation, as always",
          float(next(i for i in prd["items"] if i["line_no"] == 2)["sell_price"]) == 380_000)

    print("\n── a cost correction reaches the quotation's estimate, silently ──")
    r = await c.post(f"/price-requests/{pr}/reprice", headers=d, json={
        "items": [{"line_no": 2, "cost_price": 250_000}], "reason": "vendor raised price"})
    check("the director corrects a cost", r.status_code == 200, f"{r.status_code} {J(r)}")
    from app.core.db import SessionLocal
    from app.models.quotation import QuotationItem
    from sqlalchemy import select
    async with SessionLocal() as s:
        ce = await s.scalar(select(QuotationItem.cost_estimate).where(
            QuotationItem.quotation_id == uuid.UUID(q), QuotationItem.line_no == 2))
    check("...the won quotation's cost estimate follows", float(ce) == 250_000, str(ce))
    code, r = await rep(quotation_id=q)
    check("...and that is not a discrepancy", r["issues"] == 0, str(r["checks"])[:200])

    print("\n── an old deal that drifted before any of this ──")
    from app.models.price_request import PriceRequest
    async with SessionLocal() as s:
        p = await s.get(PriceRequest, uuid.UUID(pr))
        its = [dict(i) for i in p.items]
        its[0]["description"] = f"ROLLER CHAIN OLD WORDING {TAG}"
        p.items = its
        await s.commit()
    code, r = await rep(who=s1, price_request_id=pr)
    pq = chk(r, "pr_quotation")
    check("the request and quotation disagreeing is shown, with both wordings",
          pq["lines"] and pq["lines"][0]["fields"][0]["field"] == "description"
          and "OLD WORDING" in pq["lines"][0]["fields"][0]["left"], str(pq)[:250])
    r = await c.post("/consistency/fix", headers=s1, json={
        "price_request_id": pr, "check": "pr_quotation", "action": "use_right"})
    check("the rep makes the request match the quotation", r.status_code == 200
          and J(r)["report"]["issues"] == 0, f"{r.status_code} {str(J(r))[:200]}")

    print("\n── the buy side: purchasing's view ──")
    sup = J(await c.post("/purchasing/suppliers", headers=pur, json={"name": f"PT Pemasok {TAG}"}))["id"]
    spr = J(await c.post("/purchasing/price-requests", headers=pur, json={
        "price_request_id": pr, "supplier_ids": [sup]}))
    spr = (spr if isinstance(spr, list) else spr.get("created") or [spr])[0]
    prd = J(await c.get(f"/price-requests/{pr}", headers=d))
    items = [{k: v for k, v in it.items() if k in ("line_no", "description", "qty", "uom",
                                                     "spec", "cost_price", "sell_price")}
             for it in prd["items"]]
    items[1]["qty"] = 6
    await c.patch(f"/price-requests/{pr}", headers=d, json={"items": items})
    code, r = await rep(who=pur, price_request_id=pr)
    keys = [x["key"] for x in r.get("checks", [])]
    check("purchasing sees the supplier request, not the selling side",
          code == 200 and not any(k.startswith(("pr_quotation", "quotation_cpo")) for k in keys)
          and r["documents"]["quotation"] is None and r["documents"]["customer_pos"] == [],
          f"{code} {keys}")
    sc = chk(r, "supplier_request:")
    check("...with the quantity the vendor was asked for flagged",
          sc and any(f["field"] == "qty" and f["left"] == 6.0 and f["right"] == 4.0
                     for l in sc["lines"] for f in l.get("fields", [])), str(sc)[:300])
    r = await c.post("/consistency/fix", headers=pur, json={
        "price_request_id": pr, "check": sc["key"], "action": "use_left"})
    b = J(r)
    check("...and refreshes it in one press", r.status_code == 200
          and chk(b["report"], "supplier_request:")["lines"] == [], f"{r.status_code} {str(b)[:300]}")

    po = J(await c.post("/purchasing/po", headers=d, json={
        "supplier_id": sup, "project_id": proj, "price_request_id": pr, "po_date": "2026-10-01",
        "items": [{"description": f"SPROCKET {TAG}", "qty": 5, "uom": "pcs",
                   "unit_price": 250_000, "amount": 1_250_000,
                   "source_pr_id": pr, "source_line_no": 2}],
        "total": 1_250_000}))
    code, r = await rep(who=pur, price_request_id=pr)
    so = chk(r, "supplier_po_qty")
    check("ordering 5 of a line the job needs 6 of is pointed out",
          so and so.get("info_only") and so["lines"]
          and so["lines"][0]["fields"][0] == {"field": "qty", "left": 6.0, "right": 5.0},
          f"{str(po)[:120]} {str(so)[:250]}")

    print("\n── scope ──")
    code, _ = await rep(who=s2, quotation_id=q)
    check("another rep can't read this deal", code == 403, str(code))
    r = await c.post("/consistency/fix", headers=s2, json={
        "quotation_id": q, "check": "pr_quotation", "action": "use_right"})
    check("...or fix it", r.status_code == 403, str(r.status_code))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

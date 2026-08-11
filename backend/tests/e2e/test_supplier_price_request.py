"""Asking a supplier what they charge — the buy side of a price request.

Asked for: a separate price request to a supplier, on the purchasing page.

The sell-side PriceRequest already exists: sales lists what a customer wants,
purchasing fills a cost, the director sets the margin. The middle step was a
black box. Purchasing rang two or three vendors, typed the best number into
the cost field, and everything else — who else was asked, what they said, how
long each said delivery would take, how long the price holds — stayed in a
phone. "Why is this one so expensive" could only be answered from memory.

So: one request per supplier asked, optionally pointing at the customer price
request it is costing, and one button that turns the chosen quote into that
request's cost. What this checks beyond the CRUD:

**The cost that reaches the director is traceable.** Applying a quote writes
the supplier request's number onto every line it touched, so the number has a
document behind it rather than a memory.

**Losing quotes survive.** Comparison is the point of asking three vendors;
applying one must not delete the other two.

**A better price arriving late is not an error.** Applying a second quote
supersedes the first and moves the "this is the cost" mark with it.

**Sales cannot reach any of it, at all.** Procurement cost is the one thing
sales must never see; a document whose entire content is procurement cost
cannot be the exception. Not the list, not a row, not the compare view.

**And the customer is never named.** This document is drafted to be sent to
an outside company. It carries the goods and nothing about who wants them —
not the customer, not what we are charging them.
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

BASE = "/purchasing/price-requests"


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
    fin = await login("finance@demo.local")

    # two vendors to compare, and a customer request to cost
    sup_a = J(await c.post("/purchasing/suppliers", headers=d, json={
        "name": f"PT Baja Murah {tag}", "category": "raw_material"}))["id"]
    sup_b = J(await c.post("/purchasing/suppliers", headers=d, json={
        "name": f"PT Baja Cepat {tag}", "category": "raw_material"}))["id"]

    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Pembeli {tag}", "industry": "mining"}))["id"]
    pr = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [{"description": f"CHAIN C-2122 {tag}", "qty": 40, "uom": "meter"},
                  {"description": f"SPROCKET 24T {tag}", "qty": 4, "uom": "pcs"}]}))
    await c.post(f"/price-requests/{pr['id']}/submit", headers=s1)

    # ══ asking ═══════════════════════════════════════════════════════════════
    print("\n── purchasing asks two vendors about the same job ──")
    r = await c.post(BASE, headers=pur, json={
        "supplier_ids": [sup_a, sup_b], "price_request_id": pr["id"],
        "notes": "need it before Friday"})
    check("both requests are raised in one action", r.status_code == 201,
          f"{r.status_code} {J(r)}"[:170])
    rows = J(r)
    check("...one per supplier", len(rows) == 2, str(len(rows)))
    check("...each with its own number",
          len({x["number"] for x in rows}) == 2, str([x["number"] for x in rows]))
    check("...numbered in their own series, not the customer one",
          all(x["number"].startswith("SPR-") for x in rows),
          str([x["number"] for x in rows]))
    a, b = rows[0], rows[1]
    check("...the customer's lines were copied across",
          len(a["items"]) == 2 and f"CHAIN C-2122 {tag}" in str(a["items"]),
          str(a["items"])[:200])
    check("...saying which request it is costing",
          a["price_request_number"] == pr["number"], str(a.get("price_request_number")))
    check("...and starting as a draft", a["status"] == "draft", a["status"])

    # what goes to an outside company must not carry the customer
    body = str(J(await c.get(f"{BASE}/{a['id']}", headers=pur)))
    check("the document never names the customer",
          f"PT Pembeli {tag}" not in body, body[:250])
    check("...and carries no selling price", "sell_price" not in body, body[:250])

    # ══ sending, and answering ═══════════════════════════════════════════════
    print("\n── one of them answers ──")
    r = await c.post(f"{BASE}/{a['id']}/send", headers=pur)
    check("it can be marked sent", r.status_code == 200 and J(r)["status"] == "sent",
          f"{r.status_code} {J(r)}"[:150])
    check("...with the time recorded", J(r)["sent_at"] is not None)
    r = await c.post(f"{BASE}/{a['id']}/send", headers=pur)
    check("...and sending twice is refused rather than restamping",
          r.status_code == 409, str(r.status_code))

    r = await c.post(f"{BASE}/{a['id']}/quote", headers=pur, json={
        "items": [{"line_no": 1, "quoted_price": 1_800_000, "basis": "unit",
                   "lead_days": 30},
                  {"line_no": 2, "quoted_price": 4_000_000, "basis": "total"}],
        "quoted_lead_days": 30, "notes": "freight not included"})
    check("their answer is recorded", r.status_code == 200, f"{r.status_code} {J(r)}"[:150])
    got = J(r)
    check("...moving it to quoted", got["status"] == "quoted", got["status"])
    check("...every line answered", got["lines_quoted"] == 2, str(got["lines_quoted"]))
    line2 = next(i for i in got["items"] if i["line_no"] == 2)
    check("...a price quoted for the whole line is stored per unit",
          float(line2["quoted_price"]) == 1_000_000, str(line2["quoted_price"]))
    check("...so the basket totals what it should",
          float(got["quoted_total"]) == 1_800_000 * 40 + 1_000_000 * 4,
          str(got["quoted_total"]))
    check("...and what they said is kept", "freight not included" in (got["notes"] or ""),
          str(got["notes"]))

    # the second vendor, dearer
    await c.post(f"{BASE}/{b['id']}/send", headers=pur)
    await c.post(f"{BASE}/{b['id']}/quote", headers=pur, json={
        "items": [{"line_no": 1, "quoted_price": 2_100_000, "basis": "unit"},
                  {"line_no": 2, "quoted_price": 1_200_000, "basis": "unit"}],
        "quoted_lead_days": 14})

    cmp_ = J(await c.get(f"{BASE}/for-price-request/{pr['id']}/compare", headers=pur))
    check("both answers sit side by side", len(cmp_["requests"]) == 2,
          str(len(cmp_.get("requests", []))))
    check("...cheapest first",
          cmp_["requests"][0]["number"] == a["number"],
          str([(x["number"], x["quoted_total"]) for x in cmp_["requests"]]))

    # ══ making it the cost ═══════════════════════════════════════════════════
    print("\n── the cheaper one becomes the cost ──")
    r = await c.post(f"{BASE}/{a['id']}/apply", headers=pur)
    check("the quote is applied", r.status_code == 200, f"{r.status_code} {J(r)}"[:170])
    check("...both lines", J(r)["applied_lines"] == 2, str(J(r).get("applied_lines")))
    costed = J(await c.get(f"/price-requests/{pr['id']}", headers=pur))
    check("...the price request now carries that cost",
          float(costed["items"][0]["cost_price"]) == 1_800_000,
          str(costed["items"][0].get("cost_price")))
    check("...and the second line too",
          float(costed["items"][1]["cost_price"]) == 1_000_000,
          str(costed["items"][1].get("cost_price")))
    check("...it moved to the director", costed["status"] == "pending_director",
          costed["status"])
    check("...with the quote it came from named on the line",
          costed["items"][0].get("cost_source") == a["number"],
          str(costed["items"][0].get("cost_source")))
    check("...and named in the notes too", a["number"] in (costed["notes"] or ""),
          str(costed["notes"])[:200])

    after_a = J(await c.get(f"{BASE}/{a['id']}", headers=pur))
    check("the taken quote is marked as the one used",
          after_a["applied_at"] is not None and after_a["status"] == "closed",
          f"{after_a['applied_at']} {after_a['status']}")
    after_b = J(await c.get(f"{BASE}/{b['id']}", headers=pur))
    check("the losing quote is still on file", after_b["status"] == "quoted",
          after_b["status"])
    check("...and is not marked as used", after_b["applied_at"] is None)

    print("\n── the dearer vendor drops their price ──")
    await c.post(f"{BASE}/{b['id']}/quote", headers=pur, json={
        "items": [{"line_no": 1, "quoted_price": 1_500_000, "basis": "unit"},
                  {"line_no": 2, "quoted_price": 900_000, "basis": "unit"}]})
    r = await c.post(f"{BASE}/{b['id']}/apply", headers=pur)
    check("a better price arriving late can be applied too",
          r.status_code == 200, f"{r.status_code} {J(r)}"[:170])
    recost = J(await c.get(f"/price-requests/{pr['id']}", headers=pur))
    check("...and the cost moves with it",
          float(recost["items"][0]["cost_price"]) == 1_500_000,
          str(recost["items"][0].get("cost_price")))
    check("...the line now points at the new quote",
          recost["items"][0].get("cost_source") == b["number"],
          str(recost["items"][0].get("cost_source")))
    check("...and only one quote claims to be the cost",
          sum(1 for x in J(await c.get(BASE, headers=pur,
                                       params={"price_request_id": pr["id"]}))
              if x["applied_at"]) == 1)

    # ══ standing alone ═══════════════════════════════════════════════════════
    print("\n── an enquiry with no deal behind it ──")
    r = await c.post(BASE, headers=pur, json={
        "supplier_ids": [sup_a],
        "items": [{"line_no": 1, "description": f"BEARING 6205 {tag}",
                   "qty": 100, "uom": "pcs"}]})
    check("purchasing can ask without a price request", r.status_code == 201,
          f"{r.status_code} {J(r)}"[:170])
    solo = J(r)[0]
    check("...and it says so", solo["price_request_number"] is None,
          str(solo.get("price_request_number")))
    r = await c.patch(f"{BASE}/{solo['id']}", headers=pur, json={
        "items": [{"line_no": 1, "description": f"BEARING 6206 {tag}",
                   "qty": 120, "uom": "pcs"}]})
    check("...its lines can be corrected while it is a draft",
          r.status_code == 200 and J(r)["items"][0]["qty"] == 120,
          f"{r.status_code} {J(r)}"[:150])
    r = await c.post(f"{BASE}/{solo['id']}/apply", headers=pur)
    check("...but it cannot be applied to anything", r.status_code == 409,
          str(r.status_code))
    r = await c.patch(f"{BASE}/{a['id']}", headers=pur, json={
        "items": [{"line_no": 1, "description": "something else", "qty": 1}]})
    check("a request copied from a price request refuses line edits",
          r.status_code == 409, f"{r.status_code} {J(r)}"[:150])

    # ══ what it refuses ══════════════════════════════════════════════════════
    print("\n── the refusals ──")
    for who, hh in [("sales", s1), ("finance", fin)]:
        r = await c.get(BASE, headers=hh)
        check(f"{who} cannot even list them", r.status_code == 403, str(r.status_code))
        r = await c.get(f"{BASE}/{a['id']}", headers=hh)
        check(f"...nor open one ({who})", r.status_code == 403, str(r.status_code))
        r = await c.post(BASE, headers=hh, json={"supplier_ids": [sup_a],
                                                 "items": [{"line_no": 1, "description": "x"}]})
        check(f"...nor raise one ({who})", r.status_code == 403, str(r.status_code))
        r = await c.get(f"{BASE}/for-price-request/{pr['id']}/compare", headers=hh)
        check(f"...nor read the comparison ({who})", r.status_code == 403,
              str(r.status_code))

    r = await c.post(BASE, headers=pur, json={"supplier_ids": []})
    check("asking nobody is refused", r.status_code == 400, str(r.status_code))
    r = await c.post(BASE, headers=pur, json={"supplier_ids": [sup_a, sup_a],
                                              "items": [{"line_no": 1, "description": "x"}]})
    check("...and asking the same supplier twice", r.status_code == 400,
          str(r.status_code))
    r = await c.post(BASE, headers=pur, json={"supplier_ids": [sup_a]})
    check("...and asking about nothing", r.status_code == 400, str(r.status_code))
    r = await c.post(BASE, headers=pur, json={"supplier_ids": [str(uuid.uuid4())],
                                              "items": [{"line_no": 1, "description": "x"}]})
    check("a supplier that does not exist is a 404", r.status_code == 404,
          str(r.status_code))

    r = await c.post(f"{BASE}/{solo['id']}/apply", headers=pur)
    check("a quote that has not been given cannot be applied",
          r.status_code == 409, str(r.status_code))

    # deleting: drafts only
    r = await c.delete(f"{BASE}/{a['id']}", headers=pur)
    check("a request that has been answered can't be deleted away",
          r.status_code == 409, str(r.status_code))
    r = await c.delete(f"{BASE}/{solo['id']}", headers=pur)
    check("...a draft raised by mistake can", r.status_code == 204, str(r.status_code))
    check("...and it is gone",
          (await c.get(f"{BASE}/{solo['id']}", headers=pur)).status_code == 404)

    # closing
    r = await c.post(f"{BASE}/{a['id']}/close", headers=pur,
                     json={"reason": "superseded by the cheaper quote"})
    check("a request can be filed away with a reason", r.status_code == 200,
          str(r.status_code))
    check("...and the reason is kept",
          "superseded" in (J(r)["notes"] or ""), str(J(r)["notes"])[:150])

    # ══ once the director has priced it ══════════════════════════════════════
    print("\n── after the director has decided ──")
    await c.post(f"/price-requests/{pr['id']}/approve", headers=d, json={
        "items": [{"line_no": 1, "sell_price": 2_500_000, "basis": "unit"},
                  {"line_no": 2, "sell_price": 1_500_000, "basis": "unit"}]})
    late = J(await c.post(BASE, headers=pur, json={
        "supplier_ids": [sup_a], "price_request_id": pr["id"]}))[0]
    await c.post(f"{BASE}/{late['id']}/quote", headers=pur, json={
        "items": [{"line_no": 1, "quoted_price": 1, "basis": "unit"}]})
    r = await c.post(f"{BASE}/{late['id']}/apply", headers=pur)
    check("an approved price request can't be re-costed underneath the director",
          r.status_code == 409, f"{r.status_code} {J(r)}"[:150])
    check("...and says why", "approved" in str(J(r)).lower(), str(J(r))[:150])

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        sys.exit(1)


asyncio.run(main())

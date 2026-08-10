"""Changing a price or a cost after the request has settled.

Asked for: the director should be able to change the price *and* the cost on
a price request.

Until now both numbers could only be set on the way past. Purchasing typed
the cost while the request sat in `pending_purchasing`; the director set the
selling price in the same motion as approving it; and from `approved` onwards
neither could be touched by anybody. But suppliers revise quotes, rates move,
and a price gets agreed on the phone — and the price request is what every
downstream document reads from, so a stale one quietly misprices the job.

The care is in what it does to work already built on top:

  the two prices are independent   sending a new cost must not require
                                   re-typing the selling price, or somebody
                                   will re-type it wrong

  a draft quotation follows        its prices are locked to this request by
                                   design; leaving it stale would make the
                                   lock a lie

  a sent one does not              that is a statement already made to the
                                   customer. It is corrected by revising the
                                   quotation, not by editing the number
                                   underneath it

  it is written down               who, when, from what, to what, and why —
                                   on the request itself, where the next
                                   person to ask is already looking
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
    s1 = await login("sales1@demo.local")
    pur = await login("purchasing@demo.local")
    mgr = await login("manager@demo.local")

    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Harga {tag}", "industry": "mining"}))["id"]

    async def approved_pr(cost=1_000_000, sell=1_400_000, qty=10) -> str:
        pr = J(await c.post("/price-requests", headers=s1, json={
            "customer_id": cust,
            "items": [{"description": f"CHAIN {tag}-{uuid.uuid4().hex[:4]}",
                       "qty": qty, "uom": "meter"},
                      {"description": f"SPROCKET {tag}-{uuid.uuid4().hex[:4]}",
                       "qty": 2, "uom": "pcs"}]}))["id"]
        await c.post(f"/price-requests/{pr}/submit", headers=s1)
        await c.post(f"/price-requests/{pr}/price", headers=pur, json={
            "items": [{"line_no": 1, "cost_price": cost, "basis": "unit"},
                      {"line_no": 2, "cost_price": 500_000, "basis": "unit"}]})
        await c.post(f"/price-requests/{pr}/approve", headers=d, json={
            "items": [{"line_no": 1, "sell_price": sell, "basis": "unit"},
                      {"line_no": 2, "sell_price": 700_000, "basis": "unit"}]})
        return pr

    def line(pr_json, n):
        return next(x for x in pr_json["items"] if x["line_no"] == n)

    # ══ the ask ══════════════════════════════════════════════════════════════
    print("\n── the director changes both numbers on an approved request ──")
    pr = await approved_pr()
    before = J(await c.get(f"/price-requests/{pr}", headers=d))
    check("it starts approved with the agreed figures",
          before["status"] == "approved"
          and line(before, 1)["cost_price"] == 1_000_000
          and line(before, 1)["sell_price"] == 1_400_000,
          str(line(before, 1)))

    r = await c.post(f"/price-requests/{pr}/reprice", headers=d, json={
        "items": [{"line_no": 1, "cost_price": 1_150_000, "sell_price": 1_600_000}],
        "reason": "supplier revised the quote"})
    out = J(r)
    check("the director can reprice it", r.status_code == 200,
          f"{r.status_code} {out}"[:160])
    check("...and it says one line moved", out.get("changed_lines") == 1,
          str(out.get("changed_lines")))
    now = J(await c.get(f"/price-requests/{pr}", headers=d))
    check("the cost is the new cost", line(now, 1)["cost_price"] == 1_150_000,
          str(line(now, 1)["cost_price"]))
    check("the price is the new price", line(now, 1)["sell_price"] == 1_600_000,
          str(line(now, 1)["sell_price"]))
    check("...the line total follows it",
          line(now, 1)["line_total"] == 16_000_000, str(line(now, 1)["line_total"]))
    check("...and the untouched line is untouched",
          line(now, 2)["cost_price"] == 500_000 and line(now, 2)["sell_price"] == 700_000,
          str(line(now, 2)))
    check("...the request is still approved, not knocked back to draft",
          now["status"] == "approved", now["status"])

    # ══ the two prices move independently ════════════════════════════════════
    print("\n── one without the other ──")
    pr2 = await approved_pr()
    await c.post(f"/price-requests/{pr2}/reprice", headers=d, json={
        "items": [{"line_no": 1, "cost_price": 1_200_000}],
        "reason": "freight went up"})
    got = J(await c.get(f"/price-requests/{pr2}", headers=d))
    check("a cost-only change moves the cost",
          line(got, 1)["cost_price"] == 1_200_000, str(line(got, 1)["cost_price"]))
    check("...and leaves the selling price alone",
          line(got, 1)["sell_price"] == 1_400_000, str(line(got, 1)["sell_price"]))
    await c.post(f"/price-requests/{pr2}/reprice", headers=d, json={
        "items": [{"line_no": 1, "sell_price": 1_800_000}],
        "reason": "customer agreed a higher price"})
    got = J(await c.get(f"/price-requests/{pr2}", headers=d))
    check("a price-only change moves the price",
          line(got, 1)["sell_price"] == 1_800_000, str(line(got, 1)["sell_price"]))
    check("...and leaves the cost where the last change put it",
          line(got, 1)["cost_price"] == 1_200_000, str(line(got, 1)["cost_price"]))

    # A figure can be entered as the line total instead of per unit, the same
    # way it can when purchasing and the director first enter it.
    await c.post(f"/price-requests/{pr2}/reprice", headers=d, json={
        "items": [{"line_no": 1, "sell_price": 20_000_000, "sell_basis": "total"}],
        "reason": "quoted as a lot price"})
    got = J(await c.get(f"/price-requests/{pr2}", headers=d))
    check("a total-basis figure is stored per unit",
          line(got, 1)["sell_price"] == 2_000_000, str(line(got, 1)["sell_price"]))

    # ══ who may ══════════════════════════════════════════════════════════════
    print("\n── nobody else ──")
    pr3 = await approved_pr()
    for who, headers in [("sales", s1), ("purchasing", pur), ("the manager", mgr)]:
        r = await c.post(f"/price-requests/{pr3}/reprice", headers=headers, json={
            "items": [{"line_no": 1, "sell_price": 1}], "reason": "no"})
        check(f"{who} cannot reprice", r.status_code == 403, str(r.status_code))
    still = J(await c.get(f"/price-requests/{pr3}", headers=d))
    check("...and nothing moved", line(still, 1)["sell_price"] == 1_400_000,
          str(line(still, 1)["sell_price"]))

    r = await c.post(f"/price-requests/{pr3}/reprice", headers=d, json={
        "items": [{"line_no": 1, "sell_price": 2_000_000}], "reason": "   "})
    check("even the director must say why", r.status_code == 400, str(r.status_code))
    r = await c.post(f"/price-requests/{pr3}/reprice", headers=d, json={
        "items": [{"line_no": 99, "sell_price": 1}], "reason": "typo"})
    check("a line that does not exist is refused", r.status_code == 400, str(r.status_code))
    r = await c.post(f"/price-requests/{pr3}/reprice", headers=d, json={
        "items": [{"line_no": 1, "sell_price": 1_400_000}], "reason": "same number"})
    check("re-entering the same figure is not an event",
          J(r).get("changed_lines") == 0, str(J(r).get("changed_lines")))
    check("...and writes nothing to the history",
          not J(await c.get(f"/price-requests/{pr3}", headers=d))["price_history"],
          str(J(await c.get(f"/price-requests/{pr3}", headers=d))["price_history"])[:120])

    # ══ what it does to the quotation ════════════════════════════════════════
    print("\n── a draft quotation is brought back into line ──")
    pr4 = await approved_pr()
    q = J(await c.post(f"/quotations/from-price-request/{pr4}", headers=s1))
    check("the quotation starts on the approved price",
          float(q["items"][0]["unit_price"]) == 1_400_000,
          str(q["items"][0]["unit_price"]))
    before_total = float(q["total"])
    out = J(await c.post(f"/price-requests/{pr4}/reprice", headers=d, json={
        "items": [{"line_no": 1, "sell_price": 1_900_000}],
        "reason": "renegotiated"}))
    check("the response says the draft was updated",
          (out.get("quotation") or {}).get("action") == "updated", str(out.get("quotation")))
    q2 = J(await c.get(f"/quotations/{q['id']}", headers=d))
    check("...and the quotation really carries the new price",
          float(q2["items"][0]["unit_price"]) == 1_900_000,
          str(q2["items"][0]["unit_price"]))
    check("...with the total recalculated",
          float(q2["total"]) > before_total, f"{q2['total']} vs {before_total}")
    check("...and it is still a draft", q2["status"] == "draft", q2["status"])

    print("\n── one that has gone out is left alone ──")
    pr5 = await approved_pr()
    q5 = J(await c.post(f"/quotations/from-price-request/{pr5}", headers=s1))
    await c.post(f"/quotations/{q5['id']}/submit", headers=d)
    await c.post(f"/quotations/{q5['id']}/approve", headers=d, json={})
    sent = J(await c.get(f"/quotations/{q5['id']}", headers=d))
    check("the quotation is approved", sent["status"] == "approved", sent["status"])
    out = J(await c.post(f"/price-requests/{pr5}/reprice", headers=d, json={
        "items": [{"line_no": 1, "sell_price": 2_500_000}],
        "reason": "price moved after the quote went out"}))
    check("the response says so rather than pretending",
          (out.get("quotation") or {}).get("action") == "left_alone",
          str(out.get("quotation")))
    after = J(await c.get(f"/quotations/{q5['id']}", headers=d))
    check("...the approved quotation is untouched",
          float(after["items"][0]["unit_price"]) == 1_400_000,
          str(after["items"][0]["unit_price"]))
    check("...and still approved", after["status"] == "approved", after["status"])
    pr5_now = J(await c.get(f"/price-requests/{pr5}", headers=d))
    check("...while the price request does carry the new figure",
          line(pr5_now, 1)["sell_price"] == 2_500_000,
          str(line(pr5_now, 1)["sell_price"]))

    # ══ the trail ════════════════════════════════════════════════════════════
    print("\n── what changed, and why ──")
    hist = J(await c.get(f"/price-requests/{pr}", headers=d))["price_history"]
    check("the change is on the request itself", len(hist) == 1, str(len(hist)))
    h = hist[0]
    check("...with the reason", h["reason"] == "supplier revised the quote", str(h.get("reason")))
    check("...and who made it", "Director" in (h.get("by") or ""), str(h.get("by")))
    check("...from what, to what",
          h["lines"][0]["cost_from"] == 1_000_000 and h["lines"][0]["cost_to"] == 1_150_000
          and h["lines"][0]["sell_from"] == 1_400_000 and h["lines"][0]["sell_to"] == 1_600_000,
          str(h["lines"][0]))
    check("...and the status it was in at the time",
          h.get("status_then") == "approved", str(h.get("status_then")))
    many = J(await c.get(f"/price-requests/{pr2}", headers=d))["price_history"]
    check("three separate changes are three separate entries", len(many) == 3, str(len(many)))

    print("\n── and it respects who may see what ──")
    ph = J(await c.get(f"/price-requests/{pr}", headers=pur))["price_history"]
    check("purchasing sees the cost change", "cost_to" in ph[0]["lines"][0], str(ph[0]["lines"][0]))
    check("...and never the selling price", "sell_to" not in ph[0]["lines"][0],
          str(ph[0]["lines"][0]))
    sh = J(await c.get(f"/price-requests/{pr}", headers=s1))["price_history"]
    check("sales sees the price change", "sell_to" in sh[0]["lines"][0], str(sh[0]["lines"][0]))
    check("...and never the cost", "cost_to" not in sh[0]["lines"][0], str(sh[0]["lines"][0]))

    audit = J(await c.get("/audit", headers=d, params={"entity": "price_request",
                                                       "limit": 50}))
    rows = audit if isinstance(audit, list) else audit.get("data", [])
    check("and the audit log has it too",
          any(a.get("action") == "reprice" for a in rows))

    # ══ it works before approval as well ═════════════════════════════════════
    print("\n── and at any point in the pipeline ──")
    pr6 = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [{"description": f"BELT {tag}", "qty": 5, "uom": "meter"}]}))["id"]
    await c.post(f"/price-requests/{pr6}/submit", headers=s1)
    r = await c.post(f"/price-requests/{pr6}/reprice", headers=d, json={
        "items": [{"line_no": 1, "cost_price": 300_000}],
        "reason": "known price, no need to wait for purchasing"})
    check("a request still waiting on purchasing can be priced",
          r.status_code == 200, f"{r.status_code} {J(r)}"[:140])
    got = J(await c.get(f"/price-requests/{pr6}", headers=d))
    check("...the cost lands", line(got, 1)["cost_price"] == 300_000,
          str(line(got, 1)["cost_price"]))
    check("...and it stays where it was in the pipeline",
          got["status"] == "pending_purchasing", got["status"])

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        sys.exit(1)


asyncio.run(main())

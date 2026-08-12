"""Negotiation revisions on a price request.

A submitted request is a live commercial document, but negotiations move: the
customer trims a quantity, swaps a spec, adds a line. Sales can now propose
that change instead of being stuck, the director decides, and the whole
exchange is on the record.

Three rules carry the design, and each is a way this could go wrong:

* **The cap counts what was applied, not what was asked.** A rejected proposal
  changed nothing, so it must not spend one of the three — otherwise the rep is
  punished for the director's decision.
* **One at a time.** Two pending proposals against the same request would let
  the second silently overwrite the first on approval.
* **Rejection changes nothing.** Not the lines, not the notes, not the prices.
"""
import asyncio, os, sys, uuid
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123", STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import httpx, logging; logging.disable(logging.INFO)
PASS, FAIL = [], []
def check(n,c,d=""):
    (PASS if c else FAIL).append(n); print(("  PASS " if c else "  FAIL ")+n+(f"  [{d}]" if d and not c else ""))
def J(r):
    try: return r.json()
    except: return {"_":r.text[:200]}
async def login(c,e):
    r=await c.post("/auth/login",json={"email":e,"password":"test-pass-123"})
    return {"Authorization":f"Bearer {r.json()['access_token']}"}

def line(pr, desc):
    return next((x for x in pr.get("items", []) if x["description"] == desc), None)


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=90)
    d = await login(c, "director@demo.local");  s1 = await login(c, "sales1@demo.local")
    s2 = await login(c, "sales2@demo.local");   pu = await login(c, "purchasing@demo.local")
    tag = uuid.uuid4().hex[:5]
    G, C, S = f"Gearbox {tag}", f"Coupling {tag}", f"Seal {tag}"

    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Nego {tag}", "industry": "mining"}))["id"]
    pr = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [{"description": G, "qty": 2, "uom": "pcs"},
                  {"description": C, "qty": 4, "uom": "pcs"}]}))["id"]

    # ── 1. a draft doesn't need any of this ──────────────────────────────────
    r = await c.post(f"/price-requests/{pr}/revise", headers=s1, json={
        "items": [{"description": G, "qty": 3, "uom": "pcs"}]})
    check("a draft is edited directly, not revised", r.status_code == 409, str(r.status_code))

    await c.post(f"/price-requests/{pr}/submit", headers=s1)
    await c.post(f"/price-requests/{pr}/price", headers=pu, json={"items": [
        {"line_no": 1, "cost_price": 5_000_000, "basis": "unit"},
        {"line_no": 2, "cost_price": 250_000, "basis": "unit"}]})

    # ── 2. sales proposes; it waits for the director ─────────────────────────
    r = await c.post(f"/price-requests/{pr}/revise", headers=s1, json={
        "items": [{"description": G, "qty": 5, "uom": "pcs"},
                  {"description": C, "qty": 4, "uom": "pcs"}],
        "reason": "Customer raised the gearbox count to 5"})
    check("sales can propose a revision on a submitted request", r.status_code == 200, J(r))
    check("it reports how many are left", J(r).get("revisions_left") == 3, str(J(r).get("revisions_left")))
    req1 = J(r).get("approval_request_id")

    live = J(await c.get(f"/price-requests/{pr}", headers=s1))
    check("nothing changed while it waits", (line(live, G) or {}).get("qty") == 2,
          str(line(live, G)))

    r = await c.post(f"/price-requests/{pr}/revise", headers=s1, json={
        "items": [{"description": G, "qty": 9, "uom": "pcs"}]})
    check("a second proposal is refused while one is pending", r.status_code == 409,
          str(r.status_code))

    # It lands in the director's queue like everything else.
    q = J(await c.get("/approvals", headers=d))
    mine = [a for a in q if str(a.get("id")) == str(req1)] if isinstance(q, list) else []
    check("it appears in the director's approval queue", len(mine) == 1, str(len(mine)))
    check("...with a reason that names the request",
          "Revision 1" in (mine[0].get("reason") or "") if mine else False,
          str(mine[0].get("reason") if mine else None))

    # ── 3. approving applies it, and keeps the costing ───────────────────────
    r = await c.post(f"/approvals/{req1}/approve", headers=d)
    check("the director approves it", r.status_code == 200, J(r))
    live = J(await c.get(f"/price-requests/{pr}", headers=d))
    check("the quantity is now the proposed one", (line(live, G) or {}).get("qty") == 5,
          str(line(live, G)))
    check("the cost purchasing entered survived",
          (line(live, G) or {}).get("cost_price") == 5_000_000, str(line(live, G)))

    log = J(await c.get(f"/price-requests/{pr}/revisions", headers=s1))
    check("the log records it as approved",
          (log.get("revisions") or [{}])[0].get("status") == "approved", str(log)[:200])
    check("...naming who asked", (log["revisions"][0].get("requested_by_name")) == "Sales One",
          str(log["revisions"][0])[:160])
    check("...and who decided", bool(log["revisions"][0].get("decided_by_name")),
          str(log["revisions"][0])[:200])
    check("the log says what actually changed",
          any(ch.get("kind") == "qty" and ch.get("to") == 5
              for ch in log["revisions"][0].get("changes", [])),
          str(log["revisions"][0].get("changes")))
    check("one revision is used", log.get("applied") == 1 and log.get("left") == 2, str(log)[:120])

    # ── 4. a rejected proposal changes nothing and costs nothing ─────────────
    r = J(await c.post(f"/price-requests/{pr}/revise", headers=s1, json={
        "items": [{"description": G, "qty": 99, "uom": "pcs"}],
        "reason": "typo, ignore"}))
    req2 = r.get("approval_request_id")
    await c.post(f"/approvals/{req2}/reject", headers=d, params={"notes": "not agreed"})
    live = J(await c.get(f"/price-requests/{pr}", headers=d))
    check("a rejected revision leaves the lines alone",
          (line(live, G) or {}).get("qty") == 5, str(line(live, G)))
    check("...and does not drop the other line", line(live, C) is not None,
          str([x["description"] for x in live.get("items", [])]))
    log = J(await c.get(f"/price-requests/{pr}/revisions", headers=s1))
    check("a rejection does NOT spend one of the three",
          log.get("applied") == 1 and log.get("left") == 2, str(log)[:140])
    check("but it is still on the record",
          any(x.get("status") == "rejected" for x in log.get("revisions", [])),
          str([x.get("status") for x in log.get("revisions", [])]))

    # ── 5. the cap ───────────────────────────────────────────────────────────
    for i, qty in enumerate((6, 7), start=2):
        rr = J(await c.post(f"/price-requests/{pr}/revise", headers=s1, json={
            "items": [{"description": G, "qty": qty, "uom": "pcs"}],
            "reason": f"round {i}"}))
        await c.post(f"/approvals/{rr['approval_request_id']}/approve", headers=d)
    log = J(await c.get(f"/price-requests/{pr}/revisions", headers=s1))
    check("three applied revisions uses the budget",
          log.get("applied") == 3 and log.get("left") == 0, str(log)[:140])

    r = await c.post(f"/price-requests/{pr}/revise", headers=s1, json={
        "items": [{"description": G, "qty": 8, "uom": "pcs"}], "reason": "one more"})
    check("a fourth revision is refused", r.status_code == 409, str(r.status_code))
    check("...and says why", "limit" in r.text.lower(), r.text[:140])

    # ── 6. scoping ───────────────────────────────────────────────────────────
    r = await c.post(f"/price-requests/{pr}/revise", headers=s2, json={
        "items": [{"description": G, "qty": 1}]})
    check("another rep cannot revise someone else's request",
          r.status_code in (403, 404), str(r.status_code))
    # ── 7. purchasing correcting a cost after the fact ───────────────────────
    # Asked for: purchasing can edit a request past submission, and every edit
    # goes to the director. Their edit is the cost — and it must not be paid
    # for out of the sales team's three negotiation revisions, which are
    # already spent by this point in the driver. That is the whole test: the
    # request above is capped, and this still gets through.
    print("\n── purchasing corrects a cost, the director signs it ──")
    before = J(await c.get(f"/price-requests/{pr}", headers=pu))
    old_cost = (line(before, G) or {}).get("cost_price")
    r = await c.post(f"/price-requests/{pr}/revise", headers=pu, json={
        "items": [{"description": G, "qty": 7, "uom": "pcs",
                   "cost_price": 6_500_000, "cost_basis": "unit"},
                  {"description": C, "qty": 4, "uom": "pcs"}],
        "reason": "Supplier raised the gearbox price"})
    check("purchasing can revise a submitted request", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:160])
    check("...even though sales has used every negotiation revision",
          J(r).get("kind") == "cost", str(J(r).get("kind")))
    check("...and it does not claim to spend one",
          J(r).get("revisions_left") is None, str(J(r).get("revisions_left")))
    cost_req = J(r).get("approval_request_id")

    live = J(await c.get(f"/price-requests/{pr}", headers=pu))
    check("nothing moves until the director says so",
          (line(live, G) or {}).get("cost_price") == old_cost,
          f"{(line(live, G) or {}).get('cost_price')} vs {old_cost}")

    r = await c.post(f"/price-requests/{pr}/revise", headers=pu, json={
        "items": [{"description": G, "qty": 7, "cost_price": 1}]})
    check("...and one at a time, same as everyone", r.status_code == 409,
          str(r.status_code))

    prev = J(await c.get(f"/approvals/{cost_req}/preview", headers=d))
    check("the director's preview names it a cost correction",
          any("cost" in str(f.get("value", "")).lower()
              or "cost" in str(f.get("label", "")).lower()
              for f in (prev.get("fields") or [])), str(prev.get("fields"))[:200])
    check("...and shows the new cost against the old",
          any(i.get("unit_price") == 6_500_000 and i.get("was_unit_price") == old_cost
              for i in (prev.get("items") or [])), str(prev.get("items"))[:240])

    r = await c.post(f"/approvals/{cost_req}/approve", headers=d)
    check("the director approves it", r.status_code == 200, str(r.status_code))
    after = J(await c.get(f"/price-requests/{pr}", headers=pu))
    check("...and the new cost lands", (line(after, G) or {}).get("cost_price") == 6_500_000,
          str(line(after, G)))

    log = J(await c.get(f"/price-requests/{pr}/revisions", headers=pu))
    check("the cost revision is on the record as its own kind",
          any(rv.get("kind") == "cost" and rv.get("status") == "approved"
              for rv in log.get("revisions", [])), str(log.get("revisions"))[-240:])
    check("...and still nothing is left of the negotiation budget",
          log.get("applied") == 3 and log.get("left") == 0, str(log)[:140])
    check("...with the cost movement spelled out for whoever may see costs",
          any(ch.get("kind") == "cost" and ch.get("to") == 6_500_000
              for rv in log.get("revisions", []) for ch in (rv.get("changes") or [])),
          str(log.get("revisions"))[-300:])

    seen = J(await c.get(f"/price-requests/{pr}/revisions", headers=s1))
    check("sales is not shown the cost that moved",
          not any(ch.get("kind") == "cost"
                  for rv in seen.get("revisions", []) for ch in (rv.get("changes") or [])),
          str(seen.get("revisions"))[-200:])

    # ── 8. a second request, with its budget intact ──────────────────────────
    # The one above has spent its three revisions, which makes it the wrong
    # place to ask what happens to a line nobody touched (earlier rounds had
    # already dropped one) or to catch sales on a cost — the cap would answer
    # first and hide both.
    print("\n── one line moves, the rest is left exactly as it was ──")
    pr2 = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [{"description": G, "qty": 2, "uom": "pcs"},
                  {"description": S, "qty": 10, "uom": "pcs"}]}))["id"]
    await c.post(f"/price-requests/{pr2}/submit", headers=s1)
    await c.post(f"/price-requests/{pr2}/price", headers=pu, json={"items": [
        {"line_no": 1, "cost_price": 4_000_000, "basis": "unit"},
        {"line_no": 2, "cost_price": 90_000, "basis": "unit"}]})
    r = await c.post(f"/price-requests/{pr2}/approve", headers=d, json={"items": [
        {"line_no": 1, "sell_price": 6_000_000, "basis": "unit"},
        {"line_no": 2, "sell_price": 150_000, "basis": "unit"}]})
    check("the director signs the second request off", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:140])

    r = await c.post(f"/price-requests/{pr2}/revise", headers=pu, json={
        "items": [{"description": G, "qty": 2, "uom": "pcs",
                   "cost_price": 8_400_000, "cost_basis": "total"},
                  {"description": S, "qty": 10, "uom": "pcs"}],
        "reason": "New quote from the vendor"})
    check("purchasing can still correct an approved request", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:150])
    await c.post(f"/approvals/{J(r)['approval_request_id']}/approve", headers=d)
    got = J(await c.get(f"/price-requests/{pr2}", headers=pu))
    check("a cost entered as a line total is stored per unit, as everywhere else",
          (line(got, G) or {}).get("cost_price") == 4_200_000, str(line(got, G)))
    check("...the line nobody touched keeps its cost",
          (line(got, S) or {}).get("cost_price") == 90_000, str(line(got, S)))
    seller = J(await c.get(f"/price-requests/{pr2}", headers=d))
    check("...and the director's selling prices survive the correction",
          (line(seller, G) or {}).get("sell_price") == 6_000_000
          and (line(seller, S) or {}).get("sell_price") == 150_000,
          f"{line(seller, G)} {line(seller, S)}")

    r = await c.post(f"/price-requests/{pr2}/revise", headers=s1, json={
        "items": [{"description": G, "qty": 2, "cost_price": 1}], "reason": "sneak"})
    check("sales cannot set a cost through a revision", r.status_code == 403,
          f"{r.status_code} {r.text[:120]}")
    r = await c.post(f"/price-requests/{pr2}/revise", headers=s1, json={
        "items": [{"description": G, "qty": 3}], "reason": "a real one"})
    check("...but its own scope revision still works", r.status_code == 200,
          f"{r.status_code} {r.text[:120]}")
    check("...and purchasing's correction cost it nothing",
          J(r).get("revisions_left") == 3, str(J(r).get("revisions_left")))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")


asyncio.run(main())

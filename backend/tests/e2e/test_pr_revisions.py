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
    r = await c.post(f"/price-requests/{pr}/revise", headers=pu, json={
        "items": [{"description": G, "qty": 1}]})
    check("purchasing cannot revise it either", r.status_code in (403, 404, 409),
          str(r.status_code))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")


asyncio.run(main())

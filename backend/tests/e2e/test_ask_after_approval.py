"""Asking a supplier about a job the director has already priced.

The vendor list only offered price requests still waiting on a cost, on the
reasoning that asking about a job already priced was answering a question
nobody asked. That reads well and is wrong about how the work runs: the
approved request is the one you actually buy against. The deal is won and the
goods have to be ordered; the quote that justified the cost has expired; the
order itself changed. Every one of those is a vendor conversation about a
settled request, and there was no way to start one — the request simply was
not in the list.

Opening the list is the easy half. The half that matters is what happens when
the quote comes back, because a settled request has a margin the director
approved against the *old* cost. Writing the new one straight on would move
that decision without telling the person who made it. The apply path used to
answer this by skipping silently, which is the same failure seen from the
other end: purchasing rings three vendors, presses Apply, and nothing happens
anywhere.

So it goes where purchasing's own "propose a cost revision" button already
sends it — the director's queue, with the quote named on it. Same entry in the
revision log, same approval row, same button to approve. What this pins is
that the two halves stay joined: the request can be asked about, the answer
reaches somebody, and the approved cost does not move until a person says so.
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
    # The create endpoint answers with a list of the requests it made, so a
    # helper that assumes an error envelope has to cope with both.
    if not isinstance(b, dict):
        return str(b)[:160].lower()
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

    def line(doc, no):
        for it in (doc.get("items") or []):
            if int(it.get("line_no") or 0) == no:
                return it
        return {}

    # ══ a request, priced and signed off ═════════════════════════════════
    print("\n── a job the director has already priced ──")
    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Lanjut {TAG}", "industry": "mining"}))["id"]
    pr = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust, "items": [
            {"description": f"ROLLER CHAIN RS 80 {TAG}", "qty": 28, "uom": "roll"},
            {"description": f"SPROCKET RS 100 {TAG}", "qty": 8, "uom": "pcs"}]}))["id"]
    await c.post(f"/price-requests/{pr}/submit", headers=s1)
    await c.post(f"/price-requests/{pr}/price", headers=d, json={"items": [
        {"line_no": 1, "cost_price": 380_000, "basis": "unit"},
        {"line_no": 2, "cost_price": 365_000, "basis": "unit"}]})
    await c.post(f"/price-requests/{pr}/approve", headers=d, json={"items": [
        {"line_no": 1, "sell_price": 494_000, "basis": "unit"},
        {"line_no": 2, "sell_price": 475_000, "basis": "unit"}]})
    got = J(await c.get(f"/price-requests/{pr}", headers=d))
    check("the request is approved", got.get("status") == "approved",
          str(got.get("status")))
    check("...with the cost the director signed the margin against",
          float(line(got, 1).get("cost_price") or 0) == 380_000,
          str(line(got, 1).get("cost_price")))

    # ══ it can still be put in front of a vendor ═════════════════════════
    print("\n── and it can still be put in front of a vendor ──")
    sup = J(await c.post("/purchasing/suppliers", headers=pur, json={
        "name": f"PT Rantai {TAG}", "category": "fabrication"}))["id"]
    r = await c.post("/purchasing/price-requests", headers=pur, json={
        "price_request_id": pr, "supplier_ids": [sup]})
    check("a supplier request is raised against a settled price request",
          r.status_code == 201, f"{r.status_code} {why(r)}")
    made = J(r)
    spr = (made if isinstance(made, list) else made.get("created") or [made])[0]
    spr_id = spr["id"]
    check("...carrying its lines", len(spr.get("items") or []) == 2,
          str(len(spr.get("items") or [])))
    check("...and pointing back at the request it costs",
          str(spr.get("price_request_id")) == pr, str(spr.get("price_request_id")))

    await c.post(f"/purchasing/price-requests/{spr_id}/send", headers=pur)
    r = await c.post(f"/purchasing/price-requests/{spr_id}/quote", headers=pur, json={
        "items": [{"line_no": 1, "quoted_price": 340_000, "basis": "unit"},
                  {"line_no": 2, "quoted_price": 300_000, "basis": "unit"}]})
    check("the vendor's answer is recorded", r.status_code == 200,
          f"{r.status_code} {why(r)}")

    # ══ applying it does not move the approved cost ══════════════════════
    print("\n── and applying it asks the director rather than telling them ──")
    r = await c.post(f"/purchasing/price-requests/{spr_id}/apply", headers=pur)
    check("the apply is accepted rather than refused", r.status_code == 200,
          f"{r.status_code} {why(r)}")
    body = J(r)
    row = (body.get("price_requests") or [{}])[0]
    check("...as a queued cost revision, not a write",
          bool(row.get("queued_revision")), str(row)[:220])
    check("...and it says so in words somebody can act on",
          "director" in str(row.get("detail", "")).lower(), str(row.get("detail"))[:180])

    got = J(await c.get(f"/price-requests/{pr}", headers=d))
    check("the approved cost has NOT moved",
          float(line(got, 1).get("cost_price") or 0) == 380_000,
          str(line(got, 1).get("cost_price")))
    check("...and the request is still approved, not dragged back a stage",
          got.get("status") == "approved", str(got.get("status")))

    revs = J(await c.get(f"/price-requests/{pr}/revisions", headers=d))
    rows = revs if isinstance(revs, list) else (revs.get("revisions") or [])
    mine = next((x for x in rows if x.get("status") == "pending"), None)
    check("a revision is waiting in the log", mine is not None, str(revs)[:220])
    check("...marked as a cost revision, which spends no negotiation budget",
          mine and mine.get("kind") == "cost", str(mine and mine.get("kind")))
    check("...naming the quote it came from",
          mine and spr["number"] in str(mine.get("reason")),
          str(mine and mine.get("reason"))[:160])
    # The log reports a diff rather than two raw item blobs, so this is what
    # the director actually reads: which line, from what, to what.
    moved = [ch for ch in (mine or {}).get("changes") or [] if ch.get("kind") == "cost"]
    check("...showing the cost that would move, and by how much",
          any(float(ch.get("from") or 0) == 380_000
              and float(ch.get("to") or 0) == 340_000 for ch in moved),
          str(moved)[:220])

    print("\n── the director approves it, and only then does the cost move ──")
    approvals = J(await c.get("/approvals", headers=d))
    approvals = approvals if isinstance(approvals, list) else (approvals.get("items") or [])
    req = next((a for a in approvals
                if a.get("target_type") == "price_request_revision"
                and str(a.get("target_id")) == pr), None)
    check("it is in the director's queue", req is not None, str(len(approvals)))
    r = await c.post(f"/approvals/{req['id']}/approve", headers=d)
    check("...and approving works", r.status_code == 200, f"{r.status_code} {why(r)}")
    got = J(await c.get(f"/price-requests/{pr}", headers=d))
    check("NOW the cost is the vendor's", float(line(got, 1).get("cost_price") or 0) == 340_000,
          str(line(got, 1).get("cost_price")))
    check("...on both lines", float(line(got, 2).get("cost_price") or 0) == 300_000,
          str(line(got, 2).get("cost_price")))
    check("...and the selling price the director set is untouched",
          float(line(got, 1).get("sell_price") or 0) == 494_000,
          str(line(got, 1).get("sell_price")))
    check("...with the quote that supplied it named on the line",
          line(got, 1).get("cost_source") == spr["number"],
          str(line(got, 1).get("cost_source")))

    # ══ one at a time ════════════════════════════════════════════════════
    print("\n── a second quote while one is already waiting ──")
    spr2 = J(await c.post("/purchasing/price-requests", headers=pur, json={
        "price_request_id": pr, "supplier_ids": [sup]}))
    spr2 = (spr2 if isinstance(spr2, list) else spr2.get("created") or [spr2])[0]
    await c.post(f"/purchasing/price-requests/{spr2['id']}/quote", headers=pur, json={
        "items": [{"line_no": 1, "quoted_price": 310_000, "basis": "unit"}]})
    r = await c.post(f"/purchasing/price-requests/{spr2['id']}/apply", headers=pur)
    check("the first one queues fine", r.status_code == 200, f"{r.status_code} {why(r)}")

    spr3 = J(await c.post("/purchasing/price-requests", headers=pur, json={
        "price_request_id": pr, "supplier_ids": [sup]}))
    spr3 = (spr3 if isinstance(spr3, list) else spr3.get("created") or [spr3])[0]
    await c.post(f"/purchasing/price-requests/{spr3['id']}/quote", headers=pur, json={
        "items": [{"line_no": 1, "quoted_price": 305_000, "basis": "unit"}]})
    r = await c.post(f"/purchasing/price-requests/{spr3['id']}/apply", headers=pur)
    check("a second is refused while the director still has the first",
          r.status_code == 409 and "waiting" in why(r), f"{r.status_code} {why(r)}")

    # ══ a request still waiting on a cost is untouched by all this ═══════
    print("\n── and the ordinary path is exactly as it was ──")
    pr2 = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [{"description": f"BELT {TAG}", "qty": 10, "uom": "meter"}]}))["id"]
    await c.post(f"/price-requests/{pr2}/submit", headers=s1)
    spr4 = J(await c.post("/purchasing/price-requests", headers=pur, json={
        "price_request_id": pr2, "supplier_ids": [sup]}))
    spr4 = (spr4 if isinstance(spr4, list) else spr4.get("created") or [spr4])[0]
    await c.post(f"/purchasing/price-requests/{spr4['id']}/quote", headers=pur, json={
        "items": [{"line_no": 1, "quoted_price": 120_000, "basis": "unit"}]})
    r = await c.post(f"/purchasing/price-requests/{spr4['id']}/apply", headers=pur)
    check("an uncosted request takes the price straight on",
          r.status_code == 200 and not (J(r).get("price_requests") or [{}])[0].get("queued_revision"),
          f"{r.status_code} {str(J(r))[:200]}")
    got = J(await c.get(f"/price-requests/{pr2}", headers=d))
    check("...the cost is on it now", float(line(got, 1).get("cost_price") or 0) == 120_000,
          str(line(got, 1).get("cost_price")))
    check("...and it has gone to the director for a price",
          got.get("status") == "pending_director", str(got.get("status")))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)


asyncio.run(main())

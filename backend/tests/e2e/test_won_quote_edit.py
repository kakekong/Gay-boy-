"""Changing a won deal, and everything that reads it following along.

The sync exists: edit a quotation and the price request behind it follows,
and the project's order card reads that request live. It worked on every
quotation except the only one that matters by the time a project exists —
the won one. `won` was in the same locked set as `lost` and `cancelled`, so
the edit was refused outright, nothing synced, and from the outside the
whole feature looked broken: "it doesn't work on closed quotations".

It was the wrong grouping. A lost or cancelled deal is over — nothing is
delivered against it and nothing reads it, so editing one rewrites history
and changes no reality. A **won** deal is the opposite: it is the live one.
A project is running against it, the price request behind it is kept in step
with it, and purchasing buys to that request. It is precisely the document a
customer rings up about to add four more of item eight.

So won joins approved and sent: the director edits it directly, anyone else's
edit queues for them, and the same sync runs. What that drags in is the
ledger — winning a quotation posts revenue, so a quotation that can now move
after winning must not leave the accounts holding the old figure. It is
reversed and re-posted, which is the rule this system already keeps for every
other correction: the original entries stay, the reversal sits beside them,
and the new posting follows.
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
    adm = await login("admin@demo.local")

    def line(doc, no):
        for it in (doc.get("items") or []):
            if int(it.get("line_no") or 0) == no:
                return it
        return {}
    async def quote(qid, hdr=None):
        return J(await c.get(f"/quotations/{qid}", headers=hdr or d))
    def payload_items(qdoc):
        out = []
        for it in qdoc["items"]:
            row = dict(it)
            row.pop("id", None); row.pop("line_total", None)
            out.append(row)
        return out

    # ══ a won deal with a project running against it ═════════════════════
    print("\n── a deal that is won, with a job under way ──")
    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Hidup {TAG}", "industry": "mining"}))["id"]
    pr = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust, "items": [
            {"description": f"ROLLER CHAIN RS 80 {TAG}", "qty": 28, "uom": "roll"},
            {"description": f"SPROCKET RS 100 {TAG}", "qty": 8, "uom": "pcs"}]}))["id"]
    await c.post(f"/price-requests/{pr}/submit", headers=s1)
    await c.post(f"/price-requests/{pr}/price", headers=d, json={"items": [
        {"line_no": 1, "cost_price": 380_000, "basis": "unit"},
        {"line_no": 2, "cost_price": 365_000, "basis": "unit"}]})
    await c.post(f"/price-requests/{pr}/approve", headers=d, json={"items": [
        {"line_no": 1, "sell_price": 500_000, "basis": "unit"},
        {"line_no": 2, "sell_price": 475_000, "basis": "unit"}]})
    q = J(await c.post(f"/quotations/from-price-request/{pr}", headers=s1))["id"]
    await c.post(f"/quotations/{q}/submit", headers=s1)
    await c.post(f"/quotations/{q}/approve", headers=d, json={"notes": ""})
    cpo = J(await c.post("/customer-pos", headers=s1, json={
        "customer_id": cust, "quotation_id": q, "number": f"PO-WON-{TAG}",
        "items": [{"description": f"ROLLER CHAIN RS 80 {TAG}", "qty": 28,
                   "unit_price": 500_000}], "is_downpayment": False}))["id"]
    await c.post(f"/quotations/{q}/won", headers=d)
    proj = J(await c.post(f"/customer-pos/{cpo}/approve", headers=d,
                          json={"notes": ""}))["project_id"]
    got = await quote(q)
    check("the quotation is won", got.get("status") == "won", str(got.get("status")))
    check("...and posted to the ledger", got.get("is_posted") is True,
          str(got.get("is_posted")))
    total_before = float(got.get("total") or 0)
    check("there is a project running against it", bool(proj), str(proj))

    # What the accounts hold before anything moves.
    from app.core.db import SessionLocal
    from sqlalchemy import func as _f, select as _sel
    from app.models.account import Account
    async def balance(no):
        async with SessionLocal() as db:
            a = await db.scalar(_sel(Account).where(Account.account_no == no))
            return round(float(a.balance or 0), 2) if a else None
    recv_before = await balance("110301")

    # ══ the customer changes their mind ══════════════════════════════════
    print("\n── the customer rings up and changes the order ──")
    items = payload_items(got)
    items[1]["qty"] = 12                 # four more sprockets
    items[0]["unit_price"] = 520_000     # and a renegotiated price
    r = await c.patch(f"/quotations/{q}", headers=d, json={"items": items})
    check("a won quotation takes the edit — it is the live deal",
          r.status_code == 200, f"{r.status_code} {why(r)}")
    got = await quote(q)
    check("...the line moved", float(line(got, 2).get("qty") or 0) == 12,
          str(line(got, 2).get("qty")))
    check("...and it is still won, not knocked back a stage",
          got.get("status") == "won", str(got.get("status")))

    print("\n── and the order behind it follows, with no button pressed ──")
    back = J(await c.get(f"/price-requests/{pr}", headers=d))
    check("the price request has the new quantity",
          float(line(back, 2).get("qty") or 0) == 12, str(line(back, 2).get("qty")))
    check("...and the new price",
          float(line(back, 1).get("sell_price") or 0) == 520_000,
          str(line(back, 1).get("sell_price")))
    check("...while purchasing's cost is untouched",
          float(line(back, 1).get("cost_price") or 0) == 380_000,
          str(line(back, 1).get("cost_price")))

    full = J(await c.get(f"/operation/projects/{proj}/full", headers=d))
    card = (full.get("project") or {}).get("price_request") or full.get("price_request") or {}
    check("the project's order card shows it too",
          any(float(i.get("qty") or 0) == 12 for i in card.get("items") or []),
          str(card.get("items"))[:200])
    check("...and reports nothing out of step",
          not card.get("drift"), str(card.get("drift"))[:200])

    # ══ the accounts are told ════════════════════════════════════════════
    print("\n── and the accounts hear about it, because they had the old figure ──")
    got = await quote(q)
    total_after = float(got.get("total") or 0)
    check("the quotation total really did move", abs(total_after - total_before) > 1,
          f"{total_before} → {total_after}")
    check("...it is posted again, not left reversed",
          got.get("is_posted") is True, str(got.get("is_posted")))
    recv_after = await balance("110301")
    check("...and the receivable moved by exactly the difference",
          abs((recv_after - recv_before) - (total_after - total_before)) < 1,
          f"receivable {recv_before} → {recv_after}, quote {total_before} → {total_after}")

    async with SessionLocal() as db:
        from app.models.finance import LedgerEntry
        lines = (await db.scalars(
            _sel(LedgerEntry).where(LedgerEntry.source_type == "quotation",
                                    LedgerEntry.source_id == uuid.UUID(q)))).all()
        memos = [str(x.memo or "") for x in lines]
    check("the correction is written as a reversal beside the original",
          any("reversed" in m.lower() for m in memos), str(memos)[:220])
    check("...with the original entries still there",
          any("posted" in m.lower() for m in memos), str(memos)[:220])

    # ══ a deal that really is over stays shut ════════════════════════════
    print("\n── while a deal that really is over stays shut ──")
    # Sales cannot raise a quotation from scratch — every one starts from an
    # approved price request, so the second deal is built the same way.
    pr2 = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [{"description": f"SHAFT {TAG}", "qty": 2, "uom": "pcs"}]}))["id"]
    await c.post(f"/price-requests/{pr2}/submit", headers=s1)
    await c.post(f"/price-requests/{pr2}/price", headers=d, json={
        "items": [{"line_no": 1, "cost_price": 700_000, "basis": "unit"}]})
    await c.post(f"/price-requests/{pr2}/approve", headers=d, json={
        "items": [{"line_no": 1, "sell_price": 1_000_000, "basis": "unit"}]})
    q2 = J(await c.post(f"/quotations/from-price-request/{pr2}", headers=s1))["id"]
    await c.post(f"/quotations/{q2}/submit", headers=s1)
    await c.post(f"/quotations/{q2}/approve", headers=d, json={"notes": ""})
    await c.post(f"/quotations/{q2}/lost", headers=d,
                 params={"reason": "customer went elsewhere"})
    got2 = await quote(q2)
    check("the second quotation is lost", got2.get("status") == "lost",
          str(got2.get("status")))
    # An unchanged payload is pruned to nothing and returns early, so the
    # edit has to actually differ for the guard to be the thing answering.
    dead = payload_items(got2)
    dead[0]["qty"] = 9
    r = await c.patch(f"/quotations/{q2}", headers=d, json={"items": dead})
    check("a lost quotation still refuses an edit", r.status_code == 409,
          f"{r.status_code} {why(r)}")
    check("...and says the deal is closed", "closed" in why(r), why(r)[:160])

    # ══ and somebody who is not the director still asks ══════════════════
    print("\n── a non-director's change to a won deal still goes to the director ──")
    got = await quote(q)
    items = payload_items(got)
    items[1]["qty"] = 20
    r = await c.patch(f"/quotations/{q}", headers=s1, json={"items": items})
    check("sales' edit is not applied on the spot",
          r.status_code in (202, 409), f"{r.status_code} {why(r)}")
    back = J(await c.get(f"/price-requests/{pr}", headers=d))
    check("...so the request has not moved either",
          float(line(back, 2).get("qty") or 0) == 12, str(line(back, 2).get("qty")))

    r = await c.patch(f"/quotations/{q}", headers=adm, json={"items": items})
    check("admin's edit is queued rather than applied",
          r.status_code == 202, f"{r.status_code} {why(r)}")
    approvals = J(await c.get("/approvals", headers=d))
    approvals = approvals if isinstance(approvals, list) else (approvals.get("items") or [])
    req = next((a for a in approvals if a.get("target_type") == "quotation_edit"
                and str(a.get("target_id")) == q), None)
    check("...and waits in the director's queue", req is not None, str(len(approvals)))
    r = await c.post(f"/approvals/{req['id']}/approve", headers=d)
    check("...approving it applies the change", r.status_code == 200,
          f"{r.status_code} {why(r)}")
    back = J(await c.get(f"/price-requests/{pr}", headers=d))
    check("...and only then does the request follow",
          float(line(back, 2).get("qty") or 0) == 20, str(line(back, 2).get("qty")))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)


asyncio.run(main())

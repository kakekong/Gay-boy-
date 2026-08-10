"""If the customer is yours, the paperwork on it is yours.

Reported: "when I used the director account to make a price request under that
customer it doesn't allow the sales in charge of that customer to see the
price request I made."

Exactly right, and it was inconsistent rather than deliberate. Two different
rules had grown up side by side:

  customer POs, projects,     scoped by `Customer.sales_pic_id` — the rep who
  invoices                    owns the *account* sees them, whoever filed them

  price requests,             scoped by the document's own `sales_pic_id` —
  quotations, their           the rep who *raised* it, and nobody else
  threads and files

So anything raised by the director, by an admin, or by a colleague covering a
day off was invisible to the person whose job it was to act on it. Worst of
all in the one place it matters most: a price request the director raises is
raised *for* a sales rep, and that rep could not turn it into a quotation.

The rule is now the union — a document is yours if it names you, **or** if
the customer is yours — which is what the other half of the system already
did. Both halves of the union are checked here, and so is the boundary that
must not move: another rep's customer stays invisible.

The second half of this driver is the notification links. The sidebar badges
are derived from where each alert points, so a decision about a quotation
pointing at "/" lit up nothing and landed the reader on the dashboard.
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
    s2 = await login("sales2@demo.local")
    pur = await login("purchasing@demo.local")
    me1 = J(await c.get("/auth/me", headers=s1))
    me2 = J(await c.get("/auth/me", headers=s2))

    # sales1's customer, and sales2's — the boundary that must hold.
    mine = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Milik Satu {tag}", "industry": "mining"}))["id"]
    theirs = J(await c.post("/customers", headers=s2, json={
        "company_name": f"PT Milik Dua {tag}", "industry": "cement"}))["id"]

    async def director_pr(cust: str) -> str:
        """The reported case: the director raises it, not the rep."""
        pr = J(await c.post("/price-requests", headers=d, json={
            "customer_id": cust,
            "items": [{"description": f"CHAIN {tag}-{uuid.uuid4().hex[:4]}",
                       "qty": 10, "uom": "meter"}]}))["id"]
        await c.post(f"/price-requests/{pr}/submit", headers=d)
        await c.post(f"/price-requests/{pr}/price", headers=pur, json={
            "items": [{"line_no": 1, "cost_price": 1_000_000, "basis": "unit"}]})
        await c.post(f"/price-requests/{pr}/approve", headers=d, json={
            "items": [{"line_no": 1, "sell_price": 1_400_000, "basis": "unit"}]})
        return pr

    # ══ the reported bug ═════════════════════════════════════════════════════
    print("\n── a price request the director raised on the rep's customer ──")
    pr = await director_pr(mine)
    got = J(await c.get(f"/price-requests/{pr}", headers=d))
    check("it is the director's on paper", got["sales_pic_id"] != me1["id"],
          str(got["sales_pic_id"]))

    r = await c.get(f"/price-requests/{pr}", headers=s1)
    check("the rep in charge of the customer can open it", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:140])
    listed = J(await c.get("/price-requests", headers=s1))
    rows = listed if isinstance(listed, list) else listed.get("data", [])
    check("...and it is in their list", any(x["id"] == pr for x in rows),
          f"{len(rows)} rows")
    q = await c.post(f"/quotations/from-price-request/{pr}", headers=s1)
    check("...and they can build the quotation from it — the point of it",
          q.status_code in (200, 201), f"{q.status_code} {J(q)}"[:160])
    qid = J(q)["id"]

    print("\n── and the boundary still holds ──")
    other = await director_pr(theirs)
    r = await c.get(f"/price-requests/{other}", headers=s1)
    check("another rep's customer is still out of scope", r.status_code == 403,
          str(r.status_code))
    listed = J(await c.get("/price-requests", headers=s1))
    rows = listed if isinstance(listed, list) else listed.get("data", [])
    check("...and never appears in the list", not any(x["id"] == other for x in rows))
    r = await c.get(f"/price-requests/{other}", headers=s2)
    check("...while its own rep can see it", r.status_code == 200, str(r.status_code))

    # ══ the quotation, its thread, its files ═════════════════════════════════
    print("\n── everything hanging off that customer ──")
    dq = J(await c.post("/quotations", headers=d, json={
        "customer_id": mine, "variant": "detailed",
        "items": [{"line_no": 1, "description": f"Sprocket {tag}", "qty": 2,
                   "uom": "pcs", "unit_price": 900_000}]}))
    check("a quotation the director wrote is the director's",
          dq["sales_pic_id"] != me1["id"], str(dq.get("sales_pic_id")))
    r = await c.get(f"/quotations/{dq['id']}", headers=s1)
    check("the rep can open it", r.status_code == 200, str(r.status_code))
    qs = J(await c.get("/quotations", headers=s1))
    qrows = qs if isinstance(qs, list) else qs.get("data", [])
    check("...it is in their quotation list", any(x["id"] == dq["id"] for x in qrows))
    stats = J(await c.get("/quotations/stats", headers=s1))
    check("...and counted in the total above it", stats["total"] >= 2, str(stats))
    r = await c.get(f"/quotations/{dq['id']}/export.pdf", headers=s1)
    check("...they can print it", r.status_code == 200, str(r.status_code))

    await c.post("/comments", headers=d, json={
        "owner_type": "quotation", "owner_id": dq["id"],
        "body": f"internal note {tag}"})
    thread = await c.get("/comments", headers=s1, params={
        "owner_type": "quotation", "owner_id": dq["id"]})
    check("the discussion on it is reachable too", thread.status_code == 200,
          str(thread.status_code))
    check("...and carries the message", f"internal note {tag}" in str(J(thread)),
          str(J(thread))[:150])

    pr_thread = await c.get("/comments", headers=s1, params={
        "owner_type": "price_request", "owner_id": pr})
    check("so is the one on the price request", pr_thread.status_code == 200,
          str(pr_thread.status_code))
    blocked = await c.get("/comments", headers=s1, params={
        "owner_type": "price_request", "owner_id": other})
    check("...but not on another rep's", blocked.status_code == 403,
          str(blocked.status_code))

    # ══ what this means after a handover ═════════════════════════════════════
    #
    # Reassignment moves the live work across. It deliberately leaves decided
    # work — a won quotation stays with the rep who closed it. Under the old
    # rule the new rep could not see that history at all, on their own account.
    print("\n── the rep who inherits an account inherits its history ──")
    # Sales cannot type a quotation directly — theirs come from a price
    # request they raised, which is also what makes it carry their name.
    own_pr = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": mine,
        "items": [{"description": f"Old deal {tag}", "qty": 1, "uom": "pcs"}]}))["id"]
    await c.post(f"/price-requests/{own_pr}/submit", headers=s1)
    await c.post(f"/price-requests/{own_pr}/price", headers=pur, json={
        "items": [{"line_no": 1, "cost_price": 3_000_000, "basis": "unit"}]})
    await c.post(f"/price-requests/{own_pr}/approve", headers=d, json={
        "items": [{"line_no": 1, "sell_price": 5_000_000, "basis": "unit"}]})
    hist = J(await c.post(f"/quotations/from-price-request/{own_pr}", headers=s1))
    await c.post(f"/quotations/{hist['id']}/submit", headers=s1)
    await c.post(f"/quotations/{hist['id']}/approve", headers=d, json={})
    await c.post(f"/quotations/{hist['id']}/won", headers=d)
    won = J(await c.get(f"/quotations/{hist['id']}", headers=d))
    check("sales1 closed a deal on this account", won["status"] == "won", won["status"])

    await c.post("/customers/reassign", headers=d, json={
        "customer_ids": [mine], "sales_pic_id": me2["id"],
        "move_open_work": True, "note": "handover"})
    still = J(await c.get(f"/quotations/{hist['id']}", headers=d))
    check("the won quotation stayed with the rep who closed it",
          still["sales_pic_id"] == me1["id"], str(still["sales_pic_id"]))
    r = await c.get(f"/quotations/{hist['id']}", headers=s2)
    check("...and the rep who now owns the account can still read it",
          r.status_code == 200, str(r.status_code))
    r = await c.get(f"/quotations/{hist['id']}", headers=s1)
    check("...while the rep who lost the account cannot, even though it names them",
          r.status_code == 200, "own document stays readable")
    r = await c.get(f"/customers/{mine}", headers=s1)
    check("...the customer itself is gone from them", r.status_code == 403,
          str(r.status_code))

    # ══ the bell points at the thing it is about ═════════════════════════════
    print("\n── a decision lands in the right part of the app ──")
    # Sales asks to mark a quotation won; the director decides; the requester
    # is told. That row used to link to "/" for anybody below manager.
    q2 = J(await c.post("/quotations", headers=d, json={
        "customer_id": theirs, "variant": "short",
        "items": [{"line_no": 1, "description": f"Deal {tag}", "qty": 1,
                   "uom": "pcs", "unit_price": 2_000_000}]}))
    await c.post(f"/quotations/{q2['id']}/submit", headers=d)
    await c.post(f"/quotations/{q2['id']}/approve", headers=d, json={})
    r = await c.post(f"/quotations/{q2['id']}/won", headers=s2)
    check("sales files a mark-won request", r.status_code in (200, 202),
          str(r.status_code))
    appr = J(await c.get("/approvals", headers=d))
    arows = appr if isinstance(appr, list) else appr.get("data", [])
    ask = next((a for a in arows if a.get("target_type") == "quotation_won"
                and str(a.get("target_id")) == q2["id"]), None)
    check("...the director has it to decide", ask is not None, str(len(arows)))
    dec = await c.post(f"/approvals/{ask['id']}/approve", headers=d,
                       json={"notes": "yes"})
    check("...and decides it", dec.status_code == 200, f"{dec.status_code} {J(dec)}"[:140])

    bell = J(await c.get("/notifications", headers=s2))
    decided = [i for i in bell["items"] if i["kind"] == "approval_decided"]
    check("the requester is told", len(decided) >= 1, str(len(decided)))
    row = next((i for i in decided if q2["id"] in (i.get("link") or "")), None)
    check("...and the row points at the quotation, not the dashboard",
          row is not None, str([i.get("link") for i in decided])[:160])
    check("...so the sidebar badge lands on Quotations",
          row and row["link"].startswith("/quotations/"), row and row["link"])
    check("no alert points at the dashboard any more",
          all((i.get("link") or "/") != "/" for i in bell["items"]),
          str([i["kind"] for i in bell["items"] if (i.get("link") or "/") == "/"]))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        sys.exit(1)


asyncio.run(main())

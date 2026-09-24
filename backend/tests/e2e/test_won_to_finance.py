"""Marking a deal Won is finance's sign-off, not the director's.

Winning is the moment a deal stops being a conversation and becomes money:
the quotation posts to the ledger, the project opens, and the invoice schedule
follows from it. Finance is the desk that lives with all three, and they were
already the ones checking the customer's PO on the down-payment path — so the
sign-off moves to them.

Moving an approval between desks is never only the `required_role` line. The
request has to *arrive*: in finance's inbox, which filters to what is
addressed to them, and in their notification bell, which did not carry
approvals at all — they had a queue nobody told them about, which is the same
as not having one. And the old desk has to stop being the one it waits on
while still being able to settle anything, which is what the director is for.

What is pinned here: the request is addressed to finance, finance can see it
and decide it, approving it does the whole job (Won, ledger, project), a
manager cannot reach past it, the director can still settle one, and a
direct mark-won by finance closes any request already in the queue instead of
leaving it there with nothing to decide.
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
def why(r):
    b = J(r)
    if not isinstance(b, dict):
        return str(b)[:200].lower()
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
    fin = await login("finance@demo.local")
    mgr = await login("manager@demo.local")

    async def a_quote(tag):
        """A quotation with the customer's PO on file — Won's precondition."""
        cust = J(await c.post("/customers", headers=s1, json={
            "company_name": f"PT Menang {tag}", "industry": "mining"}))["id"]
        pr = J(await c.post("/price-requests", headers=s1, json={
            "customer_id": cust,
            "items": [{"description": f"CHAIN {tag}", "qty": 10, "uom": "pcs"}]}))["id"]
        await c.post(f"/price-requests/{pr}/submit", headers=s1)
        await c.post(f"/price-requests/{pr}/price", headers=d, json={
            "items": [{"line_no": 1, "cost_price": 500_000, "basis": "unit"}]})
        await c.post(f"/price-requests/{pr}/approve", headers=d, json={
            "items": [{"line_no": 1, "sell_price": 1_000_000, "basis": "unit"}]})
        q = J(await c.post(f"/quotations/from-price-request/{pr}", headers=s1))
        qid = q["id"]
        await c.post(f"/quotations/{qid}/submit", headers=s1)
        await c.post(f"/quotations/{qid}/approve", headers=d, json={"notes": ""})
        await c.post("/customer-pos", headers=s1, json={
            "customer_id": cust, "quotation_id": qid, "number": f"PO-WIN-{tag}",
            "items": [{"description": f"CHAIN {tag}", "qty": 10,
                       "unit_price": 1_000_000}],
            "is_downpayment": False})
        return qid, q["number"]

    async def won_request_for(qid, hdr):
        rows = J(await c.get("/approvals", headers=hdr))
        if not isinstance(rows, list):
            return None, rows
        return next((x for x in rows
                     if x["target_type"] == "quotation_won"
                     and x["target_id"] == qid), None), rows

    # ══ sales files it, and it goes to finance ═══════════════════════════
    print("\n── sales marks a deal won ──")
    qid, qno = await a_quote(TAG)
    r = await c.post(f"/quotations/{qid}/won", headers=s1)
    check("sales can ask for the deal to be marked Won", r.status_code == 202,
          f"{r.status_code} {why(r)}")
    check("...and is told it went to finance, not the director",
          "finance" in str(J(r)).lower(), str(J(r))[:160])

    req, rows = await won_request_for(qid, fin)
    check("the request lands in FINANCE's approval inbox", req is not None,
          str([(x['target_type'], x.get('required_role')) for x in (rows or [])])[:200])
    if req is None:
        print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
        return
    check("...addressed to finance", req.get("required_role") == "finance",
          str(req.get("required_role")))
    check("...naming the quotation it is about",
          qno in str(req.get("target_label") or req.get("reason") or ""),
          f"{req.get('target_label')} / {req.get('reason')}")

    # A queue nobody is told about is not a queue.
    notes = J(await c.get("/notifications", headers=fin))
    hit = [i for i in (notes.get("items") or [])
           if i.get("kind") == "approval" and str(req["id"]) in str(i.get("id"))]
    check("finance's bell tells them it is waiting", bool(hit),
          str([i.get("id") for i in (notes.get("items") or [])])[:200])
    if hit:
        check("...loudly enough to count on the sidebar badge",
              hit[0].get("severity") in ("high", "medium"), str(hit[0].get("severity")))
        check("...and points at the approvals page",
              hit[0].get("link") == "/approvals", str(hit[0].get("link")))

    # Finance can read what they are deciding.
    p = J(await c.get(f"/approvals/{req['id']}/preview", headers=fin))
    check("finance can open the preview of what they are signing off",
          p.get("title") == qno, str(p.get("title")))
    check("...with the money on it", p.get("total") is not None, str(p.get("total")))

    # ══ nobody else reaches past them ════════════════════════════════════
    print("\n── the desks that are not finance ──")
    mreq, mrows = await won_request_for(qid, mgr)
    check("a manager is not offered it — it is not their decision",
          mreq is None,
          str([(x['target_type'], x.get('required_role')) for x in (mrows or [])])[:160])
    r = await c.post(f"/approvals/{req['id']}/approve", headers=mgr)
    check("...and a manager cannot decide it through the back door",
          r.status_code == 403, f"{r.status_code} {why(r)}")
    r = await c.post(f"/approvals/{req['id']}/approve", headers=s1)
    check("sales cannot approve their own mark-won", r.status_code in (401, 403),
          f"{r.status_code} {why(r)}")

    q_now = J(await c.get(f"/quotations/{qid}", headers=d))
    check("and until somebody decides, the deal is NOT won",
          q_now.get("status") != "won", str(q_now.get("status")))

    # ══ finance approves, and it does the whole job ══════════════════════
    print("\n── finance signs it off ──")
    r = await c.post(f"/approvals/{req['id']}/approve", headers=fin,
                     params={"notes": f"PO checked {TAG}"})
    check("finance approves the mark-won", r.status_code == 200,
          f"{r.status_code} {why(r)}")

    q_now = J(await c.get(f"/quotations/{qid}", headers=d))
    check("...the quotation is Won", q_now.get("status") == "won",
          str(q_now.get("status")))
    check("...it posted to the ledger, which is what winning means here",
          bool(q_now.get("posted_at") or q_now.get("is_posted")
               or q_now.get("journal_entry_id")
               or (J(r).get("applied") or {}).get("posted") is not None),
          str({k: v for k, v in q_now.items() if "post" in k.lower()}))

    projs = J(await c.get("/operation/projects", headers=d))
    proj_rows = projs if isinstance(projs, list) else (projs.get("items") or [])
    check("...and the project opened on the back of it",
          any(str(x.get("quotation_id") or "") == qid
              or qno in str(x.get("quotation_number") or "")
              for x in proj_rows)
          or bool((J(r).get("applied") or {}).get("project_id")),
          str((J(r).get("applied") or {}))[:200])

    gone, _ = await won_request_for(qid, fin)
    check("...and it leaves finance's queue", gone is None, str(gone))

    # ══ the director is not waited on — it is not in their inbox at all ══
    print("\n── it stays out of the director's inbox ──")
    qid2, qno2 = await a_quote(f"D{TAG}")
    await c.post(f"/quotations/{qid2}/won", headers=s1)
    req2, _ = await won_request_for(qid2, fin)
    check("finance has the second request", req2 is not None)
    dreq, drows = await won_request_for(qid2, d)
    check("the director's approval inbox does NOT show it — it is finance's alone",
          dreq is None, str(dreq)[:160])
    check("...while the director's inbox still works for their own requests",
          isinstance(drows, list), str(drows)[:160])
    dnotes = J(await c.get("/notifications", headers=d))
    dhit = [i for i in (dnotes.get("items") or [])
            if i.get("kind") == "approval" and req2 and str(req2["id"]) in str(i.get("id"))]
    check("...nor does the director's bell (so the sidebar badge doesn't count it either)",
          not dhit, str(dhit)[:160])
    if req2:
        # Out of the inbox is not out of reach: the director can settle
        # anything, and an answer they give still counts.
        r = await c.post(f"/approvals/{req2['id']}/approve", headers=d)
        check("the director can still settle it if they do answer it",
              r.status_code == 200, f"{r.status_code} {why(r)}")
        q2 = J(await c.get(f"/quotations/{qid2}", headers=d))
        check("...with the same effect", q2.get("status") == "won",
              str(q2.get("status")))

    # The director's own Mark won still applies at once.
    qid4, _ = await a_quote(f"W{TAG}")
    r = await c.post(f"/quotations/{qid4}/won", headers=d)
    q4 = J(await c.get(f"/quotations/{qid4}", headers=d))
    check("the director marking a deal Won themselves applies at once",
          r.status_code == 200 and q4.get("status") == "won",
          f"{r.status_code} {q4.get('status')}")

    # ══ finance marking it directly ══════════════════════════════════════
    print("\n── finance marking it won without going through the queue ──")
    qid3, qno3 = await a_quote(f"F{TAG}")
    await c.post(f"/quotations/{qid3}/won", headers=s1)   # sales files first
    pending, _ = await won_request_for(qid3, fin)
    check("sales' request is queued", pending is not None)

    r = await c.post(f"/quotations/{qid3}/won", headers=fin)
    check("finance can mark it Won straight from the quotation",
          r.status_code in (200, 201), f"{r.status_code} {why(r)}")
    q3 = J(await c.get(f"/quotations/{qid3}", headers=d))
    check("...and it IS won, not queued back to themselves",
          q3.get("status") == "won", str(q3.get("status")))
    left, _ = await won_request_for(qid3, fin)
    check("...and the request they overtook is closed, not left sitting in "
          "the queue with nothing to decide",
          left is None, str(left))

    # ══ the precondition is unchanged ════════════════════════════════════
    print("\n── what has not changed ──")
    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Tanpa PO {TAG}", "industry": "mining"}))["id"]
    pr = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [{"description": f"WIRE {TAG}", "qty": 5, "uom": "pcs"}]}))["id"]
    await c.post(f"/price-requests/{pr}/submit", headers=s1)
    await c.post(f"/price-requests/{pr}/price", headers=d, json={
        "items": [{"line_no": 1, "cost_price": 100_000, "basis": "unit"}]})
    await c.post(f"/price-requests/{pr}/approve", headers=d, json={
        "items": [{"line_no": 1, "sell_price": 200_000, "basis": "unit"}]})
    bare = J(await c.post(f"/quotations/from-price-request/{pr}", headers=s1))["id"]
    await c.post(f"/quotations/{bare}/submit", headers=s1)
    await c.post(f"/quotations/{bare}/approve", headers=d, json={"notes": ""})
    r = await c.post(f"/quotations/{bare}/won", headers=fin)
    check("Won still refuses without the customer's PO on file — moving the "
          "desk did not move the rule",
          r.status_code == 409, f"{r.status_code} {why(r)}")
    check("...and says why", "po" in why(r), why(r)[:120])

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    for f in FAIL:
        print("  ✗", f)


asyncio.run(main())

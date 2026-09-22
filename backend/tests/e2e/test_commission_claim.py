"""Commission: claimable only once the customer's money is actually in.

A rep's share of a job is 2% of it, and the whole design turns on one word —
*when*. Not when the deal is won, not when the goods go out, not when the
invoice is raised: when finance has the money. A commission paid against an
outstanding invoice is a payout on a promise, and the promise is the part that
sometimes does not arrive.

So the gate is the collected figure — the same `SUM(payments.amount)` the AR
screens read — and it is checked on the server, twice: when the claim is filed
and again when it is approved, because a claim can sit in the queue for a week
and a payment can be reversed in that week. What this pins is that the button
and the endpoint never disagree, that a half-paid job is refused with the
figure still outstanding named in the message, and that the amount on an
approved claim is frozen rather than re-derived — otherwise reversing a
payment months later would quietly restate somebody's pay.
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
    s2 = await login("sales2@demo.local")
    fin = await login("finance@demo.local")
    hr = await login("hr@demo.local")
    adm = await login("admin@demo.local")

    me_s1 = J(await c.get("/auth/me", headers=s1))
    sales_id = me_s1.get("id")

    async def a_paid_job(tag, *, pay=True, unit=1_000_000, qty=10):
        """A project driven to a real invoice, optionally settled."""
        cust = J(await c.post("/customers", headers=s1, json={
            "company_name": f"PT Komisi {tag}", "industry": "mining"}))["id"]
        pr = J(await c.post("/price-requests", headers=s1, json={
            "customer_id": cust,
            "items": [{"description": f"CHAIN {tag}", "qty": qty, "uom": "pcs"}]}))["id"]
        await c.post(f"/price-requests/{pr}/submit", headers=s1)
        await c.post(f"/price-requests/{pr}/price", headers=d, json={
            "items": [{"line_no": 1, "cost_price": unit // 2, "basis": "unit"}]})
        await c.post(f"/price-requests/{pr}/approve", headers=d, json={
            "items": [{"line_no": 1, "sell_price": unit, "basis": "unit"}]})
        q = J(await c.post(f"/quotations/from-price-request/{pr}", headers=s1))["id"]
        await c.post(f"/quotations/{q}/submit", headers=s1)
        await c.post(f"/quotations/{q}/approve", headers=d, json={"notes": ""})
        cpo = J(await c.post("/customer-pos", headers=s1, json={
            "customer_id": cust, "quotation_id": q, "number": f"PO-KOM-{tag}",
            "items": [{"description": f"CHAIN {tag}", "qty": qty, "unit_price": unit}],
            "is_downpayment": False}))["id"]
        await c.post(f"/quotations/{q}/won", headers=d)
        proj = J(await c.post(f"/customer-pos/{cpo}/approve", headers=d,
                              json={"notes": ""}))["project_id"]
        await c.post(f"/operation/projects/{proj}/qc", headers=adm,
                     json={"decision": "pass"})
        await c.post(f"/operation/projects/{proj}/issue-invoice", headers=d,
                     data={"invoice_type": "single"})
        from app.core.db import SessionLocal
        from sqlalchemy import select as _sel
        from app.models.finance import Invoice as _Inv
        async with SessionLocal() as db:
            row = await db.scalar(_sel(_Inv).where(_Inv.project_id == proj)
                                  .order_by(_Inv.created_at.desc()))
            iid, total = str(row.id), float(row.total or 0)
        await c.post(f"/finance/invoices/{iid}/approve", headers=fin,
                     data={"faktur_pajak_no": f"FP-KOM-{tag}"})
        if pay:
            await c.post("/payments/manual", headers=fin, json={
                "invoice_id": iid, "amount": total, "method": "transfer",
                "reference": f"TRX-{tag}"})
        return proj, iid, total

    async def board(hdr=None):
        return J(await c.get(f"/users/{sales_id}/projects", headers=hdr or d))
    def row_for(rows, proj):
        return next((x for x in rows if x["id"] == proj), {})

    # ══ an unpaid job is not claimable ═══════════════════════════════════
    print("\n── a job the customer has not paid for ──")
    unpaid, _, unpaid_total = await a_paid_job(f"A{TAG}", pay=False)
    row = row_for(await board(), unpaid)
    com = row.get("commission") or {}
    check("the rep's project list carries the commission block", bool(com), str(row)[:200])
    check("...it knows what was invoiced",
          abs(float(com.get("invoiced") or 0) - unpaid_total) < 1, str(com.get("invoiced")))
    check("...that nothing has been collected", float(com.get("collected") or 0) == 0,
          str(com.get("collected")))
    check("...so it is not claimable", com.get("may_claim") is False,
          str(com.get("may_claim")))
    check("...and says why in a word the screen can show",
          com.get("blocked_reason") == "not paid in full", str(com.get("blocked_reason")))

    r = await c.post("/commissions", headers=s1, json={"project_id": unpaid})
    check("claiming it anyway is refused by the server, not just the button",
          r.status_code == 409, f"{r.status_code} {why(r)}")
    check("...naming what is still outstanding",
          "outstanding" in why(r), why(r)[:200])

    # ══ a paid job is ════════════════════════════════════════════════════
    print("\n── and one the customer has settled ──")
    paid, inv_id, total = await a_paid_job(f"B{TAG}")
    row = row_for(await board(), paid)
    com = row.get("commission") or {}
    check("the money shows as collected in full",
          com.get("paid_in_full") is True and abs(float(com["collected"]) - total) < 1,
          str(com)[:200])
    check("...the baseline rate is 2%", float(com.get("rate_pct") or 0) == 2.0,
          str(com.get("rate_pct")))
    check("...and the figure it would come to is 2% of what was collected",
          abs(float(com.get("amount") or 0) - round(total * 0.02, 2)) < 0.01,
          f"{com.get('amount')} vs {round(total * 0.02, 2)}")
    check("...it is claimable", com.get("may_claim") is True, str(com.get("may_claim")))

    r = await c.post("/commissions", headers=s1, json={
        "project_id": paid, "notes": "closed it in March"})
    check("the rep files the claim", r.status_code == 201, f"{r.status_code} {why(r)}")
    claim = J(r)
    check("...for 2% of the collected amount",
          abs(float(claim.get("amount") or 0) - round(total * 0.02, 2)) < 0.01,
          str(claim.get("amount")))
    check("...pending the director", claim.get("status") == "pending",
          str(claim.get("status")))
    check("...in the rep's name", claim.get("beneficiary_id") == sales_id,
          str(claim.get("beneficiary_id")))

    row = row_for(await board(), paid)
    check("the board now shows the claim on the job",
          (row.get("commission") or {}).get("claim", {}).get("status") == "pending",
          str(row.get("commission"))[:200])
    check("...and will not offer a second one",
          (row.get("commission") or {}).get("may_claim") is False
          and (row.get("commission") or {}).get("blocked_reason") == "already claimed",
          str(row.get("commission"))[:200])
    r = await c.post("/commissions", headers=s1, json={"project_id": paid})
    check("...nor accept one", r.status_code == 409 and "already" in why(r),
          f"{r.status_code} {why(r)}")

    # ══ whose money it is ════════════════════════════════════════════════
    print("\n── and it is nobody else's to claim or read ──")
    other, _, _ = await a_paid_job(f"C{TAG}")
    r = await c.post("/commissions", headers=s2, json={"project_id": other})
    check("another rep cannot claim on this rep's customer",
          r.status_code == 403, f"{r.status_code} {why(r)}")
    r = await c.post("/commissions", headers=adm, json={"project_id": other})
    check("...and admin, who runs the job, has no claim to file at all",
          r.status_code == 403, f"{r.status_code} {why(r)}")
    mine = J(await c.get("/commissions", headers=s2))
    check("a rep's list shows only their own",
          all(x.get("beneficiary_id") != sales_id for x in mine), str(mine)[:200])

    # ══ the decision ═════════════════════════════════════════════════════
    print("\n── the director decides ──")
    r = await c.post(f"/commissions/{claim['id']}/approve", headers=s1, json={})
    check("a rep cannot approve their own", r.status_code == 403, f"HTTP{r.status_code}")
    r = await c.post(f"/commissions/{claim['id']}/approve", headers=fin, json={})
    check("...nor finance", r.status_code == 403, f"HTTP{r.status_code}")
    r = await c.post(f"/commissions/{claim['id']}/approve", headers=d,
                     json={"rate_pct": 3, "notes": "brought the account in"})
    check("the director approves, at a rate of their choosing",
          r.status_code == 200, f"{r.status_code} {why(r)}")
    got = J(r)
    check("...and the amount follows the rate, on the basis frozen at claim time",
          abs(float(got.get("amount") or 0) - round(total * 0.03, 2)) < 0.01,
          f"{got.get('amount')} vs {round(total * 0.03, 2)}")
    check("...marked approved", got.get("status") == "approved", str(got.get("status")))

    r = await c.post(f"/commissions/{claim['id']}/mark-paid", headers=fin, json={})
    check("finance marks it paid once it has gone out",
          r.status_code == 200 and J(r).get("status") == "paid",
          f"{r.status_code} {str(J(r))[:140]}")
    r = await c.post(f"/commissions/{claim['id']}/approve", headers=d, json={})
    check("...and it cannot then be approved again",
          r.status_code == 409, f"{r.status_code} {why(r)}")

    # ══ the money moving back underneath a pending claim ══════════════════
    print("\n── a payment reversed while a claim is waiting ──")
    proj3, inv3, total3 = await a_paid_job(f"D{TAG}")
    r = await c.post("/commissions", headers=s1, json={"project_id": proj3})
    check("the claim is filed while it is paid", r.status_code == 201,
          f"{r.status_code} {why(r)}")
    claim3 = J(r)
    inv = J(await c.get(f"/finance/invoices/{inv3}", headers=fin))
    pay_id = (inv.get("payments") or [{}])[0].get("id")
    r = await c.post(f"/payments/{pay_id}/reverse", headers=d,
                     json={"reason": f"bounced {TAG}"})
    check("the director reverses the customer's payment", r.status_code == 201,
          f"{r.status_code} {why(r)}")
    r = await c.post(f"/commissions/{claim3['id']}/approve", headers=d, json={})
    check("the waiting claim can no longer be approved — the money went back",
          r.status_code == 409, f"{r.status_code} {why(r)}")
    check("...and says so plainly", "reversed" in why(r) or "paid in full" in why(r),
          why(r)[:200])
    row = row_for(await board(), proj3)
    check("...and the job stops reading as paid on the board",
          (row.get("commission") or {}).get("paid_in_full") is False,
          str(row.get("commission"))[:200])

    # ══ HR sees the person, not the pay ══════════════════════════════════
    print("\n── HR runs the personnel side, not the payroll of a deal ──")
    hr_rows = await board(hr)
    check("HR gets the project list", isinstance(hr_rows, list) and hr_rows,
          str(hr_rows)[:120])
    check("...with no commission figures on it",
          all(x.get("commission") is None for x in hr_rows), str(hr_rows[0])[:200])
    check("...and no deal value either, as before",
          all(x.get("po_value") is None for x in hr_rows), str(hr_rows[0])[:200])

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)


asyncio.run(main())

"""Recording a payment: finance's own entry, and nobody else's.

The change under test is who gets to say money arrived. It used to be the
customer — they filed a claim from the portal and finance agreed or
disagreed with it — which put the first record of a receipt in the hands of
somebody outside the company, and left finance unable to act on a transfer
they could already see in the bank statement until a claim showed up to
agree with.

So the claim route is gone and the entry is one step. What is checked here is
that removing it cost nothing: the same Payment row, the same ledger post,
the same invoice status, the same project close — and that the parts which
protect the books are still in place, because "one step" must not quietly
mean "fewer checks". Paying a settled invoice, paying a negative amount, and
recording one at all from any desk but finance are all still refused.

The verify / reject endpoints stay behind, and are tested against a claim
written straight into the database, because that is the only way one can
exist now — and stranding the ones customers submitted before the change
would be a worse outcome than the change itself.
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
    return str(b.get("detail")
               or (b.get("errors") or [{}])[0].get("message", "")).lower()


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)

    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    fin = await login("finance@demo.local")
    s1 = await login("sales1@demo.local")
    adm = await login("admin@demo.local")

    # ══ a project, invoiced — through the real pipeline ══════════════════
    print("\n── an invoice goes out ──")
    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Bayar {TAG}", "industry": "mining"}))["id"]
    pr = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [{"description": f"Rotor {TAG}", "qty": 10, "uom": "pcs"}]}))["id"]
    await c.post(f"/price-requests/{pr}/submit", headers=s1)
    await c.post(f"/price-requests/{pr}/price", headers=d,
                 json={"items": [{"line_no": 1, "cost_price": 500_000, "basis": "unit"}]})
    await c.post(f"/price-requests/{pr}/approve", headers=d,
                 json={"items": [{"line_no": 1, "sell_price": 1_000_000, "basis": "unit"}]})
    q = J(await c.post(f"/quotations/from-price-request/{pr}", headers=s1))["id"]
    await c.post(f"/quotations/{q}/submit", headers=s1)
    await c.post(f"/quotations/{q}/approve", headers=d, json={"notes": ""})
    cpo = J(await c.post("/customer-pos", headers=s1, json={
        "customer_id": cust, "quotation_id": q, "number": f"PO-PAY-{TAG}",
        "items": [{"description": f"Rotor {TAG}", "qty": 10, "unit_price": 1_000_000}],
        "is_downpayment": False}))["id"]
    await c.post(f"/quotations/{q}/won", headers=d)
    pid = J(await c.post(f"/customer-pos/{cpo}/approve", headers=d,
                         json={"notes": ""}))["project_id"]
    await c.post(f"/operation/projects/{pid}/qc", headers=adm,
                 json={"decision": "pass"})
    r = await c.post(f"/operation/projects/{pid}/issue-invoice", headers=d,
                     data={"invoice_type": "single"})
    check("an invoice exists to pay", r.status_code == 201, f"{r.status_code} {J(r)}"[:200])

    from app.core.db import SessionLocal
    from sqlalchemy import select as _sel
    from app.models.finance import Invoice as _Inv
    async with SessionLocal() as db:
        row = await db.scalar(_sel(_Inv).where(_Inv.project_id == pid)
                              .order_by(_Inv.created_at.desc()))
        iid, inv_total = str(row.id), float(row.total or 0)
    r = await c.post(f"/finance/invoices/{iid}/approve", headers=fin,
                     data={"faktur_pajak_no": f"FP-PAY-{TAG}"})
    check("...and is approved, so it can take money", r.status_code < 300,
          f"{r.status_code} {why(r)}")
    half = round(inv_total / 2, 2)

    # ══ the customer has no way in ═══════════════════════════════════════
    print("\n── the customer cannot claim it ──")
    pemail = f"portal.{TAG}@buyer.example"
    emp_free = await c.post("/users", headers=d, json={
        "email": pemail, "full_name": f"Portal {TAG}", "role": "customer",
        "password": "test-pass-123", "linked_customer_id": cust})
    check("a portal login exists", emp_free.status_code == 201,
          f"{emp_free.status_code} {J(emp_free)}"[:180])
    cu = await login(pemail)
    r = await c.post("/payments/claims", headers=cu, json={
        "invoice_id": iid, "amount": 10_000_000, "method": "bank_transfer"})
    check("submitting a payment claim is gone, not merely refused",
          r.status_code in (404, 405), f"HTTP{r.status_code}")
    r = await c.get("/payments/claims/mine", headers=cu)
    check("...as is the list it fed", r.status_code == 404, f"HTTP{r.status_code}")
    r = await c.get("/payments/claims", headers=cu)
    check("...and finance's own record stays out of reach",
          r.status_code == 403, f"HTTP{r.status_code}")
    # The portal did not lose sight of the invoice — only the ability to
    # assert something about it.
    projs = J(await c.get("/portal/customer/projects", headers=cu))
    rows = projs if isinstance(projs, list) else projs.get("items", [])
    mine = next((x for x in rows if x["id"] == pid), None)
    check("the customer still sees the project the invoice is against",
          mine is not None, str(rows)[:200])

    # ══ finance writes it down ═══════════════════════════════════════════
    print("\n── finance records what landed ──")
    openinv = J(await c.get("/payments/open-invoices", headers=fin))
    row = next((x for x in openinv if x["id"] == iid), None)
    check("the invoice is offered for payment", row is not None, str(openinv)[:200])
    check("...with what is still owed on it",
          row and abs(row["outstanding"] - inv_total) < 0.01, str(row)[:200])

    r = await c.post("/payments/manual", headers=fin, json={
        "invoice_id": iid, "amount": -5, "method": "cash"})
    check("a negative amount is refused",
          r.status_code == 400 and "positive" in why(r), f"{r.status_code} {why(r)}")

    r = await c.post("/payments/manual", headers=s1, json={
        "invoice_id": iid, "amount": 1_000_000})
    check("sales cannot record a payment", r.status_code == 403, str(r.status_code))
    r = await c.post("/payments/manual", headers=cu, json={
        "invoice_id": iid, "amount": 1_000_000})
    check("...and neither can the customer", r.status_code == 403, str(r.status_code))

    r = await c.post("/payments/manual", headers=fin, json={
        "invoice_id": iid, "amount": half, "paid_at": "2026-05-04",
        "method": "bank_transfer", "reference": f"TRX{TAG}",
        "notes": "part payment"})
    check("finance records a part payment", r.status_code == 201,
          f"{r.status_code} {J(r)}"[:220])
    part = J(r)
    check("...verified the moment it is written — there is nobody to agree with",
          part.get("status") == "verified", str(part.get("status")))
    check("...and attributed to the person who wrote it, not to a customer",
          part.get("source") == "finance"
          and "Finance" in str(part.get("submitted_by_name")),
          f"{part.get('source')} / {part.get('submitted_by_name')}")

    got = J(await c.get(f"/finance/invoices/{iid}", headers=fin))
    check("the invoice moves to partial", got.get("status") == "partial",
          str(got.get("status")))
    openinv = J(await c.get("/payments/open-invoices", headers=fin))
    row = next((x for x in openinv if x["id"] == iid), None)
    check("...and what is owed comes down by exactly what was paid",
          row and abs(row["outstanding"] - (inv_total - half)) < 0.01,
          str(row)[:200])

    # The receipt has to reach the books, not just the invoice — an invoice
    # that says "partial" with nothing behind it in the ledger is the exact
    # divergence this whole path exists to avoid.
    from app.models.finance import LedgerEntry as _LE, Payment as _Pay
    from sqlalchemy import func as _f
    async with SessionLocal() as db:
        paid_rows = (await db.scalars(
            _sel(_Pay).where(_Pay.invoice_id == uuid.UUID(iid)))).all()
        cash_in = await db.scalar(
            _sel(_f.coalesce(_f.sum(_LE.cash_delta), 0)).where(
                _LE.source_type == "payment",
                _LE.source_id.in_([x.id for x in paid_rows])))
    check("a real payment row is written, not just a claim",
          len(paid_rows) == 1 and abs(float(paid_rows[0].amount) - half) < 0.01,
          f"{len(paid_rows)} rows")
    check("...and the cash it brought in reaches the ledger",
          abs(float(cash_in or 0) - half) < 0.01, str(cash_in))

    # ══ paying the rest closes the job ═══════════════════════════════════
    print("\n── and the rest of it ──")
    r = await c.post("/payments/manual", headers=fin, json={
        "invoice_id": iid, "amount": inv_total - half, "paid_at": "2026-05-20",
        "method": "bank_transfer", "reference": f"TRX{TAG}-2"})
    check("the balance is recorded", r.status_code == 201, f"{r.status_code} {why(r)}")
    got = J(await c.get(f"/finance/invoices/{iid}", headers=fin))
    check("the invoice is paid", got.get("status") == "paid", str(got.get("status")))
    pr = J(await c.get(f"/operation/projects/{pid}", headers=adm))
    check("...and the project it belonged to is closed",
          pr.get("status") == "closed", str(pr.get("status")))

    r = await c.post("/payments/manual", headers=fin, json={
        "invoice_id": iid, "amount": 1_000_000})
    check("a settled invoice takes no more money",
          r.status_code == 409 and "paid" in why(r), f"{r.status_code} {why(r)}")

    openinv = J(await c.get("/payments/open-invoices", headers=fin))
    check("...and it drops off the list of what is owed",
          not any(x["id"] == iid for x in openinv), str(len(openinv)))


    # ══ the claims left behind ═══════════════════════════════════════════
    print("\n── what customers submitted before the change ──")
    # The only way one can exist now, which is the point: it is a leftover.
    from app.models.payment_claim import PaymentClaim
    from app.models.user import User
    # A second project, so the leftover claim has a live invoice to settle.
    cust2 = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Lama {TAG}", "industry": "mining"}))["id"]
    pr2 = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust2,
        "items": [{"description": f"Shaft {TAG}", "qty": 2, "uom": "pcs"}]}))["id"]
    await c.post(f"/price-requests/{pr2}/submit", headers=s1)
    await c.post(f"/price-requests/{pr2}/price", headers=d,
                 json={"items": [{"line_no": 1, "cost_price": 400_000, "basis": "unit"}]})
    await c.post(f"/price-requests/{pr2}/approve", headers=d,
                 json={"items": [{"line_no": 1, "sell_price": 1_000_000, "basis": "unit"}]})
    q2 = J(await c.post(f"/quotations/from-price-request/{pr2}", headers=s1))["id"]
    await c.post(f"/quotations/{q2}/submit", headers=s1)
    await c.post(f"/quotations/{q2}/approve", headers=d, json={"notes": ""})
    cpo2 = J(await c.post("/customer-pos", headers=s1, json={
        "customer_id": cust2, "quotation_id": q2, "number": f"PO-OLD-{TAG}",
        "items": [{"description": f"Shaft {TAG}", "qty": 2, "unit_price": 1_000_000}],
        "is_downpayment": False}))["id"]
    await c.post(f"/quotations/{q2}/won", headers=d)
    pid2 = J(await c.post(f"/customer-pos/{cpo2}/approve", headers=d,
                          json={"notes": ""}))["project_id"]
    await c.post(f"/operation/projects/{pid2}/qc", headers=adm,
                 json={"decision": "pass"})
    await c.post(f"/operation/projects/{pid2}/issue-invoice", headers=d,
                 data={"invoice_type": "single"})
    async with SessionLocal() as db:
        row2 = await db.scalar(_sel(_Inv).where(_Inv.project_id == pid2)
                               .order_by(_Inv.created_at.desc()))
        iid2, total2 = str(row2.id), float(row2.total or 0)
    await c.post(f"/finance/invoices/{iid2}/approve", headers=fin,
                 data={"faktur_pajak_no": f"FP-OLD-{TAG}"})
    async with SessionLocal() as db:
        who = await db.scalar(_sel(User).where(User.email == pemail))
        legacy = PaymentClaim(invoice_id=uuid.UUID(iid2),
                              customer_user_id=who.id, amount=total2,
                              method="bank_transfer", reference=f"OLD{TAG}",
                              status="pending")
        db.add(legacy); await db.commit()
        legacy_id = str(legacy.id)

    pending = J(await c.get("/payments/claims", headers=fin,
                            params={"status_eq": "pending"}))
    mine = next((x for x in pending if x["id"] == legacy_id), None)
    check("a leftover claim is still shown to finance", mine is not None,
          str(pending)[:200])
    check("...and labelled as having come from the portal, not from a colleague",
          mine and mine.get("source") == "portal", str(mine)[:220])

    r = await c.post(f"/payments/claims/{legacy_id}/verify", headers=fin,
                     json={"notes": "matched against the bank"})
    check("...and can still be settled rather than stranded",
          r.status_code == 200, f"{r.status_code} {why(r)}")
    got = J(await c.get(f"/finance/invoices/{iid2}", headers=fin))
    check("...paying its invoice the same way a recorded payment does",
          got.get("status") == "paid", str(got.get("status")))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)


asyncio.run(main())

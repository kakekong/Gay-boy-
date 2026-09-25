"""Taking a payment back off an invoice — the director's call.

A receipt gets recorded against the wrong invoice, or against the right one
twice, or the transfer bounces a week later. Until now there was nothing to
do about it: "paid" is not a field anybody edits, it is derived from the sum
of the payments recorded against the invoice, and the only escape was to
delete the invoice — which the delete endpoint itself refuses to do while a
payment stands against it, telling you to reverse the payment first. There
was no way to reverse the payment.

So this is what "reverse the paid status" has to mean if it is to be true:
the reversal acts on the money. A second payment row is written for the
negative amount, pointing at the receipt it undoes, and the mirror entry is
posted to the ledger — cash down, receivable back up. Everything downstream
then follows from arithmetic that was already there: the invoice stops
saying paid because the sum no longer covers it, it reappears in the
collections queue and the payment picker, and the project that payment had
walked to closed comes back to the stage before money — invoiced if the
goods were delivered, the stage before delivery if they were not (this
job never was, so it goes back to packaging).

What is checked here is that all of that actually happens, that both facts
survive on the record rather than one erasing the other, that the books
balance to zero afterwards, and that the door is the director's alone —
finance, who records the money, cannot also take it back off.
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
    mgr = await login("manager@demo.local")

    from app.core.db import SessionLocal
    from sqlalchemy import func as _f, select as _sel
    from app.models.finance import Invoice as _Inv, LedgerEntry as _LE, Payment as _Pay

    async def invoiced(n: int, unit: int = 1_000_000, qty: int = 10):
        """A project driven through the real pipeline to an approved invoice."""
        cust = J(await c.post("/customers", headers=s1, json={
            "company_name": f"PT Balik {TAG}-{n}", "industry": "mining"}))["id"]
        pr = J(await c.post("/price-requests", headers=s1, json={
            "customer_id": cust,
            "items": [{"description": f"Rotor {TAG}-{n}", "qty": qty, "uom": "pcs"}]}))["id"]
        await c.post(f"/price-requests/{pr}/submit", headers=s1)
        await c.post(f"/price-requests/{pr}/price", headers=d,
                     json={"items": [{"line_no": 1, "cost_price": unit // 2, "basis": "unit"}]})
        await c.post(f"/price-requests/{pr}/approve", headers=d,
                     json={"items": [{"line_no": 1, "sell_price": unit, "basis": "unit"}]})
        q = J(await c.post(f"/quotations/from-price-request/{pr}", headers=s1))["id"]
        await c.post(f"/quotations/{q}/submit", headers=s1)
        await c.post(f"/quotations/{q}/approve", headers=d, json={"notes": ""})
        cpo = J(await c.post("/customer-pos", headers=s1, json={
            "customer_id": cust, "quotation_id": q, "number": f"PO-REV{n}-{TAG}",
            "items": [{"description": f"Rotor {TAG}-{n}", "qty": qty,
                       "unit_price": unit}],
            "is_downpayment": False}))["id"]
        await c.post(f"/quotations/{q}/won", headers=d)
        pid = J(await c.post(f"/customer-pos/{cpo}/approve", headers=d,
                             json={"notes": ""}))["project_id"]
        await c.post(f"/operation/projects/{pid}/qc", headers=adm,
                     json={"decision": "pass"})
        await c.post(f"/operation/projects/{pid}/issue-invoice", headers=d,
                     data={"invoice_type": "single"})
        async with SessionLocal() as db:
            row = await db.scalar(_sel(_Inv).where(_Inv.project_id == pid)
                                  .order_by(_Inv.created_at.desc()))
            iid, total = str(row.id), float(row.total or 0)
        await c.post(f"/finance/invoices/{iid}/approve", headers=fin,
                     data={"faktur_pajak_no": f"FP-REV{n}-{TAG}"})
        return pid, iid, total

    async def books(invoice_id: str):
        """Cash movement and AR movement across every payment on an invoice."""
        async with SessionLocal() as db:
            ids = [x.id for x in (await db.scalars(
                _sel(_Pay).where(_Pay.invoice_id == uuid.UUID(invoice_id)))).all()]
            if not ids:
                return 0.0, 0.0
            cash = await db.scalar(
                _sel(_f.coalesce(_f.sum(_LE.cash_delta), 0)).where(
                    _LE.source_type == "payment", _LE.source_id.in_(ids)))
            ar = await db.scalar(
                _sel(_f.coalesce(_f.sum(_LE.amount), 0)).where(
                    _LE.source_type == "payment", _LE.source_id.in_(ids),
                    _LE.account_no == "110301"))
            return float(cash or 0), float(ar or 0)

    # ══ a paid invoice, and the money taken back off it ═══════════════════
    print("\n── an invoice is paid ──")
    pid, iid, total = await invoiced(1)
    r = await c.post("/payments/manual", headers=fin, json={
        "invoice_id": iid, "amount": total, "paid_at": "2026-06-03",
        "method": "bank_transfer", "reference": f"TRX-{TAG}"})
    check("finance records the money", r.status_code == 201,
          f"{r.status_code} {why(r)}")
    got = J(await c.get(f"/finance/invoices/{iid}", headers=fin))
    check("...the invoice says paid", got.get("status") == "paid",
          str(got.get("status")))
    proj = J(await c.get(f"/operation/projects/{pid}", headers=adm))
    check("...and the project closed on the back of it",
          proj.get("status") == "closed", str(proj.get("status")))
    cash, ar = await books(iid)
    check("...cash in and receivable down, in the ledger",
          abs(cash - total) < 0.01 and abs(ar + total) < 0.01, f"cash={cash} ar={ar}")
    pay_id = got["payments"][0]["id"]

    print("\n── and only the director can take it back ──")
    for who, hdr in (("finance", fin), ("the manager", mgr),
                     ("admin", adm), ("sales", s1)):
        r = await c.post(f"/payments/{pay_id}/reverse", headers=hdr,
                         json={"reason": "wrong invoice"})
        check(f"{who} cannot reverse a payment", r.status_code == 403,
              f"HTTP{r.status_code}")
    r = await c.post(f"/payments/{pay_id}/reverse", headers=d, json={"reason": "  "})
    check("...and even the director must say why",
          r.status_code == 400 and "why" in why(r), f"{r.status_code} {why(r)}")
    r = await c.post(f"/payments/{uuid.uuid4()}/reverse", headers=d,
                     json={"reason": "nothing there"})
    check("...on a payment that exists", r.status_code == 404, f"HTTP{r.status_code}")

    print("\n── the director reverses it ──")
    r = await c.post(f"/payments/{pay_id}/reverse", headers=d,
                     json={"reason": f"recorded against the wrong invoice {TAG}"})
    check("the reversal is accepted", r.status_code == 201,
          f"{r.status_code} {why(r)}")
    body = J(r)
    check("...for the negative of what came in",
          abs(float(body.get("amount") or 0) + total) < 0.01, str(body.get("amount")))
    check("...and the invoice is unpaid again, not merely 'partial'",
          body.get("invoice_status") == "approved", str(body.get("invoice_status")))
    # Delivered comes before invoiced now, and this job was paid without ever
    # being marked delivered — so it goes back to waiting for delivery.
    check("...the project comes back off paid — to the stage before delivery, since it never was",
          body.get("project_status") == "packaging", str(body.get("project_status")))
    check("...and nothing was said about keeping a deposit's job open",
          body.get("project_kept_open") is False, str(body.get("project_kept_open")))

    got = J(await c.get(f"/finance/invoices/{iid}", headers=fin))
    check("the invoice screen agrees", got.get("status") == "approved",
          str(got.get("status")))
    check("...nothing stands paid against it",
          abs(float(got.get("paid_amount") or 0)) < 0.01, str(got.get("paid_amount")))
    check("...and the whole total is outstanding again",
          abs(float(got.get("outstanding") or 0) - total) < 0.01,
          str(got.get("outstanding")))

    print("\n── both facts stay on the record ──")
    rows = got.get("payments") or []
    orig = next((x for x in rows if x["id"] == pay_id), None)
    rev = next((x for x in rows if x.get("is_reversal")), None)
    check("the receipt is still there — it is not deleted", orig is not None,
          str(len(rows)))
    check("...marked as taken back", orig and orig.get("reversed") is True,
          str(orig)[:180])
    check("...with the reversal written beside it", rev is not None, str(len(rows)))
    check("...pointing at what it undoes",
          rev and rev.get("reverses_payment_id") == pay_id, str(rev)[:180])
    check("...carrying the reason and the name of who did it",
          rev and TAG in str(rev.get("notes"))
          and "Director" in str(rev.get("notes")), str(rev and rev.get("notes"))[:200])
    check("the director is offered the button; the desk that recorded it is not",
          got.get("may", {}).get("reverse_payment") is False
          and J(await c.get(f"/finance/invoices/{iid}", headers=d)
                ).get("may", {}).get("reverse_payment") is True,
          str(got.get("may")))

    cash, ar = await books(iid)
    check("the books net to zero — cash back out, receivable restored",
          abs(cash) < 0.01 and abs(ar) < 0.01, f"cash={cash} ar={ar}")

    print("\n── and it cannot be done twice ──")
    r = await c.post(f"/payments/{pay_id}/reverse", headers=d,
                     json={"reason": "again"})
    check("reversing the same receipt twice is refused",
          r.status_code == 409 and "already" in why(r), f"{r.status_code} {why(r)}")
    r = await c.post(f"/payments/{rev['id']}/reverse", headers=d,
                     json={"reason": "undo the undo"})
    check("...and reversing the reversal is not how you re-record the money",
          r.status_code == 409, f"{r.status_code} {why(r)}")

    print("\n── the invoice is collectable again ──")
    openinv = J(await c.get("/payments/open-invoices", headers=fin))
    row = next((x for x in openinv if x["id"] == iid), None)
    check("it is back in the payment picker", row is not None, str(len(openinv)))
    check("...for the full amount", row and abs(row["outstanding"] - total) < 0.01,
          str(row)[:180])
    r = await c.post("/payments/manual", headers=fin, json={
        "invoice_id": iid, "amount": total, "paid_at": "2026-06-11",
        "method": "bank_transfer", "reference": f"TRX-{TAG}-fix"})
    check("finance can record the money properly this time",
          r.status_code == 201, f"{r.status_code} {why(r)}")
    got = J(await c.get(f"/finance/invoices/{iid}", headers=fin))
    check("...and it is paid again", got.get("status") == "paid",
          str(got.get("status")))
    cash, ar = await books(iid)
    check("...with the books showing exactly one payment's worth of cash",
          abs(cash - total) < 0.01 and abs(ar + total) < 0.01, f"cash={cash} ar={ar}")

    # ══ part of the money ════════════════════════════════════════════════
    print("\n── reversing one of two part payments ──")
    pid2, iid2, total2 = await invoiced(2)
    half = round(total2 / 2, 2)
    r1 = J(await c.post("/payments/manual", headers=fin, json={
        "invoice_id": iid2, "amount": half, "reference": f"A-{TAG}"}))
    await c.post("/payments/manual", headers=fin, json={
        "invoice_id": iid2, "amount": total2 - half, "reference": f"B-{TAG}"})
    got = J(await c.get(f"/finance/invoices/{iid2}", headers=fin))
    check("two payments settle it", got.get("status") == "paid",
          str(got.get("status")))
    first = next(x["id"] for x in got["payments"]
                 if str(x.get("reference")) == f"A-{TAG}")
    r = await c.post(f"/payments/{first}/reverse", headers=d,
                     json={"reason": "the first transfer bounced"})
    check("the first one is reversed", r.status_code == 201,
          f"{r.status_code} {why(r)}")
    check("...leaving the invoice partial, not unpaid",
          J(r).get("invoice_status") == "partial", str(J(r).get("invoice_status")))
    got = J(await c.get(f"/finance/invoices/{iid2}", headers=fin))
    check("...with the half that did land still standing against it",
          abs(float(got.get("paid_amount") or 0) - (total2 - half)) < 0.01,
          str(got.get("paid_amount")))
    proj = J(await c.get(f"/operation/projects/{pid2}", headers=adm))
    check("...and the project off 'closed' again",
          proj.get("status") == "packaging", str(proj.get("status")))

    # ══ what the delete endpoint has been promising ══════════════════════
    print("\n── the door the delete guard kept pointing at ──")
    pid3, iid3, total3 = await invoiced(3)
    paid3 = J(await c.post("/payments/manual", headers=fin, json={
        "invoice_id": iid3, "amount": total3, "reference": f"DUP-{TAG}"}))
    r = await c.delete(f"/finance/invoices/{iid3}", headers=fin)
    check("a paid invoice cannot be deleted",
          r.status_code == 409 and "reverse" in why(r), f"{r.status_code} {why(r)}")
    got = J(await c.get(f"/finance/invoices/{iid3}", headers=fin))
    r = await c.post(f"/payments/{got['payments'][0]['id']}/reverse", headers=d,
                     json={"reason": "duplicate invoice, money belongs elsewhere"})
    check("...the payment is reversed instead", r.status_code == 201,
          f"{r.status_code} {why(r)}")
    r = await c.delete(f"/finance/invoices/{iid3}", headers=fin)
    check("...and now the duplicate can go, exactly as the refusal said",
          r.status_code == 204, f"{r.status_code} {why(r)}")
    check("(and the claim row is quiet about it)", paid3.get("status") == "verified",
          str(paid3.get("status")))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)


asyncio.run(main())

"""Beban Pokok Penjualan (5101) is booked when the job is paid in full.

The cost of the goods reaches 5101 when the job they were bought for has been
invoiced and the customer has paid every invoice — not when the purchasing PO
is approved. Until then the goods sit in Persediaan, where receiving put them.

* Approving the PO books nothing.
* Receiving: Persediaan up, Hutang Pembelian Belum Ditagih up (Utang Usaha
  once the supplier invoices) — HPP still nothing.
* The job paid in full: what was received moves from Persediaan to 5101.
* The payment reversed (no longer paid in full): taken back.
* Goods received after the job was paid: their cost follows them to 5101.
* A cancelled order books nothing; the books stay balanced throughout.
"""
import asyncio, os, sys, uuid
from datetime import date
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123",
    STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import httpx, logging; logging.disable(logging.INFO)
TAG = uuid.uuid4().hex[:5].upper()
PASS, FAIL = [], []
def check(n, c, d=""):
    (PASS if c else FAIL).append(n); print(("  PASS " if c else "  FAIL ")+n+(f"  [{d}]" if d and not c else ""))
def J(r):
    try: return r.json()
    except Exception: return {"_": r.text[:200]}

HPP, STOCK, AP, UNBILLED = "5101", "110401", "210101", "2102-03"


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    from app.core.db import SessionLocal
    from app.models.account import Account
    from app.models.finance import Invoice
    from sqlalchemy import select
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d, s1, pur, fin = [await login(f"{x}@demo.local")
                       for x in ("director", "sales1", "purchasing", "finance")]

    async def bal():
        async with SessionLocal() as s:
            rows = (await s.scalars(select(Account).where(
                Account.account_no.in_([HPP, STOCK, AP, UNBILLED])))).all()
            return {a.account_no: float(a.balance or 0) for a in rows}

    def moved(a, b, acc):
        return round(b[acc] - a[acc], 2)

    async with SessionLocal() as s:
        hpp = await s.scalar(select(Account).where(Account.account_no == HPP))
    check("5101 is an account that takes postings, not a header the reports skip",
          hpp is not None and hpp.is_parent is False)

    # A won job.
    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT HPP {TAG}", "industry": "mining"}))["id"]
    pr = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust, "items": [{"description": f"CHAIN {TAG}", "qty": 10, "uom": "pcs"}]}))
    await c.post(f"/price-requests/{pr['id']}/submit", headers=s1)
    await c.post(f"/price-requests/{pr['id']}/price", headers=pur, json={
        "items": [{"line_no": 1, "cost_price": 100_000, "basis": "unit"}]})
    await c.post(f"/price-requests/{pr['id']}/approve", headers=d, json={
        "items": [{"line_no": 1, "sell_price": 200_000, "basis": "unit"}]})
    q = J(await c.post(f"/quotations/from-price-request/{pr['id']}", headers=s1))
    await c.post(f"/quotations/{q['id']}/submit", headers=s1)
    await c.post(f"/quotations/{q['id']}/approve", headers=d, json={"notes": ""})
    cpo = J(await c.post("/customer-pos", headers=s1, json={
        "customer_id": cust, "quotation_id": q["id"], "number": f"CPO-{TAG}",
        "items": [{"description": f"CHAIN {TAG}", "qty": 10, "unit_price": 200_000}],
        "is_downpayment": False}))
    pid = J(await c.post(f"/customer-pos/{cpo['id']}/approve", headers=d, json={"notes": ""}))["project_id"]
    sup = J(await c.post("/purchasing/suppliers", headers=pur, json={"name": f"PT Pemasok HPP {TAG}"}))["id"]

    def order(qty, price, desc):
        return c.post("/purchasing/po", headers=d, json={
            "supplier_id": sup, "project_id": pid, "po_date": date.today().isoformat(),
            "items": [{"description": f"{desc} {TAG}", "qty": qty, "uom": "pcs",
                       "unit_price": price, "amount": qty * price}], "total": qty * price})

    print("\n── ordered and received ──")
    b0 = await bal()
    po = J(await order(10, 100_000, "CHAIN"))
    b1 = await bal()
    check("approving the purchasing PO books no cost", moved(b0, b1, HPP) == 0, str(moved(b0, b1, HPP)))
    r = await c.post(f"/purchasing/po/{po['id']}/gr", headers=pur, json={
        "items": [{"description": f"CHAIN {TAG}", "qty": 10}]})
    b2 = await bal()
    check("receiving puts it in Persediaan, owed on Hutang Pembelian Belum Ditagih",
          r.status_code == 201 and moved(b1, b2, STOCK) == 1_000_000
          and moved(b1, b2, UNBILLED) == 1_000_000 and moved(b1, b2, AP) == 0,
          f"{r.status_code} {moved(b1, b2, STOCK)} {moved(b1, b2, UNBILLED)} {moved(b1, b2, AP)}")
    check("...still no cost in 5101 — the customer hasn't paid", moved(b1, b2, HPP) == 0)

    print("\n── the customer pays ──")
    async with SessionLocal() as s:
        inv = Invoice(number=f"INV-HPP-{TAG}", customer_id=uuid.UUID(cust), project_id=uuid.UUID(pid),
                      status="approved", issue_date=date.today(), due_date=date.today(),
                      amount=2_000_000, tax_amount=0, total=2_000_000)
        s.add(inv); await s.commit(); inv_id = str(inv.id)
    r = await c.post("/payments/manual", headers=fin, json={"invoice_id": inv_id, "amount": 1_000_000})
    b3 = await bal()
    check("half paid: still nothing in 5101", r.status_code == 201 and moved(b2, b3, HPP) == 0,
          f"{r.status_code} {moved(b2, b3, HPP)}")
    r = await c.post("/payments/manual", headers=fin, json={"invoice_id": inv_id, "amount": 1_000_000})
    from app.models.finance import Payment
    async with SessionLocal() as s:
        pay2 = str(await s.scalar(select(Payment.id).where(
            Payment.invoice_id == uuid.UUID(inv_id), Payment.amount > 0)
            .order_by(Payment.created_at.desc()).limit(1)))
    b4 = await bal()
    check("paid in full: what was received moves to 5101",
          r.status_code == 201 and moved(b3, b4, HPP) == 1_000_000, f"{r.status_code} {moved(b3, b4, HPP)}")
    check("...out of Persediaan", moved(b3, b4, STOCK) == -1_000_000, str(moved(b3, b4, STOCK)))

    print("\n── more arrives after payment ──")
    po2 = J(await order(2, 50_000, "LINK"))
    await c.post(f"/purchasing/po/{po2['id']}/gr", headers=pur, json={
        "items": [{"description": f"LINK {TAG}", "qty": 2}]})
    b5 = await bal()
    check("goods received for a paid job go straight to 5101",
          moved(b4, b5, HPP) == 100_000 and moved(b4, b5, STOCK) == 0,
          f"{moved(b4, b5, HPP)} {moved(b4, b5, STOCK)}")

    print("\n── the payment reversed ──")
    if pay2:
        r = await c.post(f"/payments/{pay2}/reverse", headers=d, json={"reason": f"bounced {TAG}"})
        b6 = await bal()
        check("no longer paid in full: the cost goes back to Persediaan",
              r.status_code in (200, 201) and moved(b5, b6, HPP) == -1_100_000
              and moved(b5, b6, STOCK) == 1_100_000, f"{r.status_code} {moved(b5, b6, HPP)} {J(r)}"[:200])
    else:
        check("the payment id came back to reverse", False, str(J(r))[:200])

    print("\n── the journal and the books ──")
    from app.models.finance import LedgerEntry
    async with SessionLocal() as s:
        rows = (await s.scalars(select(LedgerEntry).where(
            LedgerEntry.source_type == "supplier_po_cogs",
            LedgerEntry.source_ref == po["number"]))).all()
    check("each booking is a pair naming the PO",
          rows and {r.account_no for r in rows} == {HPP, STOCK}, str([(r.account_no, r.amount) for r in rows]))
    bs = J(await c.get("/finance/reports/balance-sheet", headers=fin))
    check("the balance sheet balances", bs.get("balanced") is True, str(bs.get("balanced")))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

"""Finance check: each kind of disagreement is found, in its own section.

Planted, one of each, then read back through the check:

* an approved invoice nobody paid → unpaid, with who issued it and how late;
* "paid" with only part of the money, and unpaid with all of it → status;
* more money than the invoice → overpaid;
* a payment with no ledger lines → missing from the books;
* ledger lines for a payment that's gone → ledger with no payment;
* a receipt finance verified that never became a payment → not counted;
* an invoice left with finance ten days → waiting on finance.

Finance and the director can run it, sales can't; the Excel copy has a sheet
per finding.
"""
import asyncio, os, sys, uuid
from datetime import UTC, date, datetime, timedelta
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


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    from app.core.db import SessionLocal
    from app.models.finance import Invoice, LedgerEntry, Payment
    from app.models.payment_claim import PaymentClaim
    from app.models.user import User
    from sqlalchemy import select
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    fin = await login("finance@demo.local")
    s1 = await login("sales1@demo.local")
    cust = uuid.UUID(J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT CEK {TAG}", "industry": "mining"}))["id"])

    n = lambda k: f"INV-{TAG}-{k}"
    async with SessionLocal() as s:
        admin = await s.scalar(select(User).where(User.email == "admin@demo.local"))
        def inv(k, status, total, **kw):
            i = Invoice(number=n(k), customer_id=cust, status=status, amount=total, total=total,
                        issue_date=date.today() - timedelta(days=40), issued_by=admin.id,
                        due_date=date.today() - timedelta(days=10), **kw)
            s.add(i); return i
        a = inv("A", "approved", 1_000_000)
        b = inv("B", "paid", 1_000_000)
        cc = inv("C", "approved", 1_000_000)
        dd = inv("D", "paid", 500_000)
        e = inv("E", "partial", 1_000_000)
        f = inv("F", "approved", 800_000)
        g = inv("G", "pending_finance", 300_000)
        await s.flush()
        g.created_at = datetime.now(UTC) - timedelta(days=10)
        def pay(i, amt, ledger=True):
            p = Payment(invoice_id=i.id, amount=amt, paid_at=datetime.now(UTC))
            s.add(p); return p
        pb, pc, pd, pe = pay(b, 400_000), pay(cc, 1_000_000), pay(dd, 700_000), pay(e, 200_000)
        await s.flush()
        for p in (pb, pc, pd):          # these reached the books; E's didn't
            s.add(LedgerEntry(entry_date=date.today(), account_no="1101-01", account_type="Cash & Bank",
                              amount=float(p.amount), source_type="payment", source_id=p.id,
                              source_ref="x", memo="test"))
        gone = uuid.uuid4()
        s.add(LedgerEntry(entry_date=date.today(), account_no="110301", account_type="Accounts Receivable",
                          amount=-123_000, source_type="payment", source_id=gone,
                          source_ref=n("GONE"), memo=f"orphan {TAG}"))
        s.add(PaymentClaim(invoice_id=f.id, amount=300_000, status="verified"))
        await s.commit()

    r = await c.get("/finance/check", headers=s1)
    check("sales can't run it", r.status_code == 403, str(r.status_code))
    r = await c.get("/finance/check", headers=fin)
    out = J(r)
    check("finance runs it", r.status_code == 200, f"{r.status_code} {str(out)[:160]}")
    sec = {x["key"]: x for x in out.get("sections", [])}
    def has(key, k, **want):
        rows = [x for x in sec.get(key, {}).get("rows", []) if x.get("invoice") == n(k)]
        return bool(rows) and all(rows[0].get(f) == v for f, v in want.items())

    check("the unpaid invoice is listed, with who issued it and how late",
          has("unpaid", "A", issued_by="Admin Demo", outstanding=1_000_000, days_overdue=10),
          str([x for x in sec["unpaid"]["rows"] if x["invoice"] == n("A")]))
    check("'paid' with only part of the money: should be partial", has("status_mismatch", "B", should_be="partial"))
    check("unpaid with all the money in: should be paid", has("status_mismatch", "C", should_be="paid"))
    check("more money than the invoice: overpaid", has("overpaid", "D", paid=700_000))
    check("a payment with no ledger lines: missing from the books",
          any(x["invoice"] == n("E") and x["amount"] == 200_000 for x in sec["payment_no_ledger"]["rows"]))
    check("ledger lines for a payment that's gone",
          any(x["for"] == n("GONE") for x in sec["ledger_no_payment"]["rows"]))
    check("a verified receipt that never became a payment: not counted",
          has("receipts_not_counted", "F", verified_receipts=300_000))
    check("left with finance ten days: waiting on finance", has("stuck", "G", waiting_days=10))
    check("the Piutang reconciliation has its figures",
          [x["figure"] for x in sec["piutang"]["rows"]][0].startswith("Piutang account"))

    r = await c.get("/finance/check.xlsx", headers=d)
    from io import BytesIO
    from openpyxl import load_workbook
    wb = load_workbook(BytesIO(r.content))
    check("the Excel copy has a summary and a sheet per finding",
          r.status_code == 200 and wb.sheetnames[0] == "Summary" and "Unpaid invoices" in wb.sheetnames
          and "Payments missing from the books" in wb.sheetnames, str(wb.sheetnames))
    cells = [str(v) for row in wb["Unpaid invoices"].iter_rows(values_only=True) for v in row if v is not None]
    check("...with the rows in it", n("A") in cells)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

"""Money from deleted records, and payments larger than the invoice.

INV-2026-0001 (Rp 4.267.728) showed a payment of Rp 9.990.000.000 on Piutang,
dated before it was issued. That payment belonged to a test invoice of the
same number, deleted in a data clean-up: the clean-up took the invoice and its
payments but left the payments' postings — they point at the payment, not the
invoice — and never moved any balance back. And nothing stopped a payment
larger than the invoice being recorded in the first place.

* A payment above what the invoice still owes is refused.
* A posting whose record is gone reads "Record deleted" on the ledger, with no
  link; a live payment links to its invoice.
* The director takes it off the books — both sides — and the balances move back.
* The clean-up now takes a deleted invoice's payment postings with it, and
  moves the balances back.
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

AR, BANK = "110301", "1101-01"


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    from app.core.db import SessionLocal
    from app.models.account import Account
    from app.models.finance import Invoice, LedgerEntry, Payment
    from app.api.v1.endpoints.maintenance import CONFIRM_PHRASE
    from sqlalchemy import select, delete, func
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d, fin, s1 = [await login(f"{x}@demo.local") for x in ("director", "finance", "sales1")]

    async def bal():
        async with SessionLocal() as s:
            rows = (await s.scalars(select(Account).where(Account.account_no.in_([AR, BANK])))).all()
            return {a.account_no: float(a.balance or 0) for a in rows}

    def moved(a, b, no):
        return round(b[no] - a[no], 2)

    cust = J(await c.post("/customers", headers=s1, json={"company_name": f"PT Sisa {TAG}",
                                                          "industry": "mining"}))["id"]

    async def invoice(number, total):
        async with SessionLocal() as s:
            inv = Invoice(number=number, customer_id=uuid.UUID(cust), status="approved",
                          issue_date=date.today(), due_date=date.today(),
                          amount=total, tax_amount=0, total=total)
            s.add(inv); await s.commit()
            return str(inv.id)

    print("\n── a payment can't be more than the invoice ──")
    real = await invoice(f"INV-R-{TAG}", 4_267_728)
    r = await c.post("/payments/manual", headers=fin, json={"invoice_id": real, "amount": 9_990_000_000})
    check("Rp 9.990.000.000 on a Rp 4.267.728 invoice is refused", r.status_code == 400
          and "4.267.728" in J(r)["errors"][0]["message"], f"{r.status_code} {J(r)}"[:200])
    r = await c.post("/payments/manual", headers=fin, json={"invoice_id": real, "amount": 4_267_728})
    check("...the right amount goes through", r.status_code == 201, str(r.status_code))

    print("\n── a test invoice deleted the old way ──")
    old = await invoice(f"INV-T-{TAG}", 9_990_000_000)
    await c.post("/payments/manual", headers=fin, json={"invoice_id": old, "amount": 9_990_000_000})
    async with SessionLocal() as s:            # what the old clean-up did
        await s.execute(delete(Invoice).where(Invoice.id == uuid.UUID(old)))
        await s.commit()
    L = J(await c.get(f"/journals/account/{AR}", headers=fin))
    left = [i for i in L["items"] if i.get("source_ref") == f"INV-T-{TAG}"]
    live = [i for i in L["items"] if i.get("source_ref") == f"INV-R-{TAG}"]
    check("its payment still sits on Piutang, marked 'Record deleted', no link",
          len(left) == 1 and left[0]["orphan"] and left[0]["label"] == "Record deleted"
          and left[0]["link"] is None, str(left)[:300])
    check("a live payment links to its invoice",
          live and live[0]["link"] == f"/invoices/{real}" and not live[0]["orphan"], str(live)[:200])
    lst = J(await c.get("/accounts/leftovers", headers=d))
    g = next((x for x in lst if x["ref"] == f"INV-T-{TAG}"), None)
    check("the director's list shows it, with both sides",
          g and {l["account_no"] for l in g["lines"]} == {AR, BANK}, str(g)[:300])

    print("\n── taken off the books ──")
    r = await c.post("/accounts/leftovers/remove", headers=fin,
                     json={"source_type": g["source_type"], "source_id": g["source_id"]})
    check("finance can't", r.status_code == 403, str(r.status_code))
    b0 = await bal()
    r = await c.post("/accounts/leftovers/remove", headers=d,
                     json={"source_type": g["source_type"], "source_id": g["source_id"]})
    b1 = await bal()
    check("the director takes it off", r.status_code == 200, f"{r.status_code} {J(r)}"[:200])
    check("...Piutang back up by 9.99 billion, the bank back down",
          moved(b0, b1, AR) == 9_990_000_000 and moved(b0, b1, BANK) == -9_990_000_000,
          f"{moved(b0, b1, AR)} {moved(b0, b1, BANK)}")
    async with SessionLocal() as s:
        n = await s.scalar(select(func.count()).select_from(LedgerEntry)
                           .where(LedgerEntry.source_ref == f"INV-T-{TAG}"))
    check("...and its lines are gone", n == 0, str(n))
    r = await c.post("/accounts/leftovers/remove", headers=d,
                     json={"source_type": g["source_type"], "source_id": g["source_id"]})
    check("again: nothing there", r.status_code == 404, str(r.status_code))
    async with SessionLocal() as s:
        pid = await s.scalar(select(Payment.id).where(Payment.invoice_id == uuid.UUID(real)))
    r = await c.post("/accounts/leftovers/remove", headers=d,
                     json={"source_type": "payment", "source_id": str(pid)})
    check("a payment whose invoice exists can't be taken off this way", r.status_code == 409, str(r.status_code))

    print("\n── the clean-up now takes the postings with it ──")
    gone = await invoice(f"INV-C-{TAG}", 500_000)
    await c.post("/payments/manual", headers=fin, json={"invoice_id": gone, "amount": 500_000})
    b2 = await bal()
    r = await c.post("/maintenance/records/delete", headers=d, json={
        "targets": [{"type": "invoice", "id": gone}], "confirm": CONFIRM_PHRASE,
        "allow_financial": True})
    b3 = await bal()
    check("deleting a paid invoice in the clean-up works", r.status_code == 200, f"{r.status_code} {J(r)}"[:200])
    async with SessionLocal() as s:
        n = await s.scalar(select(func.count()).select_from(LedgerEntry)
                           .where(LedgerEntry.source_ref == f"INV-C-{TAG}"))
    check("...its payment's postings go with it", n == 0, str(n))
    check("...and Piutang and the bank move back", moved(b2, b3, AR) == 500_000
          and moved(b2, b3, BANK) == -500_000, f"{moved(b2, b3, AR)} {moved(b2, b3, BANK)}")
    lst = J(await c.get("/accounts/leftovers", headers=d))
    check("...nothing left behind", not any(x["ref"] == f"INV-C-{TAG}" for x in lst))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

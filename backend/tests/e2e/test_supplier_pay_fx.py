"""Paying a supplier: from the bank finance chooses, at the rate really paid.

* **Which bank.** The payment leaves the account finance picks — BNI, Kas
  Besar — not BCA whatever was used.
* **The real rate is the cost.** A foreign PO's rate is an estimate; the bank
  converts at the real one. Finance gives the amount in the supplier's
  currency and the rate it went at. The payment settles the debt by what
  left the bank, and the difference from the estimate goes onto the goods'
  cost (Persediaan, or HPP once the job is paid) — not to Laba/Rugi
  Terealisasi, which no longer moves.
"""
import asyncio, os, sys, uuid
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

BNI, BCA, KAS, FX, AP, STOCK, UNB = "1101-02", "1101-01", "1102-02", "7200-04", "210101", "110401", "2102-03"


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    from app.core.db import SessionLocal
    from app.models.account import Account
    from sqlalchemy import select
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    fin = await login("finance@demo.local")
    pur = await login("purchasing@demo.local")

    async def balances():
        async with SessionLocal() as s:
            rows = (await s.scalars(select(Account).where(
                Account.account_no.in_([BNI, BCA, KAS, FX, AP, STOCK, UNB])))).all()
            return {a.account_no: float(a.balance or 0) for a in rows}

    def moved(before, after, acc):
        return round(after[acc] - before[acc], 2)

    sup = J(await c.post("/purchasing/suppliers", headers=pur, json={"name": f"JIANGSU KURS {TAG}"}))["id"]
    po = J(await c.post("/purchasing/po", headers=d, json={
        "supplier_id": sup, "po_date": "2026-10-14", "currency": "CNY", "fx_rate": 3000,
        "items": [{"description": f"CHAIN {TAG}", "qty": 10, "uom": "pcs",
                   "unit_price": 100, "amount": 1000}], "total": 1000}))["id"]

    print("\n── a CNY order estimated at 3,000, paid ¥400 at 3,100 from BNI ──")
    b0 = await balances()
    r = await c.post(f"/finance/payables/{po}/pay", headers=fin, json={
        "currency_amount": 400, "fx_rate": 3100, "bank_account_no": BNI,
        "method": "Transfer", "reference": f"TT-{TAG}"})
    out = J(r)
    check("finance pays CNY 400 at the real rate", r.status_code == 201, f"{r.status_code} {out}"[:200])
    check("...which settles Rp 1.240.000 of the debt — what left the bank",
          out.get("paid") == 1_240_000 and out.get("bank_amount") == 1_240_000,
          f"{out.get('paid')} {out.get('bank_amount')}")
    check("...Rp 40.000 more than the PO's estimate", out.get("fx_difference") == 40_000,
          str(out.get("fx_difference")))
    check("...from BNI, as chosen", out.get("bank_account_no") == BNI and "Bni" in (out.get("bank_name") or ""),
          str(out.get("bank_name")))
    b1 = await balances()
    check("BNI drops by what really left it", moved(b0, b1, BNI) == -1_240_000, str(moved(b0, b1, BNI)))
    check("...BCA is untouched", moved(b0, b1, BCA) == 0, str(moved(b0, b1, BCA)))
    check("the debt drops by the same", moved(b0, b1, AP) == -1_240_000, str(moved(b0, b1, AP)))
    check("nothing goes to Laba/Rugi Terealisasi", moved(b0, b1, FX) == 0, str(moved(b0, b1, FX)))

    print("\n── the goods arrive: the paid part at the rate paid ──")
    await c.post(f"/purchasing/po/{po}/gr", headers=pur, json={
        "items": [{"description": f"CHAIN {TAG}", "qty": 10}]})
    b2 = await balances()
    check("Persediaan: ¥400 at 3,100 + ¥600 at the 3,000 estimate = Rp 3.040.000",
          moved(b1, b2, STOCK) == 3_040_000, str(moved(b1, b2, STOCK)))
    check("...and still nothing on Laba/Rugi Terealisasi", moved(b1, b2, FX) == 0)

    print("\n── the rest at 2,950: the goods cost less ──")
    r = await c.post(f"/finance/payables/{po}/pay", headers=fin, json={
        "currency_amount": 700, "fx_rate": 2950})
    check("paying more than is left is refused, in the supplier's currency",
          r.status_code == 409 and "CNY 600" in str(J(r)), f"{r.status_code} {J(r)}"[:200])
    r = await c.post(f"/finance/payables/{po}/pay", headers=fin, json={"currency_amount": 600})
    check("a foreign payment without the rate is refused", r.status_code == 400
          and "rate" in str(J(r)).lower(), f"{r.status_code} {J(r)}"[:200])
    r = await c.post(f"/finance/payables/{po}/pay", headers=fin, json={
        "currency_amount": 600, "fx_rate": 2950, "bank_account_no": "210101"})
    check("only our own cash or bank accounts can be paid from", r.status_code == 400,
          f"{r.status_code} {J(r)}"[:200])
    r = await c.post(f"/finance/payables/{po}/pay", headers=fin, json={
        "currency_amount": 600, "fx_rate": 2950})
    b3 = await balances()
    check("the rest is paid — from BCA when nothing is chosen", r.status_code == 201
          and moved(b2, b3, BCA) == -1_770_000, f"{r.status_code} {moved(b2, b3, BCA)}")
    check("...Persediaan drops Rp 30.000: the goods cost Rp 3.010.000 in all",
          moved(b2, b3, STOCK) == -30_000, str(moved(b2, b3, STOCK)))
    # Received goods wait on Belum Ditagih until the supplier invoices; paid,
    # that and Utang Usaha together come to nothing owed.
    check("...the debt is settled exactly (Utang Usaha + Belum Ditagih)",
          round(moved(b0, b3, AP) + moved(b0, b3, UNB), 2) == 0,
          f"{moved(b0, b3, AP)} + {moved(b0, b3, UNB)}")
    check("...and Laba/Rugi Terealisasi never moved", moved(b0, b3, FX) == 0, str(moved(b0, b3, FX)))

    rows = J(await c.get("/finance/payables", headers=fin, params={"show": "all"}))["items"]
    row = next(x for x in rows if x["po_id"] == po)
    check("the order now reads paid", row["status"] == "paid", row["status"])
    p1 = row["payments"][0] if row.get("payments") else {}
    check("...and lists each payment with its bank and rate",
          len(row.get("payments", [])) == 2 and "Bni" in (p1.get("bank_name") or "")
          and p1.get("fx_rate") == 3100 and p1.get("currency_amount") == 400
          and p1.get("fx_difference") == 40_000, str(row.get("payments"))[:300])

    print("\n── a rupiah order, paid in cash ──")
    po2 = J(await c.post("/purchasing/po", headers=d, json={
        "supplier_id": sup, "po_date": "2026-10-14",
        "items": [{"description": f"BOLT {TAG}", "qty": 1, "uom": "pcs",
                   "unit_price": 500_000, "amount": 500_000}], "total": 500_000}))["id"]
    b4 = await balances()
    r = await c.post(f"/finance/payables/{po2}/pay", headers=fin, json={
        "amount": 500_000, "bank_account_no": KAS, "method": "Cash"})
    b5 = await balances()
    check("paid from Kas Besar", r.status_code == 201 and moved(b4, b5, KAS) == -500_000,
          f"{r.status_code} {moved(b4, b5, KAS)}")
    check("...with no exchange difference", moved(b4, b5, FX) == 0 and J(r).get("fx_difference") == 0,
          str(J(r).get("fx_difference")))

    r = await c.post(f"/finance/payables/{po2}/pay", headers=pur, json={"amount": 1})
    check("purchasing can't pay suppliers", r.status_code == 403, str(r.status_code))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

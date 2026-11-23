"""Commission on the real selling price, set by finance.

A customer asks for 15.000 on the invoice while 10.000 is what the company
keeps; commission on the paper figure overpays the rep.

* Finance (or the director) approving a claim may set the real selling price
  lower than the invoice, with a reason. Refused: no reason, higher than the
  invoice, zero; sales can't set it.
* The invoiced figure, the real price, the reason and who set it are kept,
  and the rep sees them.
* Once approved only the director can correct it; once paid it is locked,
  and the journal books the corrected amount.
* Left alone, commission is on the invoice exactly as before.
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


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    from app.core.db import SessionLocal
    from sqlalchemy import select
    from app.models.account import Account
    from app.models.finance import Invoice
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)

    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    s1 = await login("sales1@demo.local")
    fin = await login("finance@demo.local")
    adm = await login("admin@demo.local")

    async def paid_job(tag, unit=1_000_000, qty=10):
        cust = J(await c.post("/customers", headers=s1, json={
            "company_name": f"PT Komisi Keu {tag}", "industry": "mining"}))["id"]
        pr = J(await c.post("/price-requests", headers=s1, json={
            "customer_id": cust, "items": [{"description": f"CHAIN {tag}", "qty": qty, "uom": "pcs"}]}))["id"]
        await c.post(f"/price-requests/{pr}/submit", headers=s1)
        await c.post(f"/price-requests/{pr}/price", headers=d, json={
            "items": [{"line_no": 1, "cost_price": unit // 2, "basis": "unit"}]})
        await c.post(f"/price-requests/{pr}/approve", headers=d, json={
            "items": [{"line_no": 1, "sell_price": unit, "basis": "unit"}]})
        q = J(await c.post(f"/quotations/from-price-request/{pr}", headers=s1))["id"]
        await c.post(f"/quotations/{q}/submit", headers=s1)
        await c.post(f"/quotations/{q}/approve", headers=d, json={"notes": ""})
        cpo = J(await c.post("/customer-pos", headers=s1, json={
            "customer_id": cust, "quotation_id": q, "number": f"PO-KK-{tag}",
            "items": [{"description": f"CHAIN {tag}", "qty": qty, "unit_price": unit}],
            "is_downpayment": False}))["id"]
        await c.post(f"/quotations/{q}/won", headers=d)
        proj = J(await c.post(f"/customer-pos/{cpo}/approve", headers=d, json={"notes": ""}))["project_id"]
        await c.post(f"/operation/projects/{proj}/qc", headers=adm, json={"decision": "pass"})
        await c.post(f"/operation/projects/{proj}/issue-invoice", headers=d, data={"invoice_type": "single"})
        async with SessionLocal() as db:
            row = await db.scalar(select(Invoice).where(Invoice.project_id == proj)
                                  .order_by(Invoice.created_at.desc()))
            iid, total = str(row.id), float(row.total or 0)
        await c.post(f"/finance/invoices/{iid}/approve", headers=fin, data={"faktur_pajak_no": f"FP-KK-{tag}"})
        await c.post("/payments/manual", headers=fin, json={
            "invoice_id": iid, "amount": total, "method": "transfer", "reference": f"TRX-KK-{tag}"})
        return proj

    async def bal(no):
        async with SessionLocal() as db:
            a = await db.scalar(select(Account).where(Account.account_no == no))
            return float(a.balance or 0) if a else None

    async def badge(h):
        return int(J(await c.get("/nav/badges", headers=h)).get("commission_to_pay") or 0)

    async def claim_for(tag):
        proj = await paid_job(tag)
        r = await c.post("/commissions", headers=s1, json={"project_id": proj})
        return J(r)

    print("\n── finance sets the real selling price ──")
    cl = await claim_for("R" + TAG)
    invoiced = float(cl["basis_amount"])        # 10 × 1.000.000 = Rp 10.000.000 before PPN
    check("the claim starts on the invoiced figure", invoiced == 10_000_000, str(invoiced))
    r = await c.post(f"/commissions/{cl['id']}/approve", headers=fin, json={"basis_amount": 7_000_000})
    check("a lower price with no reason: refused", r.status_code == 400 and "why" in str(J(r)).lower(),
          f"{r.status_code} {J(r)}"[:160])
    r = await c.post(f"/commissions/{cl['id']}/approve", headers=fin,
                     json={"basis_amount": 12_000_000, "basis_note": "x"})
    check("higher than invoiced: refused", r.status_code == 400, f"{r.status_code} {J(r)}"[:160])
    r = await c.post(f"/commissions/{cl['id']}/approve", headers=fin, json={"basis_amount": 0, "basis_note": "x"})
    check("zero: refused", r.status_code == 400, f"{r.status_code}")
    r = await c.post(f"/commissions/{cl['id']}/approve", headers=s1,
                     json={"basis_amount": 7_000_000, "basis_note": "x"})
    check("sales can't set it", r.status_code == 403, f"{r.status_code}")
    r = await c.post(f"/commissions/{cl['id']}/approve", headers=fin,
                     json={"basis_amount": 7_000_000, "basis_note": "Rp 3 jt kembali ke pelanggan"})
    x = J(r)
    check("finance approves on Rp 7.000.000: commission 2% = Rp 140.000",
          r.status_code == 200 and x.get("amount") == 140_000 and x.get("basis_amount") == 7_000_000,
          f"{r.status_code} {str(x)[:200]}")
    check("...the invoiced figure, the reason and who set it are kept",
          x.get("invoiced_basis") == 10_000_000 and x.get("basis_adjusted") is True
          and x.get("basis_note") == "Rp 3 jt kembali ke pelanggan" and x.get("basis_set_by_name"),
          str(x)[:240])
    mine = next((y for y in J(await c.get("/commissions", headers=s1)) if y["id"] == cl["id"]), {})
    check("the rep sees both figures and the reason", mine.get("invoiced_basis") == 10_000_000
          and mine.get("basis_amount") == 7_000_000 and mine.get("basis_note"), str(mine)[:200])

    print("\n── after approval: the director's ──")
    r = await c.post(f"/commissions/{cl['id']}/basis", headers=fin, json={"basis_amount": 8_000_000, "basis_note": "y"})
    check("finance can't change it once approved", r.status_code == 403, f"{r.status_code}")
    r = await c.post(f"/commissions/{cl['id']}/basis", headers=d,
                     json={"basis_amount": 8_000_000, "basis_note": "Rp 2 jt kembali, bukan 3"})
    x = J(r)
    check("the director corrects it: Rp 8.000.000 → Rp 160.000",
          r.status_code == 200 and x.get("amount") == 160_000 and x.get("invoiced_basis") == 10_000_000,
          f"{r.status_code} {str(x)[:200]}")
    exp0 = await bal("6000-02")
    r = await c.post(f"/commissions/{cl['id']}/mark-paid", headers=fin, json={"cash_account_no": "1101-01"})
    check("paid: the journal books the corrected Rp 160.000",
          r.status_code == 200 and abs((await bal("6000-02")) - exp0 - 160_000) < 0.01, f"{r.status_code}")
    r = await c.post(f"/commissions/{cl['id']}/basis", headers=d, json={"basis_amount": 5_000_000, "basis_note": "z"})
    check("paid: locked, even for the director", r.status_code == 409, f"{r.status_code}")

    print("\n── left alone: as before ──")
    cl2 = await claim_for("N" + TAG)
    x = J(await c.post(f"/commissions/{cl2['id']}/approve", headers=fin, json={}))
    check("no real price set: commission on the invoice, nothing flagged",
          x.get("amount") == 200_000 and x.get("invoiced_basis") == 10_000_000
          and x.get("basis_adjusted") is False and x.get("basis_note") is None, str(x)[:200])

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

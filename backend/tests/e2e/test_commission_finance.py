"""A commission claim goes to finance, and paying it books it.

Asked for: *"when the commission is claimed where does it go — it should go
to finance."*

* The claim counts on finance's badge (and the director's) while it waits.
* Finance approves it at the stated rate; only the director may change it.
* Marked paid from a bank account, it is booked as one journal entry —
  Beban Komisi Penjualan Sales (6000-02) up, that bank down — and both
  balances move by the amount.
* A non-bank account is refused; sales can't pay it.
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

    print("\n── the claim lands in finance's queue ──")
    proj = await paid_job(TAG)
    before_fin = await badge(fin)
    r = await c.post("/commissions", headers=s1, json={"project_id": proj})
    claim = J(r)
    check("sales files the claim", r.status_code == 201, f"{r.status_code} {str(claim)[:160]}")
    check("finance's badge counts it", await badge(fin) == before_fin + 1,
          f"{before_fin} → {await badge(fin)}")
    check("...the director's too", await badge(d) >= 1)
    lst = J(await c.get("/commissions", headers=fin))
    check("finance sees it in the list", any(x["id"] == claim["id"] for x in lst))

    print("\n── finance approves ──")
    r = await c.post(f"/commissions/{claim['id']}/approve", headers=s1, json={})
    check("sales can't approve", r.status_code == 403, str(r.status_code))
    r = await c.post(f"/commissions/{claim['id']}/approve", headers=fin, json={"rate_pct": 5})
    check("finance can't change the rate", r.status_code == 403, f"{r.status_code} {J(r)}")
    r = await c.post(f"/commissions/{claim['id']}/approve", headers=fin, json={})
    got = J(r)
    check("finance approves at the stated rate", r.status_code == 200 and got.get("status") == "approved"
          and float(got.get("rate_pct")) == 2.0, f"{r.status_code} {str(got)[:160]}")
    amount = float(got.get("amount") or 0)

    print("\n── paid, and booked ──")
    r = await c.post(f"/commissions/{claim['id']}/mark-paid", headers=s1, json={})
    check("sales can't mark it paid", r.status_code == 403, str(r.status_code))
    r = await c.post(f"/commissions/{claim['id']}/mark-paid", headers=fin,
                     json={"cash_account_no": "1200-01"})
    check("an account that isn't a bank or cash is refused", r.status_code == 400, f"{r.status_code} {J(r)}")
    exp0, bank0 = await bal("6000-02"), await bal("1101-01")
    r = await c.post(f"/commissions/{claim['id']}/mark-paid", headers=fin,
                     json={"cash_account_no": "1101-01", "paid_on": "2026-11-18"})
    x = J(r)
    check("finance marks it paid", r.status_code == 200 and x.get("status") == "paid",
          f"{r.status_code} {str(x)[:160]}")
    check("...and names the journal it was booked as", bool(x.get("journal_number")), str(x.get("journal_number")))
    exp1, bank1 = await bal("6000-02"), await bal("1101-01")
    check(f"Beban Komisi up by Rp {amount:,.0f}", abs((exp1 - exp0) - amount) < 0.01, f"{exp0} → {exp1}")
    check(f"...the bank down by the same", abs((bank0 - bank1) - amount) < 0.01, f"{bank0} → {bank1}")
    jr = J(await c.get("/journals", headers=fin, params={"q": x.get("journal_number")}))
    rows = jr.get("items", jr) if isinstance(jr, dict) else jr
    e = next((j for j in rows if j.get("number") == x.get("journal_number")), None) if isinstance(rows, list) else None
    check("the entry is posted, from the commission", e is not None and e.get("is_posted") is True
          and e.get("source_type") == "commission", str(e)[:200])
    check("the badge drops once it's paid", await badge(fin) == before_fin, str(await badge(fin)))
    r = await c.post(f"/commissions/{claim['id']}/mark-paid", headers=fin, json={})
    check("it can't be paid twice", r.status_code == 409, str(r.status_code))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

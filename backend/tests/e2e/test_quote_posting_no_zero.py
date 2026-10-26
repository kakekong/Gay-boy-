"""A won quotation posts only what it has: no Rp 0 discount line, and a real
discount as a reduction of revenue.

Diskon Penjualan was a column of "Quotation … posted (discount)" rows, one per
deal won, almost all Rp 0 — a quotation with no discount still wrote a line
for it. Now a zero figure writes nothing (the old zero lines are removed on
boot), a real discount still posts, and nothing is posted before Won.
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


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    from app.core.db import SessionLocal
    from app.models.finance import LedgerEntry
    from app.models.quotation import Quotation
    from sqlalchemy import func, select, update
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d, s1, pur = [await login(f"{x}@demo.local") for x in ("director", "sales1", "purchasing")]

    async def approved_quote(label):
        cust = J(await c.post("/customers", headers=s1, json={
            "company_name": f"PT Diskon {label} {TAG}", "industry": "mining"}))["id"]
        pr = J(await c.post("/price-requests", headers=s1, json={
            "customer_id": cust, "items": [{"description": f"CHAIN {label} {TAG}", "qty": 1, "uom": "pcs"}]}))
        await c.post(f"/price-requests/{pr['id']}/submit", headers=s1)
        await c.post(f"/price-requests/{pr['id']}/price", headers=pur, json={
            "items": [{"line_no": 1, "cost_price": 100_000, "basis": "unit"}]})
        await c.post(f"/price-requests/{pr['id']}/approve", headers=d, json={
            "items": [{"line_no": 1, "sell_price": 1_000_000, "basis": "unit"}]})
        q = J(await c.post(f"/quotations/from-price-request/{pr['id']}", headers=s1))
        await c.post(f"/quotations/{q['id']}/submit", headers=s1)
        await c.post(f"/quotations/{q['id']}/approve", headers=d, json={"notes": ""})
        await c.post("/customer-pos", headers=s1, json={
            "customer_id": cust, "quotation_id": q["id"], "number": f"PO-{label}-{TAG}",
            "items": [{"description": f"CHAIN {label} {TAG}", "qty": 1, "unit_price": 1_000_000}],
            "is_downpayment": False})
        return q

    async def lines(number):
        async with SessionLocal() as s:
            rows = (await s.scalars(select(LedgerEntry).where(
                LedgerEntry.source_type == "quotation", LedgerEntry.source_ref == number))).all()
            return {(r.account_no, float(r.amount)) for r in rows}

    q = await approved_quote("A")
    r = await c.post(f"/quotations/{q['id']}/post-ledger", headers=d)
    check("a quotation that isn't won can't be posted", r.status_code == 409, str(r.status_code))
    check("...and has nothing on the books", not await lines(q["number"]))
    r = await c.post(f"/quotations/{q['id']}/won", headers=d)
    got = await lines(q["number"])
    check("won with no discount: posted", r.status_code == 200 and got, f"{r.status_code} {got}")
    check("...without a Rp 0 discount line", all(abs(a) >= 0.005 for _, a in got)
          and not any(acc == "400004" for acc, _ in got), str(got))

    q2 = await approved_quote("B")
    async with SessionLocal() as s:
        await s.execute(update(Quotation).where(Quotation.id == uuid.UUID(q2["id"]))
                        .values(discount_amount=100_000))
        await s.commit()
    await c.post(f"/quotations/{q2['id']}/won", headers=d)
    got = await lines(q2["number"])
    check("a real discount still posts to Diskon Penjualan — as a reduction",
          ("400004", -100_000.0) in got, str(got))
    rev = [a for acc, a in got if acc == "400001"]
    rec = [a for acc, a in got if acc == "110301"]
    check("...with Penjualan at the full price, so the entry balances",
          rev and rec and abs(rev[0] - 100_000 - (rec[0] - sum(a for acc, a in got
                                                          if acc == "2102-01"))) < 0.01,
          str(got))
    bs = J(await c.get("/finance/reports/balance-sheet", headers=d))
    check("the balance sheet balances", bs.get("balanced") is True, str(bs.get("balanced")))

    async with SessionLocal() as s:
        zeros = await s.scalar(select(func.count()).select_from(LedgerEntry).where(
            LedgerEntry.source_type == "quotation", LedgerEntry.amount == 0))
    check("no Rp 0 quotation lines are left on the books", zeros == 0, str(zeros))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

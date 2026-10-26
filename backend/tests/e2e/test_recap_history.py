"""The recaps' "whole history" button.

Rekap Pembelian and Penjualan show one month; Hutang and Piutang show only
what is still owed. With `all`, each shows the whole history:

* Pembelian / Penjualan: every month there has been, with a month-by-month
  total that adds up to the recap's total.
* Hutang: every purchasing PO, settled ones too, with each payment made.
* Piutang: every invoice issued, paid ones too, with each payment received —
  the aging still counts only what is owed.
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


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    from app.core.db import SessionLocal
    from app.models.finance import Invoice
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d, fin, pur, s1, adm = [await login(f"{x}@demo.local")
                            for x in ("director", "finance", "purchasing", "sales1", "admin")]
    R = "/finance/reports"

    def rows(rep, key):
        return [r for g in rep["groups"] for r in g["rows"] if r.get(key)]

    print("\n── Pembelian and Penjualan: every month ──")
    for name in ("purchase-recap", "sales-recap"):
        month = J(await c.get(f"{R}/{name}", headers=fin))
        whole = J(await c.get(f"{R}/{name}", headers=fin, params={"all": True}))
        tot = "total_idr" if name == "purchase-recap" else "total"
        check(f"{name}: the whole history holds at least this month",
              whole.get("all") is True and whole["count"] >= month["count"],
              f'{whole.get("count")} vs {month.get("count")}')
        check(f"{name}: month by month adds up to the total",
              abs(sum(m["total"] for m in whole["months"]) - whole[tot]) < 1
              and sum(m["count"] for m in whole["months"]) == whole["count"])
        check(f"{name}: newest month first",
              [m["period"] for m in whole["months"]]
              == sorted((m["period"] for m in whole["months"]), reverse=True))

    print("\n── Hutang: settled orders too, with their payments ──")
    sup = J(await c.post("/purchasing/suppliers", headers=pur, json={"name": f"PT Lunas {TAG}"}))["id"]
    po = J(await c.post("/purchasing/po", headers=d, json={
        "supplier_id": sup, "po_date": date.today().isoformat(),
        "items": [{"description": f"BOLT {TAG}", "qty": 2, "uom": "pcs",
                   "unit_price": 100_000, "amount": 200_000}], "total": 200_000}))
    await c.post(f"/purchasing/po/{po['id']}/gr", headers=pur, json={
        "items": [{"description": f"BOLT {TAG}", "qty": 2}]})
    r = await c.post(f"/finance/payables/{po['id']}/pay", headers=fin,
                     json={"amount": 200_000, "reference": f"TRF-{TAG}"})
    check("the order is paid in full", r.status_code == 201, f"{r.status_code} {J(r)}"[:200])
    owed = J(await c.get(f"{R}/payables-recap", headers=fin))
    whole = J(await c.get(f"{R}/payables-recap", headers=fin, params={"all": True}))
    check("a settled order isn't in what we owe today",
          not any(x["po_id"] == po["id"] for x in rows(owed, "po_id")))
    row = next((x for x in rows(whole, "po_id") if x["po_id"] == po["id"]), None)
    check("...but is in the whole history, settled",
          row and row["outstanding"] == 0 and row["paid"] == 200_000, str(row)[:200])
    check("...with the payment made on it",
          row and len(row["payments"]) == 1 and row["payments"][0]["amount"] == 200_000
          and row["payments"][0]["reference"] == f"TRF-{TAG}", str(row and row["payments"]))
    check("the whole history still says what is owed today",
          abs(whole["outstanding"] - owed["outstanding"]) < 1,
          f'{whole["outstanding"]} vs {owed["outstanding"]}')
    r = await c.get(f"{R}/payables-recap", headers=adm, params={"all": True})
    check("admin stays off supplier costs", r.status_code == 403, str(r.status_code))

    print("\n── Piutang: paid invoices too, with their payments ──")
    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Bayar {TAG}", "industry": "mining"}))["id"]
    async with SessionLocal() as s:
        inv = Invoice(number=f"INV-RH-{TAG}", customer_id=uuid.UUID(cust),
                      status="approved", issue_date=date.today(), due_date=date.today(),
                      amount=500_000, tax_amount=0, total=500_000)
        s.add(inv); await s.commit(); inv_id = str(inv.id)
    r = await c.post("/payments/manual", headers=fin, json={"invoice_id": inv_id, "amount": 500_000})
    check("the invoice is paid in full", r.status_code == 201, f"{r.status_code} {J(r)}"[:200])
    owed = J(await c.get(f"{R}/receivables-recap", headers=fin))
    whole = J(await c.get(f"{R}/receivables-recap", headers=fin, params={"all": True}))
    check("a paid invoice isn't in what is owed today",
          not any(x["invoice_id"] == inv_id for x in rows(owed, "invoice_id")))
    row = next((x for x in rows(whole, "invoice_id") if x["invoice_id"] == inv_id), None)
    check("...but is in the whole history, paid, with the payment",
          row and row["outstanding"] == 0 and row["paid"] == 500_000
          and [p["amount"] for p in row["payments"]] == [500_000], str(row)[:250])
    check("...and is in no aging bucket", row and row["bucket"] is None)
    check("the aging is the same as today's",
          all(abs(whole["buckets"][k] - owed["buckets"][k]) < 1 for k in owed["buckets"])
          and abs(whole["outstanding"] - owed["outstanding"]) < 1)

    cat = J(await c.get(f"{R}/catalogue", headers=fin))
    hist = {r["key"] for r in cat["reports"] if r.get("history")}
    check("the four recaps offer the button",
          hist == {"purchase-recap", "sales-recap", "payables-recap", "receivables-recap"}, str(hist))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

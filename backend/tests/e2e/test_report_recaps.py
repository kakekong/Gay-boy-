"""Daftar laporan: Rekap Pembelian, Penjualan, Hutang, Piutang and Buku Besar.

Asked for by finance. Each is checked against documents made here:

* Rekap Pembelian — the month's approved POs by supplier, in rupiah; one
  waiting for the director isn't a purchase yet; a foreign order with no
  rate is counted as such, not as zero.
* Rekap Hutang — received and not yet paid, per supplier; paying it down
  lowers it.
* Rekap Penjualan — invoices issued in the month, DPP / PPN / total / paid.
* Rekap Piutang — what each customer owes, days past due, aging buckets.
* Buku Besar — every account's month, closing where its own ledger closes.
* Admin, kept off supplier costs, sees only the sales side.
"""
import asyncio, os, sys, uuid
from datetime import date, timedelta
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
    d = await login("director@demo.local")
    fin = await login("finance@demo.local")
    pur = await login("purchasing@demo.local")
    adm = await login("admin@demo.local")
    s1 = await login("sales1@demo.local")
    today = date.today()
    ym = {"year": today.year, "month": today.month}

    def report(name, who=fin, **p):
        return c.get(f"/finance/reports/{name}", headers=who, params=p)

    def group(data, key, name):
        # names are stored in capitals
        return next((g for g in data["groups"] if g[key].upper() == name.upper()), None)

    print("\n── Rekap Pembelian ──")
    sup_name = f"PT Rekap {TAG}"
    sup = J(await c.post("/purchasing/suppliers", headers=pur, json={"name": sup_name}))["id"]
    def order(who, total, **extra):
        return c.post("/purchasing/po", headers=who, json={
            "supplier_id": sup, "po_date": today.isoformat(),
            "items": [{"description": f"CHAIN {TAG}", "qty": 1, "uom": "pcs",
                       "unit_price": total, "amount": total}], "total": total, **extra})
    po = J(await order(d, 2_000_000))
    await order(d, 1_000, currency="USD")                 # no rate yet
    await order(pur, 999_000)                            # waits for the director
    R = J(await report("purchase-recap", **ym))
    g = group(R, "supplier", sup_name)
    check("the supplier's approved orders are listed, in rupiah",
          g and g["count"] == 2 and g["total_idr"] == 2_000_000, str(g)[:300])
    check("...the one waiting for the director isn't",
          g and all(r["total_idr"] != 999_000 for r in g["rows"]))
    check("...a dollar order with no rate is counted as such, not as zero",
          R["without_rate"] >= 1 and g and any(r["currency"] == "USD" and r["total_idr"] is None
                                               for r in g["rows"]))

    print("\n── Rekap Hutang ──")
    await c.post(f"/purchasing/po/{po['id']}/gr", headers=pur, json={
        "items": [{"description": f"CHAIN {TAG}", "qty": 1}]})
    H = J(await report("payables-recap"))
    g = group(H, "supplier", sup_name)
    check("goods received and unpaid are owed to the supplier",
          g and g["outstanding"] == 2_000_000 and g["rows"][0]["days_owed"] == 0, str(g)[:300])
    await c.post(f"/finance/payables/{po['id']}/pay", headers=fin, json={"amount": 500_000})
    g = group(J(await report("payables-recap")), "supplier", sup_name)
    check("...paying part of it lowers what's owed", g and g["outstanding"] == 1_500_000,
          str(g and g["outstanding"]))

    print("\n── Rekap Penjualan & Piutang ──")
    cust_name = f"PT Pelanggan {TAG}"
    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": cust_name, "industry": "mining"}))["id"]
    async with SessionLocal() as s:
        inv = Invoice(number=f"INV-{TAG}", customer_id=uuid.UUID(cust), status="approved",
                      issue_date=today, due_date=today - timedelta(days=40),
                      amount=10_000_000, tax_amount=1_100_000, total=11_100_000)
        s.add(inv); await s.commit(); inv_id = str(inv.id)
    r = await c.post("/payments/manual", headers=fin, json={"invoice_id": inv_id, "amount": 3_100_000})
    check("a payment against it is recorded", r.status_code == 201, f"{r.status_code} {J(r)}"[:200])
    S = J(await report("sales-recap", **ym))
    g = group(S, "customer", cust_name)
    check("the month's invoice is a sale: DPP, PPN, total and what's paid",
          g and (g["amount"], g["tax"], g["total"], g["paid"])
          == (10_000_000, 1_100_000, 11_100_000, 3_100_000), str(g)[:300])
    P = J(await report("receivables-recap"))
    g = group(P, "customer", cust_name)
    check("the customer owes the rest", g and g["outstanding"] == 8_000_000, str(g)[:300])
    check("...40 days past due, in the 31–60 bucket",
          g and g["rows"][0]["days_overdue"] == 40 and g["buckets"]["31-60"] == 8_000_000,
          str(g and g["rows"][0]))
    check("...and the buckets add up to the total",
          round(sum(P["buckets"].values()), 2) == P["outstanding"])

    print("\n── Buku Besar ──")
    B = J(await report("general-ledger", **ym))
    bca = next((a for a in B["accounts"] if a["account_no"] == "1101-01"), None)
    page = J(await c.get("/journals/account/1101-01", headers=fin,
                         params={"period": f"{today.year}-{today.month:02d}"}))
    check("BCA is in the month's general ledger", bca is not None)
    check("...opening and closing exactly as on BCA's own ledger page",
          bca and (bca["opening_balance"], bca["closing_balance"])
          == (page["opening_balance"], page["closing_balance"]),
          f"{bca and (bca['opening_balance'], bca['closing_balance'])} vs "
          f"{(page['opening_balance'], page['closing_balance'])}")
    ap = next((a for a in B["accounts"] if a["account_no"] == "210101"), None)
    check("Utang Usaha shows this month's goods receipt",
          ap and any(i.get("source_ref") == po["number"] for i in ap["items"]))

    print("\n── who sees what ──")
    cat = J(await c.get("/finance/reports/catalogue", headers=fin))
    keys = {r["key"] for r in cat["reports"]}
    check("finance sees all five", {"purchase-recap", "sales-recap", "payables-recap",
                                    "receivables-recap", "general-ledger"} <= keys)
    cat = J(await c.get("/finance/reports/catalogue", headers=adm))
    keys = {r["key"] for r in cat["reports"]}
    check("admin sees the sales side only",
          {"sales-recap", "receivables-recap"} <= keys
          and not keys & {"purchase-recap", "payables-recap", "general-ledger"}, str(keys))
    codes = [(await report(k, who=adm)).status_code
             for k in ("purchase-recap", "payables-recap", "general-ledger")]
    check("...and is refused the other three", codes == [403, 403, 403], str(codes))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

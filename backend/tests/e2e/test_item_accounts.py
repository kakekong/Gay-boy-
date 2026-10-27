"""Each item carries its accounts, the Accurate way (Akun-Akun).

Finance's Accurate screen: every barang names its Persediaan, Penjualan,
Retur Penjualan, Diskon Penjualan, HPP, Retur Pembelian and Belum Tertagih
accounts. Here too — empty means the company default, which "Set as default"
changes — and the books follow them:

* Receiving: the item's Persediaan up, its Belum Tertagih (Hutang Pembelian
  Belum Ditagih) up — not Utang Usaha.
* The supplier's invoice recorded: Belum Ditagih down, Utang Usaha up; paying
  takes Utang Usaha down.
* A won quotation credits the item's Penjualan account.
* The job paid: the item's HPP account up, its Persediaan down.
* Only finance and the director set accounts; a heading, an unknown account
  or the wrong kind (a bank as HPP) is refused; the balance sheet balances throughout.
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

STOCK, UNBILLED, AP = "110402", "2102-03", "210101"


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    from app.core.db import SessionLocal
    from app.models.account import Account
    from app.models.finance import Invoice, LedgerEntry
    from sqlalchemy import select
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d, fin, pur, s1, adm = [await login(f"{x}@demo.local")
                            for x in ("director", "finance", "purchasing", "sales1", "admin")]

    SALES, COGS = f"4009{TAG}", f"5109{TAG}"
    await c.post("/accounts", headers=d, json={"account_no": SALES, "name": f"Penjualan Rantai {TAG}",
                                              "account_type": "Revenue", "balance": 0})
    await c.post("/accounts", headers=d, json={"account_no": COGS, "name": f"HPP Rantai {TAG}",
                                              "account_type": "Cost Of Good Sold", "balance": 0})

    async def bal(*nos):
        async with SessionLocal() as s:
            rows = (await s.scalars(select(Account).where(Account.account_no.in_(nos)))).all()
            return {a.account_no: float(a.balance or 0) for a in rows}

    def moved(a, b, no):
        return round(b.get(no, 0) - a.get(no, 0), 2)

    print("\n── the defaults ──")
    df = J(await c.get("/inventory/item-accounts/defaults", headers=fin))
    by = {f["field"]: f for f in df["fields"]}
    check("seven accounts, as Accurate's Akun-Akun tab",
          [f["label"] for f in df["fields"]] == ["Akun Persediaan", "Akun Penjualan",
            "Akun Ret. Penjualan", "Akun Disk. Penjualan", "Akun HPP", "Akun Ret. Pembelian",
            "Akun Belum Tertagih"], str([f["label"] for f in df["fields"]]))
    check("...defaulting to Persediaan, Penjualan, Retur, Diskon, HPP and Hutang Pembelian Belum Ditagih",
          by["acc_inventory"]["account_no"] == "110401" and by["acc_sales"]["account_no"] == "400001"
          and by["acc_cogs"]["account_no"] == "5101" and by["acc_unbilled"]["account_no"] == UNBILLED
          and by["acc_unbilled"]["account_name"] == "Hutang Pembelian Belum Ditagih", str(by)[:300])

    print("\n── an item with its own accounts ──")
    name = f"ROLLER CHAIN RS 60 AKUN {TAG}"
    item = J(await c.post("/inventory", headers=adm, json={"sku": f"RC-{TAG}", "name": name, "uom": "pcs"}))
    got = J(await c.get(f"/inventory/{item['id']}", headers=fin))["accounts"]["fields"]
    check("a new item shows the defaults", all(not f["own"] for f in got)
          and got[0]["account_no"] == "110401", str(got)[:200])
    want = {"acc_inventory": STOCK, "acc_sales": SALES, "acc_cogs": COGS}
    r = await c.put(f"/inventory/{item['id']}/accounts", headers=pur, json=want)
    check("purchasing can't set an item's accounts", r.status_code == 403, str(r.status_code))
    r = await c.put(f"/inventory/{item['id']}/accounts", headers=fin, json={"acc_sales": "4000"})
    check("a heading is refused", r.status_code == 400, f"{r.status_code} {J(r)}"[:150])
    r = await c.put(f"/inventory/{item['id']}/accounts", headers=fin, json={"acc_cogs": "NOPE-1"})
    check("an unknown account is refused", r.status_code == 400, str(r.status_code))
    r = await c.put(f"/inventory/{item['id']}/accounts", headers=fin, json={"acc_cogs": "1101-01"})
    check("...and so is the wrong kind (a bank as HPP)", r.status_code == 400
          and "Cost Of Good Sold" in J(r)["errors"][0]["message"], f"{r.status_code} {J(r)}"[:200])
    r = await c.put(f"/inventory/{item['id']}/accounts", headers=fin, json=want)
    f = {x["field"]: x for x in J(r)["fields"]}
    check("finance sets them", r.status_code == 200 and f["acc_sales"]["account_no"] == SALES
          and f["acc_sales"]["own"] and not f["acc_unbilled"]["own"], f"{r.status_code} {str(J(r))[:200]}")

    print("\n── a won deal ──")
    cust = J(await c.post("/customers", headers=s1, json={"company_name": f"PT Akun {TAG}",
                                                          "industry": "mining"}))["id"]
    pr = J(await c.post("/price-requests", headers=s1, json={"customer_id": cust, "items": [
        {"description": name, "qty": 10, "uom": "pcs"}]}))["id"]
    await c.post(f"/price-requests/{pr}/submit", headers=s1)
    await c.post(f"/price-requests/{pr}/price", headers=pur, json={"items": [
        {"line_no": 1, "cost_price": 100_000, "basis": "unit"}]})
    await c.post(f"/price-requests/{pr}/approve", headers=d, json={"items": [
        {"line_no": 1, "sell_price": 200_000, "basis": "unit"}]})
    q = J(await c.post(f"/quotations/from-price-request/{pr}", headers=s1))
    await c.post(f"/quotations/{q['id']}/submit", headers=s1)
    await c.post(f"/quotations/{q['id']}/approve", headers=d, json={"notes": ""})
    b0 = await bal(SALES, "400001")
    cpo = J(await c.post("/customer-pos", headers=s1, json={
        "customer_id": cust, "quotation_id": q["id"], "number": f"CPO-{TAG}",
        "items": [{"description": name, "qty": 10, "unit_price": 200_000, "line_no": 1}],
        "is_downpayment": False}))
    await c.post(f"/quotations/{q['id']}/won", headers=d)
    pid = J(await c.post(f"/customer-pos/{cpo['id']}/approve", headers=d, json={"notes": ""}))["project_id"]
    b1 = await bal(SALES, "400001")
    check("the won quotation credits the item's own Penjualan account",
          moved(b0, b1, SALES) == 2_000_000 and moved(b0, b1, "400001") == 0,
          f"{moved(b0, b1, SALES)} {moved(b0, b1, '400001')}")

    print("\n── received, invoiced, paid ──")
    sup = J(await c.post("/purchasing/suppliers", headers=pur, json={"name": f"PT Pemasok Akun {TAG}"}))["id"]
    po = J(await c.post("/purchasing/po", headers=d, json={
        "supplier_id": sup, "project_id": pid, "po_date": date.today().isoformat(),
        "items": [{"description": name, "sku": f"RC-{TAG}", "qty": 10, "uom": "pcs",
                   "unit_price": 100_000, "amount": 1_000_000}], "total": 1_000_000}))
    b2 = await bal(STOCK, UNBILLED, AP)
    r = await c.post(f"/purchasing/po/{po['id']}/gr", headers=pur, json={
        "items": [{"description": name, "qty": 10}]})
    b3 = await bal(STOCK, UNBILLED, AP)
    check("received: the item's Persediaan up", r.status_code == 201 and moved(b2, b3, STOCK) == 1_000_000,
          f"{r.status_code} {moved(b2, b3, STOCK)}")
    check("...owed on Hutang Pembelian Belum Ditagih, not yet on Utang Usaha",
          moved(b2, b3, UNBILLED) == 1_000_000 and moved(b2, b3, AP) == 0,
          f"{moved(b2, b3, UNBILLED)} {moved(b2, b3, AP)}")
    rows = J(await c.get("/finance/payables", headers=fin, params={"show": "all"}))["items"]
    row = next((x for x in rows if x["po_id"] == po["id"]), {})
    check("payables shows it as not invoiced yet", row.get("uninvoiced") == 1_000_000, str(row.get("uninvoiced")))
    r = await c.post(f"/finance/payables/{po['id']}/supplier-invoice", headers=pur, json={"number": f"INV-S-{TAG}"})
    check("purchasing doesn't record the supplier's invoice", r.status_code == 403, str(r.status_code))
    r = await c.post(f"/finance/payables/{po['id']}/supplier-invoice", headers=fin,
                     json={"number": f"INV-S-{TAG}", "date": date.today().isoformat()})
    b4 = await bal(STOCK, UNBILLED, AP)
    check("finance records the supplier's invoice: Belum Ditagih → Utang Usaha",
          r.status_code == 201 and J(r)["moved"] == 1_000_000 and moved(b3, b4, UNBILLED) == -1_000_000
          and moved(b3, b4, AP) == 1_000_000, f"{r.status_code} {J(r)}"[:200])
    r = await c.post(f"/finance/payables/{po['id']}/supplier-invoice", headers=fin, json={"number": f"INV-S-{TAG}"})
    check("the same invoice again, with nothing new received, is refused", r.status_code == 409, str(r.status_code))
    r = await c.post(f"/finance/payables/{po['id']}/pay", headers=fin, json={"amount": 1_000_000})
    b5 = await bal(STOCK, UNBILLED, AP)
    check("paying takes Utang Usaha down", r.status_code == 201 and moved(b4, b5, AP) == -1_000_000,
          f"{r.status_code} {moved(b4, b5, AP)}")

    print("\n── the job paid: its HPP ──")
    b6 = await bal(STOCK, COGS, "5101")
    async with SessionLocal() as s:
        inv = Invoice(number=f"INV-AK-{TAG}", customer_id=uuid.UUID(cust), project_id=uuid.UUID(pid),
                      status="approved", issue_date=date.today(), due_date=date.today(),
                      amount=2_000_000, tax_amount=0, total=2_000_000)
        s.add(inv); await s.commit(); inv_id = str(inv.id)
    await c.post("/payments/manual", headers=fin, json={"invoice_id": inv_id, "amount": 2_000_000})
    b7 = await bal(STOCK, COGS, "5101")
    check("the cost moves to the item's own HPP account, out of its Persediaan",
          moved(b6, b7, COGS) == 1_000_000 and moved(b6, b7, STOCK) == -1_000_000
          and moved(b6, b7, "5101") == 0, f"{moved(b6, b7, COGS)} {moved(b6, b7, STOCK)} {moved(b6, b7, '5101')}")

    print("\n── set as default ──")
    r = await c.put("/inventory/item-accounts/defaults", headers=pur, json={"acc_cogs": COGS})
    check("purchasing can't change the default", r.status_code == 403, str(r.status_code))
    r = await c.put("/inventory/item-accounts/defaults", headers=fin, json={"acc_cogs": COGS})
    other = J(await c.post("/inventory", headers=adm, json={"sku": f"SP-{TAG}", "name": f"SPROCKET {TAG}"}))
    f = {x["field"]: x for x in J(await c.get(f"/inventory/{other['id']}", headers=fin))["accounts"]["fields"]}
    check("a new default is what items without their own take", r.status_code == 200
          and f["acc_cogs"]["account_no"] == COGS and not f["acc_cogs"]["own"], str(f["acc_cogs"]))
    await c.put("/inventory/item-accounts/defaults", headers=fin, json={"acc_cogs": "5101"})

    bs = J(await c.get("/finance/reports/balance-sheet", headers=fin))
    check("the balance sheet balances", bs.get("balanced") is True, str(bs.get("balanced")))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

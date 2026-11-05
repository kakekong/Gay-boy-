"""Other costs on a supplier PO — packaging, freight, a handling fee.

* They sit under the item lines and are part of the PO total, and of what is
  owed and paid.
* They are part of what the goods cost: booked onto the received items'
  Persediaan as the order arrives — half the goods in, half the packaging —
  owed on Belum Ditagih like the goods. A cost changed later moves the books
  by the difference.
* Purchasing's edit goes to the director like any PO edit; finance may
  correct them as it corrects prices; a cost needs a description, never
  below zero.
* The vendor's copy prints them.
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

STOCK, UNBILLED, FX = "110401", "2102-03", "7200-04"


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
    pur = await login("purchasing@demo.local")
    fin = await login("finance@demo.local")

    async def bal():
        async with SessionLocal() as s:
            rows = (await s.scalars(select(Account).where(
                Account.account_no.in_([STOCK, UNBILLED, FX])))).all()
            return {a.account_no: float(a.balance or 0) for a in rows}
    def moved(a, b, acc):
        return round(b[acc] - a[acc], 2)

    name = f"ROLLER {TAG}"
    sup = J(await c.post("/purchasing/suppliers", headers=pur, json={"name": f"PT KEMAS {TAG}"}))["id"]
    po = J(await c.post("/purchasing/po", headers=d, json={
        "supplier_id": sup, "po_date": date.today().isoformat(),
        "items": [{"description": name, "qty": 10, "uom": "pcs",
                   "unit_price": 100_000, "amount": 1_000_000}], "total": 1_000_000}))["id"]
    items = J(await c.get(f"/purchasing/po/{po}", headers=d))["items"]

    print("\n── others on the PO ──")
    r = await c.patch(f"/purchasing/po/{po}", headers=d, json={
        "items": items, "other_costs": [{"description": "Wooden crate packaging", "amount": 200_000}]})
    got = J(await c.get(f"/purchasing/po/{po}", headers=d))
    check("the director adds packaging Rp 200.000", r.status_code == 200
          and got.get("other_costs") == [{"description": "Wooden crate packaging", "amount": 200_000}],
          f"{r.status_code} {got.get('other_costs')}")
    check("...and the PO total is the lines plus it: Rp 1.200.000",
          float(got["total"]) == 1_200_000, str(got["total"]))
    r = await c.patch(f"/purchasing/po/{po}", headers=d, json={
        "other_costs": [{"description": "", "amount": 5}]})
    check("an other cost needs to say what it is for", r.status_code == 400, str(r.status_code))
    r = await c.patch(f"/purchasing/po/{po}", headers=d, json={
        "other_costs": [{"description": "Refund", "amount": -5}]})
    check("...and is never below zero", r.status_code == 400, str(r.status_code))

    print("\n── booked onto the goods as they arrive ──")
    b0 = await bal()
    await c.post(f"/purchasing/po/{po}/gr", headers=pur, json={"items": [{"description": name, "qty": 5}]})
    b1 = await bal()
    check("half received: Persediaan up Rp 500.000 of goods + Rp 100.000, half the packaging",
          moved(b0, b1, STOCK) == 600_000, str(moved(b0, b1, STOCK)))
    check("...owed on Belum Ditagih the same", moved(b0, b1, UNBILLED) == 600_000,
          str(moved(b0, b1, UNBILLED)))
    await c.post(f"/purchasing/po/{po}/gr", headers=pur, json={"items": [{"description": name, "qty": 5}]})
    b2 = await bal()
    check("the rest arrives: the other half too — Rp 1.200.000 in all",
          moved(b0, b2, STOCK) == 1_200_000, str(moved(b0, b2, STOCK)))

    print("\n── changed later ──")
    r = await c.patch(f"/purchasing/po/{po}", headers=d, json={
        "other_costs": [{"description": "Wooden crate packaging", "amount": 250_000},
                        {"description": "Freight to Jakarta", "amount": 50_000}]})
    b3 = await bal()
    check("packaging to Rp 250.000 and freight Rp 50.000: the books move Rp 100.000",
          r.status_code == 200 and moved(b2, b3, STOCK) == 100_000, f"{r.status_code} {moved(b2, b3, STOCK)}")
    got = J(await c.get(f"/purchasing/po/{po}", headers=d))
    check("...and the total is Rp 1.300.000", float(got["total"]) == 1_300_000, str(got["total"]))
    rows = J(await c.get("/finance/payables", headers=fin, params={"show": "all"}))["items"]
    row = next(x for x in rows if x["po_id"] == po)
    check("the payables list owes Rp 1.300.000", abs(row["received_value"] - 1_300_000) < 1
          and abs(row["order_total"] - 1_300_000) < 1, f"{row['received_value']} {row['order_total']}")
    r = await c.post(f"/finance/payables/{po}/pay", headers=fin, json={"amount": 1_300_000})
    rows = J(await c.get("/finance/payables", headers=fin, params={"show": "all"}))["items"]
    row = next(x for x in rows if x["po_id"] == po)
    check("...paid in full, it reads paid", r.status_code == 201 and row["status"] == "paid",
          f"{r.status_code} {row['status']}")

    print("\n── who changes them ──")
    r = await c.patch(f"/purchasing/po/{po}", headers=pur, json={
        "other_costs": [{"description": "Wooden crate packaging", "amount": 999_000}]})
    got = J(await c.get(f"/purchasing/po/{po}", headers=d))
    check("purchasing's change goes to the director, the PO unchanged until then",
          r.status_code in (200, 202) and float(got["total"]) == 1_300_000, f"{r.status_code} {got['total']}")
    r = await c.patch(f"/purchasing/po/{po}", headers=fin, json={
        "other_costs": [{"description": "Freight to Jakarta", "amount": 60_000}]})
    check("finance may correct them too (to the director)", r.status_code in (200, 202),
          f"{r.status_code} {J(r)}"[:160])

    print("\n── the vendor's copy ──")
    r = await c.get(f"/purchasing/po/{po}/export.pdf", headers=pur)
    check("the PDF prints", r.status_code == 200 and r.content[:4] == b"%PDF", str(r.status_code))
    r = await c.get(f"/purchasing/po/{po}/export.xlsx", headers=pur)
    from io import BytesIO
    from openpyxl import load_workbook
    ws = load_workbook(BytesIO(r.content)).active
    cells = [str(v) for row_ in ws.iter_rows(values_only=True) for v in row_ if v is not None]
    check("...and the Excel lists the packaging and the freight",
          "Wooden crate packaging" in cells and "Freight to Jakarta" in cells, str(cells)[:300])

    print("\n── a yuan order ──")
    po2 = J(await c.post("/purchasing/po", headers=d, json={
        "supplier_id": sup, "po_date": date.today().isoformat(), "currency": "CNY", "fx_rate": 2000,
        "items": [{"description": f"SHAFT {TAG}", "qty": 1, "uom": "pcs",
                   "unit_price": 100, "amount": 100}], "total": 100}))["id"]
    items2 = J(await c.get(f"/purchasing/po/{po2}", headers=d))["items"]
    await c.patch(f"/purchasing/po/{po2}", headers=d, json={
        "items": items2, "other_costs": [{"description": "Export packing", "amount": 10}]})
    b4 = await bal()
    await c.post(f"/purchasing/po/{po2}/gr", headers=pur, json={"items": [{"description": f"SHAFT {TAG}", "qty": 1}]})
    b5 = await bal()
    check("¥100 of goods + ¥10 packing at 2.000: Rp 220.000 on Persediaan",
          moved(b4, b5, STOCK) == 220_000, str(moved(b4, b5, STOCK)))
    await c.patch(f"/purchasing/po/{po2}", headers=d, json={"fx_rate": 2100})
    b6 = await bal()
    check("...the rate to 2.100 moves goods and packing both: Rp 11.000",
          moved(b5, b6, STOCK) == 11_000 and moved(b5, b6, FX) == 0, str(moved(b5, b6, STOCK)))

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

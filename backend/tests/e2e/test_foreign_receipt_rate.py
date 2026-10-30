"""A foreign order's receipts are on the books at its rate.

Receiving a yuan order before its rate was set read the rate as 1: ¥5.000 of
goods went onto Persediaan and Utang Usaha as Rp 5.000, and setting the rate
afterwards changed nothing. Now:

* **No rate, nothing booked.** A foreign order received with no rate puts
  nothing on the books — there is no rupiah figure to put.
* **Rate set, booked.** Setting the rate books what was received at it.
* **Rate changed, re-booked.** Changing it moves the books by the difference
  — onto Utang Usaha once the supplier has invoiced.
* **Paid stays paid.** What was already paid stays at the rate it was paid
  against.
* **Old orders.** One booked at 1 comes right on the next sync (the data fix
  runs it once over every foreign order).
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

STOCK, UNBILLED, AP = "110401", "2102-03", "210101"


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    from app.core.db import SessionLocal
    from app.models.account import Account
    from app.models.purchasing import SupplierPO
    from sqlalchemy import select
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    fin = await login("finance@demo.local")
    pur = await login("purchasing@demo.local")

    async def bal():
        async with SessionLocal() as s:
            rows = (await s.scalars(select(Account).where(
                Account.account_no.in_([STOCK, UNBILLED, AP])))).all()
            return {a.account_no: float(a.balance or 0) for a in rows}
    def moved(a, b, acc):
        return round(b[acc] - a[acc], 2)
    async def payable(po):
        async with SessionLocal() as s:
            return float((await s.get(SupplierPO, uuid.UUID(po))).payable_amount or 0)

    sup = J(await c.post("/purchasing/suppliers", headers=pur, json={"name": f"NINGBO KURS {TAG}"}))["id"]
    def new_po(name, rate=None):
        return c.post("/purchasing/po", headers=d, json={
            "supplier_id": sup, "po_date": date.today().isoformat(), "currency": "CNY",
            **({"fx_rate": rate} if rate else {}),
            "items": [{"description": name, "sku": f"FX-{name}", "qty": 50, "uom": "pcs",
                       "unit_price": 100, "amount": 5000}], "total": 5000})

    print("\n── a ¥5.000 order received before its rate is set ──")
    po = J(await new_po(f"GEAR {TAG}"))["id"]
    b0 = await bal()
    r = await c.post(f"/purchasing/po/{po}/gr", headers=pur, json={
        "items": [{"description": f"GEAR {TAG}", "qty": 50}]})
    b1 = await bal()
    check("received", r.status_code == 201, f"{r.status_code} {J(r)}"[:200])
    check("...and nothing is booked as Rp 5.000",
          moved(b0, b1, STOCK) == 0 and moved(b0, b1, UNBILLED) == 0 and await payable(po) == 0,
          f"{moved(b0, b1, STOCK)} {moved(b0, b1, UNBILLED)} {await payable(po)}")

    r = await c.patch(f"/purchasing/po/{po}", headers=fin, json={"fx_rate": 2300})
    b2 = await bal()
    check("finance sets the rate at 2.300", r.status_code == 200, f"{r.status_code} {J(r)}"[:200])
    check("...Persediaan up Rp 11.500.000", moved(b1, b2, STOCK) == 11_500_000, str(moved(b1, b2, STOCK)))
    check("...owed on Belum Ditagih, Rp 11.500.000", moved(b1, b2, UNBILLED) == 11_500_000,
          str(moved(b1, b2, UNBILLED)))
    check("...and the payables list owes it", await payable(po) == 11_500_000, str(await payable(po)))
    led = J(await c.get(f"/journals/account/{UNBILLED}", headers=fin))
    lines = [x for x in led.get("items") or [] if "per CNY" in str(x)]
    check("...the ledger line says at what rate", bool(lines), str(led)[:300])

    r = await c.patch(f"/purchasing/po/{po}", headers=fin, json={"fx_rate": 2300})
    b3 = await bal()
    check("setting the same rate again moves nothing",
          moved(b2, b3, STOCK) == 0 and moved(b2, b3, UNBILLED) == 0)

    print("\n── invoiced, then the rate changes ──")
    r = await c.post(f"/finance/payables/{po}/supplier-invoice", headers=fin,
                     json={"number": f"INV-CN-{TAG}"})
    b4 = await bal()
    check("the supplier's invoice moves it to Utang Usaha", r.status_code in (200, 201)
          and moved(b3, b4, AP) == 11_500_000 and moved(b3, b4, UNBILLED) == -11_500_000,
          f"{r.status_code} {moved(b3, b4, AP)}")
    await c.patch(f"/purchasing/po/{po}", headers=fin, json={"fx_rate": 2400})
    b5 = await bal()
    check("rate to 2.400: Utang Usaha and Persediaan up Rp 500.000 — not Belum Ditagih",
          moved(b4, b5, AP) == 500_000 and moved(b4, b5, STOCK) == 500_000
          and moved(b4, b5, UNBILLED) == 0,
          f"{moved(b4, b5, AP)} {moved(b4, b5, STOCK)} {moved(b4, b5, UNBILLED)}")

    print("\n── paid half, then the rate changes again ──")
    r = await c.post(f"/finance/payables/{po}/pay", headers=fin, json={
        "currency_amount": 2500, "fx_rate": 2450})
    check("¥2.500 paid, settling Rp 6.000.000 at 2.400", r.status_code == 201
          and J(r).get("paid") == 6_000_000, f"{r.status_code} {J(r)}"[:200])
    b6 = await bal()
    await c.patch(f"/purchasing/po/{po}", headers=fin, json={"fx_rate": 2500})
    b7 = await bal()
    check("rate to 2.500 re-books only the unpaid ¥2.500: Rp 250.000",
          moved(b6, b7, AP) == 250_000 and moved(b6, b7, STOCK) == 250_000,
          f"{moved(b6, b7, AP)} {moved(b6, b7, STOCK)}")
    check("...so the ¥2.500 left is owed at Rp 6.250.000",
          round(b7[AP] - b6[AP] + 6_000_000, 2) == 6_250_000 and await payable(po) == 12_250_000,
          str(await payable(po)))

    print("\n── an order booked at 1 before this fix ──")
    po2 = J(await new_po(f"SHAFT {TAG}", rate=2300))["id"]
    await c.post(f"/purchasing/po/{po2}/gr", headers=pur, json={
        "items": [{"description": f"SHAFT {TAG}", "qty": 50}]})
    from app.services.ledger import _bump, revalue_receipts, sync_po_cogs
    async with SessionLocal() as s:          # put it back the way it was booked
        p = await s.get(SupplierPO, uuid.UUID(po2))
        for acc, delta in ((STOCK, 5000 - 11_500_000), (UNBILLED, 5000 - 11_500_000)):
            await _bump(s, acc, delta)
        p.payable_amount = 5000
        p.unbilled = {UNBILLED: 5000}
        p.received_by = {k: 5000 for k in (p.received_by or {})}
        await s.commit()
    b8 = await bal()
    async with SessionLocal() as s:
        p = await s.get(SupplierPO, uuid.UUID(po2))
        got = await revalue_receipts(s, p)
        await sync_po_cogs(s, p)
        await s.commit()
    b9 = await bal()
    check("the data fix books the missing Rp 11.495.000", got == 11_495_000
          and moved(b8, b9, STOCK) == 11_495_000 and moved(b8, b9, UNBILLED) == 11_495_000,
          f"{got} {moved(b8, b9, STOCK)}")
    async with SessionLocal() as s:
        p = await s.get(SupplierPO, uuid.UUID(po2))
        again = await revalue_receipts(s, p)
    check("...and running it again moves nothing", again == 0, str(again))

    print("\n── a rupiah order is untouched ──")
    po3 = J(await c.post("/purchasing/po", headers=d, json={
        "supplier_id": sup, "po_date": date.today().isoformat(),
        "items": [{"description": f"NUT {TAG}", "qty": 2, "uom": "pcs",
                   "unit_price": 50_000, "amount": 100_000}], "total": 100_000}))["id"]
    b10 = await bal()
    await c.post(f"/purchasing/po/{po3}/gr", headers=pur, json={
        "items": [{"description": f"NUT {TAG}", "qty": 2}]})
    b11 = await bal()
    check("received at its own price", moved(b10, b11, STOCK) == 100_000, str(moved(b10, b11, STOCK)))

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

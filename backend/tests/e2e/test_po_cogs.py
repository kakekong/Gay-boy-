"""Beban Pokok Penjualan (5101) is booked when a purchasing PO is approved.

An interim rule — the cost on the books now, the finer points later. On
approval: HPP up, Persediaan down, by the order's value in rupiah. Receiving
then puts Persediaan back up and Utang Usaha up, so after receipt the order is
cost in HPP and debt in Utang Usaha, with Persediaan where it started.

* Purchasing's order books nothing until the director approves it; a
  rejected one never books.
* The director's own order is approved as it's made, so it books at once.
* A new total books the difference; cancelling takes it all back.
* A foreign order with no rate yet books nothing until the rate is set.
* An order approved before this rule isn't suddenly booked when edited.
* The P&L doesn't add its price-request estimate on top for these jobs.
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

HPP, STOCK, AP = "5101", "110401", "210101"


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    from app.core.db import SessionLocal
    from app.models.account import Account
    from app.models.purchasing import SupplierPO
    from sqlalchemy import select, update
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
                Account.account_no.in_([HPP, STOCK, AP])))).all()
            return {a.account_no: float(a.balance or 0) for a in rows}

    def moved(a, b, acc):
        return round(b[acc] - a[acc], 2)

    sup = J(await c.post("/purchasing/suppliers", headers=pur, json={"name": f"PT HPP {TAG}"}))["id"]

    def order(who, desc, qty, price, **extra):
        return c.post("/purchasing/po", headers=who, json={
            "supplier_id": sup, "po_date": "2026-10-18",
            "items": [{"description": f"{desc} {TAG}", "qty": qty, "uom": "pcs",
                       "unit_price": price, "amount": qty * price}],
            "total": qty * price, **extra})

    async def pending(po_id):
        rows = J(await c.get("/approvals", headers=d))
        rows = rows if isinstance(rows, list) else rows.get("items", [])
        return [r for r in rows if r.get("target_id") == po_id]

    async with SessionLocal() as s:
        hpp = await s.scalar(select(Account).where(Account.account_no == HPP))
    check("5101 is an account that takes postings, not a header the reports skip",
          hpp is not None and hpp.is_parent is False)

    print("\n── purchasing's order waits for the director ──")
    b0 = await bal()
    po = J(await order(pur, "CHAIN", 10, 100_000))
    b1 = await bal()
    check("filed by purchasing, nothing is booked yet", moved(b0, b1, HPP) == 0, str(moved(b0, b1, HPP)))
    req = (await pending(po["id"]))[0]["id"]
    r = await c.post(f"/approvals/{req}/approve", headers=d)
    b2 = await bal()
    check("the director approves it", r.status_code == 200, f"{r.status_code} {J(r)}"[:200])
    check("...5101 Beban Pokok Penjualan rises by Rp 1.000.000", moved(b1, b2, HPP) == 1_000_000,
          str(moved(b1, b2, HPP)))
    check("...Persediaan falls by the same", moved(b1, b2, STOCK) == -1_000_000,
          str(moved(b1, b2, STOCK)))

    print("\n── goods received ──")
    r = await c.post(f"/purchasing/po/{po['id']}/gr", headers=pur, json={
        "items": [{"description": f"CHAIN {TAG}", "qty": 10}]})
    b3 = await bal()
    check("receiving all ten", r.status_code == 201, f"{r.status_code} {J(r)}"[:200])
    check("...puts Persediaan back where it started", moved(b1, b3, STOCK) == 0, str(moved(b1, b3, STOCK)))
    check("...the debt is in Utang Usaha", moved(b2, b3, AP) == 1_000_000, str(moved(b2, b3, AP)))
    check("...and the cost stays in HPP", moved(b1, b3, HPP) == 1_000_000)

    print("\n── rejected ──")
    po_r = J(await order(pur, "BOLT", 5, 20_000))
    b4 = await bal()
    await c.post(f"/approvals/{(await pending(po_r['id']))[0]['id']}/reject", headers=d,
                 params={"notes": "not needed"})
    check("a rejected order never books", moved(b4, await bal(), HPP) == 0)

    print("\n── the director's own order, edited, then cancelled ──")
    b5 = await bal()
    po_d = J(await order(d, "SPROCKET", 2, 500_000))
    b6 = await bal()
    check("the director's order books as it's made", moved(b5, b6, HPP) == 1_000_000,
          str(moved(b5, b6, HPP)))
    r = await c.patch(f"/purchasing/po/{po_d['id']}", headers=d, json={
        "items": [{"description": f"SPROCKET {TAG}", "qty": 2, "uom": "pcs",
                   "unit_price": 600_000, "amount": 1_200_000}], "total": 1_200_000})
    b7 = await bal()
    check("a new total books only the difference", r.status_code == 200
          and moved(b6, b7, HPP) == 200_000 and moved(b6, b7, STOCK) == -200_000,
          f"{r.status_code} {moved(b6, b7, HPP)}")
    r = await c.patch(f"/purchasing/po/{po_d['id']}", headers=d, json={"status": "cancelled"})
    b8 = await bal()
    check("cancelling takes it all back", r.status_code == 200 and moved(b5, b8, HPP) == 0
          and moved(b5, b8, STOCK) == 0, f"{r.status_code} {moved(b5, b8, HPP)}")

    print("\n── a foreign order without a rate ──")
    b9 = await bal()
    po_f = J(await order(d, "GEAR", 10, 100, currency="CNY"))
    b10 = await bal()
    check("a CNY order with no rate books nothing yet", moved(b9, b10, HPP) == 0,
          str(moved(b9, b10, HPP)))
    r = await c.patch(f"/purchasing/po/{po_f['id']}", headers=fin, json={"fx_rate": 2_300})
    b11 = await bal()
    check("finance sets the rate: CNY 1.000 × 2.300 is booked", r.status_code == 200
          and moved(b10, b11, HPP) == 2_300_000, f"{r.status_code} {moved(b10, b11, HPP)}")
    await c.patch(f"/purchasing/po/{po_f['id']}", headers=fin, json={"fx_rate": 2_400})
    b12 = await bal()
    check("...a corrected rate books the difference", moved(b11, b12, HPP) == 100_000,
          str(moved(b11, b12, HPP)))

    print("\n── an order from before this rule ──")
    po_o = J(await order(d, "OLD", 1, 300_000))
    async with SessionLocal() as s:     # as if approved before this change
        await s.execute(update(SupplierPO).where(SupplierPO.id == uuid.UUID(po_o["id"]))
                        .values(cogs_posted=None))
        await s.commit()
    b13 = await bal()
    await c.patch(f"/purchasing/po/{po_o['id']}", headers=d, json={
        "items": [{"description": f"OLD {TAG}", "qty": 1, "uom": "pcs",
                   "unit_price": 350_000, "amount": 350_000}], "total": 350_000})
    check("editing an old order doesn't suddenly book it", moved(b13, await bal(), HPP) == 0)

    print("\n── the journal ──")
    from app.models.finance import LedgerEntry
    async with SessionLocal() as s:
        rows = (await s.scalars(select(LedgerEntry).where(
            LedgerEntry.source_type == "supplier_po_cogs",
            LedgerEntry.source_ref == po["number"]))).all()
    check("each booking is a journal pair naming the PO",
          sorted((r.account_no, float(r.amount)) for r in rows)
          == [(STOCK, -1_000_000.0), (HPP, 1_000_000.0)], str([(r.account_no, r.amount) for r in rows]))

    print("\n── the reports ──")
    bs = J(await c.get("/finance/reports/balance-sheet", headers=fin))
    check("the balance sheet balances with the cost booked", bs.get("balanced") is True,
          str(bs.get("balanced")))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

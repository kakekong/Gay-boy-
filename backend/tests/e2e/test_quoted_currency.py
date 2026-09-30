"""A supplier's money reads in its own currency, and in rupiah at its rate.

Lists printed every quoted total and every supplier order as rupiah, so a
1,800 yuan quote read "Rp 1.800". The payloads carry currency and rate; the
supplier's lifetime spend adds a yuan order at its rate, not at face value.
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
    from app.models.purchasing import Supplier, SupplierPO, SupplierPriceRequest
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=120)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")

    async with SessionLocal() as db:
        sup = Supplier(name=f"Jiangsu Rate {TAG}")
        db.add(sup); await db.flush()
        db.add(SupplierPO(number=f"SPO-CNY-{TAG}", supplier_id=sup.id, status="open",
                          currency="CNY", fx_rate=2200, total=1000,
                          items=[{"description": "chain", "qty": 1, "unit_price": 1000}]))
        db.add(SupplierPO(number=f"SPO-IDR-{TAG}", supplier_id=sup.id, status="open",
                          currency="IDR", total=500000,
                          items=[{"description": "pin", "qty": 1, "unit_price": 500000}]))
        db.add(SupplierPriceRequest(number=f"SPR-CNY-{TAG}", supplier_id=sup.id, status="quoted",
                                    currency="CNY", fx_rate=2200,
                                    items=[{"line_no": 1, "description": "chain", "qty": 2,
                                            "quoted_price": 900}]))
        await db.commit()
        sid = str(sup.id)

    s = J(await c.get(f"/purchasing/suppliers/{sid}", headers=d))
    check("lifetime spend counts the yuan order at its rate (1,000 × 2,200 + 500,000)",
          abs(float(s.get("lifetime_value") or 0) - 2_700_000) < 0.01, str(s.get("lifetime_value")))
    po = next((p for p in s.get("purchase_orders", []) if p["number"] == f"SPO-CNY-{TAG}"), {})
    check("its order list says the currency and rate",
          po.get("currency") == "CNY" and po.get("fx_rate") == 2200.0
          and po.get("total_idr") == 2_200_000, str(po))
    spr = next((x for x in s.get("price_requests", []) if x["number"] == f"SPR-CNY-{TAG}"), {})
    check("its supplier requests carry the rate with the quoted total",
          spr.get("currency") == "CNY" and spr.get("fx_rate") == 2200.0
          and spr.get("quoted_total") == 1800, str(spr))

    lst = J(await c.get("/purchasing/po", headers=d))
    mine = next((p for p in lst if p["number"] == f"SPO-CNY-{TAG}"), {})
    check("the PO list says the currency and rate too",
          mine.get("currency") == "CNY" and mine.get("fx_rate") == 2200.0, str(mine)[:200])

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

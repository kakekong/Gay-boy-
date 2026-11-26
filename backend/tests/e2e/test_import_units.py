"""The stock list's units come in as the app's units.

* MTR → meter, LIK / LNK → link, PCS → pcs, SET → set.
* BOX is a unit of its own now: offered in the unit list, and imported as box.
* Opening stock and the buying price come in with them.
"""
import asyncio, io, os, sys, uuid
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


def sheet(rows):
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active; ws.title = "Import"
    for r in rows:
        ws.append(r)
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t/api/v1", timeout=180)
    r = await c.post("/auth/login", json={"email": "director@demo.local", "password": "test-pass-123"})
    d = {"Authorization": f"Bearer {r.json()['access_token']}"}

    units = J(await c.get("/price-requests/catalog", headers=d)).get("units")
    check("box is in the unit list", "box" in (units or []), str(units))

    data = sheet([
        ["Kode Barang", "Nama Barang", "Kuantitas Saldo Awal", "Satuan", "Harga Beli", "Nilai Total Biaya"],
        [f"U1-{TAG}", f"CHAIN {TAG}", 440, "LIK", 27898.67, 12275414.8],
        [f"U2-{TAG}", f"WIRE MESH {TAG}", 90, "MTR", 1128509.44, 101565849.6],
        [f"U3-{TAG}", f"BOLT {TAG}", 3, "BOX", 150000, 450000],
        [f"U4-{TAG}", f"PIN {TAG}", 40, "PCS", 27750, 1110000],
        [f"U5-{TAG}", f"CHAIN ASSY {TAG}", 2, "SET", 17426477.34, 34852954.68],
        [f"U6-{TAG}", f"ROLLER CHAIN {TAG}", 10, "LNK", 5000, 50000],
    ])
    up = lambda: {"file": ("stok.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    p = J(await c.post("/imports/items/preview", headers=d, files=up()))
    by = {x["sku"]: x for x in p.get("rows", [])}
    want = {"U1": "link", "U2": "meter", "U3": "box", "U4": "pcs", "U5": "set", "U6": "link"}
    for k, u in want.items():
        got = (by.get(f"{k}-{TAG}") or {}).get("uom")
        check(f"{k}: comes in as {u}", got == u, str(got))

    r = J(await c.post("/imports/items/commit", headers=d, files=up(), data={"limit": 10, "confirm": "IMPORT"}))
    check("all six are created", r.get("created") == 6, str(r)[:200])
    inv = J(await c.get("/inventory", headers=d, params={"q": TAG}))
    rows = inv.get("items", inv) if isinstance(inv, dict) else inv
    box = next((x for x in rows if x.get("sku") == f"U3-{TAG}"), {})
    check("the box item: 3 box at Rp 150.000", box.get("uom") == "box" and float(box.get("current_stock") or 0) == 3
          and float(box.get("unit_cost") or 0) == 150000, str(box)[:200])

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

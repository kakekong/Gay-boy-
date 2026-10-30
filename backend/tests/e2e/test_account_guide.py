"""Every account explains what moves it.

The ledger page carries "How this account works": what the account is, what
the app posts to it and where (automatic), what can be done by hand, what a
healthy balance looks like — and a warning when the balance isn't one. The
roles are read live, so an account picked up by an item, a salary or an asset
category says so.
"""
import asyncio, os, sys, uuid
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123",
    STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import httpx, logging; logging.disable(logging.INFO)
TAG = uuid.uuid4().hex[:4].upper()
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
    from app.models.account import Account
    from sqlalchemy import update
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d, fin = await login("director@demo.local"), await login("finance@demo.local")

    async def guide(no):
        return J(await c.get(f"/journals/account/{no}", headers=fin))["guide"]

    def says(lines, *words):
        text = " ".join(x["en"] for x in lines)
        return all(w.lower() in text.lower() for w in words)

    print("\n── what moves each account ──")
    g = await guide("110301")
    check("Piutang: up when a quotation is Won, down when a customer pays — both automatic",
          says(g["up"], "Won") and says(g["down"], "payment") and all(x["auto"] for x in g["up"] + g["down"]),
          str(g["roles"]))
    check("...with where it happens", g["up"][0].get("where_en", "").startswith("Quotations"))
    check("...and checked against what is unpaid on invoices",
          g["check"] and set(g["check"]) == {"unpaid_invoices", "balance", "difference"}, str(g.get("check")))
    g = await guide("110401")
    check("Persediaan: up on goods received, down when the job is paid (to HPP)",
          says(g["up"], "received") and says(g["down"], "HPP"))
    g = await guide("2102-03")
    check("Belum Ditagih: up on receipt, down when the supplier's invoice is recorded",
          says(g["up"], "received") and says(g["down"], "supplier's invoice"))
    g = await guide("210101")
    check("Utang Usaha: up on the supplier's invoice, down when the supplier is paid",
          says(g["up"], "supplier's invoice") and says(g["down"], "pays the supplier"))
    g = await guide("5101")
    check("HPP: up when the job is paid, down when a payment is reversed",
          says(g["up"], "paid") and says(g["down"], "reversed"))
    g = await guide("1101-01")
    check("BCA: customer payments land here, suppliers and salaries are paid out",
          {"customer_bank", "bank", "payroll_bank"} <= set(g["roles"]), str(g["roles"]))
    g = await guide("2102-04")
    check("PPh 21: up when a salary is posted; paying it over is by hand",
          says(g["up"], "PPh 21") and not g["down"][0]["auto"])
    g = await guide("720101")
    check("Laba/Rugi Tahun Berjalan: nothing is ever posted to it", says(g["by_hand"], "Nothing is ever posted"))
    g = await guide("6000-11")
    check("Beban Listrik: the app never posts to it — by hand, or the Kas & Bank desk",
          not g["up"] and says(g["by_hand"], "never posts", "Kas & Bank"))
    check("...every account names the by-hand ways", says(g["by_hand"], "journal", "director"))
    check("...in Indonesian too", all(x.get("id") for x in g["by_hand"]) and g["what"]["id"])

    print("\n── read live ──")
    r = await c.post("/assets/categories", headers=d, json={
        "name": f"Kendaraan {TAG}", "asset_account_no": "1200-02", "accum_account_no": "1201-02",
        "expense_account_no": "6000-22"})
    check("an asset category is made", r.status_code == 201, f"{r.status_code} {J(r)}"[:200])
    g = await guide("1201-02")
    check("the accumulated-depreciation account it names now says the depreciation run moves it",
          "dep_accum" in g["roles"] and says(g["up"], "depreciation"), str(g["roles"]))
    g = await guide("6000-22")
    check("...and so does its expense account", "dep_expense" in g["roles"])

    print("\n── warnings ──")
    async with SessionLocal() as s:
        acc = await s.scalar(__import__("sqlalchemy").select(Account).where(Account.account_no == "1101-03"))
        before = float(acc.balance or 0)
        await s.execute(update(Account).where(Account.account_no == "1101-03").values(balance=-500_000))
        await s.commit()
    g = await guide("1101-03")
    check("a bank below zero is flagged", g["warning"] is not None)
    async with SessionLocal() as s:
        await s.execute(update(Account).where(Account.account_no == "1101-03").values(balance=before))
        await s.commit()
    g = await guide("1101-03")
    check("...and not when it isn't", g["warning"] is None or before < 0)
    g = await guide("400004")
    check("Diskon Penjualan below zero is normal — no warning", g["warning"] is None)

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

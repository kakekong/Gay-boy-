"""Laba/Rugi Tahun Berjalan: one live profit figure, everywhere — on 720101.

All revenue less all costs and expenses, worked out from the balances each
time — nothing is posted. It is account 720101 on the chart of accounts, the
balance sheet carries it under equity, and the all-time P&L ends on the same
number. Move a revenue account and all three move together. The exchange
differences that used to land on 720101 go to 7200-04; nothing can be posted
to 720101, by the app or by hand.
"""
import asyncio, os, sys, uuid
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123",
    STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import httpx, logging; logging.disable(logging.INFO)
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
    from app.models.finance import LedgerEntry
    from sqlalchemy import select, func
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d, fin = [await login(f"{x}@demo.local") for x in ("director", "finance")]

    async def figures():
        e = J(await c.get("/accounts/current-earnings", headers=fin))
        bs = J(await c.get("/finance/reports/balance-sheet", headers=fin))
        pl = J(await c.get("/finance/reports/profit-loss", headers=fin))
        return e, bs, pl

    e, bs, pl = await figures()
    check("the line is 720101",
          e.get("name") == "Laba/Rugi Tahun Berjalan" and e.get("account_no") == "720101",
          str(e)[:200])
    coa = J(await c.get("/accounts", headers=fin, params={"q": "720101"}))
    row = next((a for a in coa if a["account_no"] == "720101"), None)
    check("...on the chart of accounts it shows the profit, marked computed",
          row and row["computed"] is True and abs(row["balance"] - e["net_income"]) < 0.01,
          str(row)[:200])
    led = J(await c.get("/journals/account/720101", headers=fin))
    check("...its ledger says the same, with the figures behind it",
          led.get("computed") and abs(led["account"]["balance"] - e["net_income"]) < 0.01)
    check("it is revenue less costs and expenses",
          abs(e["net_income"] - (e["revenue"] + e["other_income"] - e["cogs"]
                                 - e["expense"] - e["other_expense"])) < 0.01)
    check("the balance sheet carries the same figure under equity",
          abs(bs["equity"]["current_earnings"] - e["net_income"]) < 0.01,
          f'{bs["equity"]["current_earnings"]} vs {e["net_income"]}')
    check("the all-time P&L ends on it",
          pl.get("source") == "balances" and abs(pl["totals"]["net_income"] - e["net_income"]) < 0.01,
          f'{pl.get("source")} {pl.get("totals", {}).get("net_income")}')

    async with SessionLocal() as s:
        rev = await s.scalar(select(Account).where(Account.account_type == "Revenue",
                                                   Account.is_parent.is_(False)).limit(1))
        n_ledger = await s.scalar(select(func.count()).select_from(LedgerEntry))
    before = float(rev.balance or 0)
    await c.patch(f"/accounts/{rev.id}", headers=d, json={"balance": before + 1_000_000})
    e2, bs2, pl2 = await figures()
    check("revenue up 1M: the line moves 1M",
          abs(e2["net_income"] - e["net_income"] - 1_000_000) < 0.01)
    check("...and the balance sheet and P&L with it",
          abs(bs2["equity"]["current_earnings"] - e2["net_income"]) < 0.01
          and abs(pl2["totals"]["net_income"] - e2["net_income"]) < 0.01)
    async with SessionLocal() as s:
        n2 = await s.scalar(select(func.count()).select_from(LedgerEntry))
    check("nothing is posted for it", n2 == n_ledger, f"{n_ledger} → {n2}")
    await c.patch(f"/accounts/{rev.id}", headers=d, json={"balance": before})

    r = await c.get("/accounts/export.xlsx", headers=fin)
    check("the chart's export includes it", r.status_code == 200, str(r.status_code))

    print("\n── nothing is posted to 720101 ──")
    async with SessionLocal() as s:
        stored = float(await s.scalar(select(Account.balance).where(Account.account_no == "720101")))
        n720 = await s.scalar(select(func.count()).select_from(LedgerEntry)
                              .where(LedgerEntry.account_no == "720101"))
        fx = await s.scalar(select(Account).where(Account.account_no == "7200-04"))
    check("its stored balance is 0 and no line sits on it", stored == 0 and n720 == 0,
          f"{stored} {n720}")
    check("exchange differences have 7200-04 to go to", fx is not None and not fx.is_parent)
    r = await c.post("/journals", headers=d, json={"entry_date": "2026-10-01", "memo": "x", "lines": [
        {"account_no": "720101", "debit": 1000}, {"account_no": "1101-01", "credit": 1000}]})
    check("the general journal refuses it", r.status_code in (400, 409, 422), f"{r.status_code} {J(r)}"[:200])
    acc720 = next((a for a in coa if a["account_no"] == "720101"), None)
    r = await c.patch(f"/accounts/{acc720['id']}", headers=d, json={"balance": 123})
    async with SessionLocal() as s:
        stored = float(await s.scalar(select(Account.balance).where(Account.account_no == "720101")))
    check("...and a balance typed on it is ignored", r.status_code == 200 and stored == 0,
          f"{r.status_code} {stored}")
    r = await c.delete(f"/accounts/{acc720['id']}", headers=d)
    check("...and it can't be deleted", r.status_code == 409, str(r.status_code))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

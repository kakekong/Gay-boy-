"""A voided (batal) cash entry is gone — from every list, ledger and report.

BKK-2026-0001 (FedEx, 1.250.000 out of BCA) was voided, yet it stayed on the
Cash & bank list marked "batal", and its journal and the reversal that undid
it showed on the accounts, the general journal and in the money-in/out
totals (once out, once back in). Batal means it never happened:

* the reversal still puts every balance back;
* the pair is marked void and left out of the cash list, the general
  journal, every account ledger and the journal-based reports;
* its lines leave the reporting journal, so the P&L, cash and transactions
  reports read exactly as they did before it was entered;
* both entries stay on file, and "Show voided" brings them back.
"""
import asyncio, os, sys, uuid, json
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

BCA, EKSPEDISI = "1101-01", "6000-18"


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    from app.core.db import SessionLocal
    from app.models.account import Account
    from app.models.finance import LedgerEntry
    from app.models.journal import JournalEntry
    from sqlalchemy import func, select
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    fin = await login("finance@demo.local")
    today = date.today()
    period = today.strftime("%Y-%m")

    async def bal(no):
        async with SessionLocal() as s:
            return float(await s.scalar(select(Account.balance).where(Account.account_no == no)) or 0)

    async def reports():
        cash = J(await c.get("/finance/reports/cash", headers=fin, params={"period": period}))
        cash.pop("may_adjust", None)
        pnl = J(await c.get("/finance/reports/pnl-columns", headers=fin,
                            params={"basis": "monthly", "year": today.year, "month": today.month,
                                    "months": 1}))
        tx = J(await c.get("/finance/reports/transactions", headers=fin,
                           params={"period": period, "account_no": BCA}))
        return json.dumps(cash, sort_keys=True, default=str), json.dumps(pnl, sort_keys=True, default=str), \
            len(tx.get("items", tx.get("rows", [])))

    before = await reports()
    b_bca, b_exp = await bal(BCA), await bal(EKSPEDISI)

    print("\n── recorded ──")
    r = await c.post("/cash", headers=fin, json={
        "kind": "payment", "bank_account_no": BCA, "counterparty": f"FEDEX {TAG}",
        "method": "Transfer", "memo": f"Ongkir FedEx {TAG}", "tx_date": today.isoformat(),
        "lines": [{"account_no": EKSPEDISI, "amount": 1_250_000, "memo": "FedEx"}]})
    tx = J(r)
    check("a FedEx bill is paid out of BCA", r.status_code == 201, f"{r.status_code} {tx}"[:200])
    during = await reports()
    check("...it shows in the reports while it stands", during != before)

    print("\n── batal ──")
    r = await c.post(f"/cash/{tx['id']}/void", headers=fin, params={"reason": f"salah input {TAG}"})
    check("finance voids it", r.status_code == 200 and J(r).get("is_void") is True,
          f"{r.status_code} {J(r)}"[:200])
    check("the balances are back", await bal(BCA) == b_bca and await bal(EKSPEDISI) == b_exp,
          f"{await bal(BCA) - b_bca} {await bal(EKSPEDISI) - b_exp}")

    rows = J(await c.get("/cash", headers=fin, params={"kind": "payment", "limit": 500}))["items"]
    check("it's gone from the Cash & bank list", not [x for x in rows if x["id"] == tx["id"]])
    rows = J(await c.get("/cash", headers=fin, params={"kind": "payment", "limit": 500,
                                                      "show_void": True}))["items"]
    check("...and back with Show voided, marked batal",
          [x["is_void"] for x in rows if x["id"] == tx["id"]] == [True])

    async with SessionLocal() as s:
        entry = await s.get(JournalEntry, uuid.UUID(tx["journal_id"]))
        mirror = await s.get(JournalEntry, entry.reversed_by_id)
        ids = [entry.id, mirror.id]
        lines = await s.scalar(select(func.count()).select_from(LedgerEntry)
                               .where(LedgerEntry.source_id.in_(ids)))
    check("the entry and its reversal are both kept, marked void",
          entry.is_void and mirror.is_void, f"{entry.is_void} {mirror.is_void}")
    check("...the reversal is dated with the original", mirror.entry_date == entry.entry_date,
          f"{mirror.entry_date} vs {entry.entry_date}")
    check("...and neither has lines left in the reporting journal", lines == 0, str(lines))

    js = J(await c.get("/journals", headers=fin, params={"q": entry.number, "limit": 50}))["items"]
    check("the general journal no longer lists it", not js, str([x["number"] for x in js]))
    js = J(await c.get("/journals", headers=fin, params={"limit": 500, "show_void": True}))["items"]
    check("...Show voided lists the pair",
          {str(i) for i in ids} <= {x["id"] for x in js}, str(len(js)))

    for no in (BCA, EKSPEDISI):
        L = J(await c.get(f"/journals/account/{no}", headers=fin))
        hit = [i for i in L["items"] if i.get("number") in (entry.number, mirror.number)
               or (i.get("source_ref") or "") in (tx["number"], entry.number)]
        check(f"{no}'s ledger doesn't show it", not hit, str(hit)[:200])
        check(f"...and still closes at its balance",
              abs(L["closing_balance"] - L["account"]["balance"]) < 0.01,
              f'{L["closing_balance"]} vs {L["account"]["balance"]}')

    after = await reports()
    check("the cash report reads as before it was entered", after[0] == before[0])
    check("...so does the month's P&L", after[1] == before[1])
    check("...and BCA's transactions", after[2] == before[2], f"{after[2]} vs {before[2]}")

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

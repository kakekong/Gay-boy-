"""The director deletes a posted journal — a reversed one goes with its reversal.

Asked for: a cash correction, reversed, still showed in the bank's ledger —
the correction on one date, the reversal on another, the balance short by
the whole amount in between. Deleting takes both off as if never posted.

* A cash correction reversed, then deleted: both entries gone, the bank and
  its counter-account back where they were, nothing left in either ledger.
* A journal typed by hand, deleted on its own: the same.
* Finance can still only reverse; the director deletes.
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
    from app.models.account import Account
    from app.models.finance import LedgerEntry
    from app.services.account_history import account_events
    from app.services import financials as fin
    from sqlalchemy import select, func
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    fn = await login("finance@demo.local")

    async with SessionLocal() as s:
        bank = (await s.scalars(select(Account).where(Account.account_type.in_(fin.CASH_TYPES),
                                                      Account.is_parent.is_(False))
                                .order_by(Account.account_no))).first()
    BANK, EQ = bank.account_no, "300001"

    async def bal():
        async with SessionLocal() as s:
            rows = (await s.scalars(select(Account).where(Account.account_no.in_([BANK, EQ])))).all()
            return {a.account_no: round(float(a.balance or 0), 2) for a in rows}
    async def in_ledgers(numbers):
        async with SessionLocal() as s:
            accs = (await s.scalars(select(Account).where(Account.account_no.in_([BANK, EQ])))).all()
            ev = await account_events(s, accs)
            hits = [e["number"] for es in ev.values() for e in es if e["number"] in numbers]
            left = await s.scalar(select(func.count()).select_from(LedgerEntry)
                                  .where(LedgerEntry.source_ref.in_(numbers)))
            return hits, left

    print("\n── a cash correction, reversed, then deleted ──")
    b0 = await bal()
    r = await c.post("/finance/reports/cash/adjust", headers=d, json={
        "account_no": BANK, "new_balance": b0[BANK] - 1_000_000,
        "as_of": (date.today() - timedelta(days=40)).isoformat()})
    adj = J(r)
    check("the correction posts", r.status_code == 201, f"{r.status_code} {adj}"[:160])
    r = await c.post(f"/journals/{adj['journal_id']}/reverse", headers=fn, params={"reason": f"wrong {TAG}"})
    rev = J(r).get("reversal", {})
    check("finance reverses it", r.status_code == 200 and rev.get("number"), f"{r.status_code} {J(r)}"[:160])
    hits, _ = await in_ledgers([adj["journal_number"], rev["number"]])
    check("...and both sit in the bank's ledger, on two dates", len([h for h in hits]) >= 2, str(hits))

    r = await c.delete(f"/journals/{adj['journal_id']}", headers=fn)
    check("finance can't delete a posted entry", r.status_code == 403, str(r.status_code))
    r = await c.delete(f"/journals/{adj['journal_id']}", headers=d)
    check("the director deletes it", r.status_code == 204, f"{r.status_code} {J(r)}"[:160])
    r1 = await c.get(f"/journals/{adj['journal_id']}", headers=d)
    r2 = await c.get(f"/journals/{rev['id']}", headers=d)
    check("...the correction and its reversal are both gone", r1.status_code == 404 and r2.status_code == 404,
          f"{r1.status_code} {r2.status_code}")
    check("...the bank and its counter-account are back where they were", await bal() == b0,
          f"{await bal()} vs {b0}")
    hits, left = await in_ledgers([adj["journal_number"], rev["number"]])
    check("...and neither shows in any ledger", hits == [] and left == 0, f"{hits} {left}")

    print("\n── a journal typed by hand ──")
    b1 = await bal()
    r = await c.post("/journals", headers=fn, json={"entry_date": date.today().isoformat(),
        "memo": f"Reclass {TAG}", "lines": [
            {"account_no": BANK, "debit": 250_000, "credit": 0},
            {"account_no": EQ, "debit": 0, "credit": 250_000}]})
    je = J(r)
    check("posted", r.status_code == 201 and (await bal())[BANK] == round(b1[BANK] + 250_000, 2),
          f"{r.status_code} {je}"[:160])
    r = await c.delete(f"/journals/{je['id']}", headers=d)
    hits, left = await in_ledgers([je["number"]])
    check("deleted by the director: balances back, ledgers clear",
          r.status_code == 204 and await bal() == b1 and hits == [] and left == 0,
          f"{r.status_code} {await bal()} {hits} {left}")

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

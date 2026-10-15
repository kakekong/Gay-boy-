"""Money out: "what it was for" is never one of our own banks.

Finance recorded a FedEx bill (BKK-2026-0001, 1.250.000) out of BCA "for"
BCA itself — the picker offered only the first forty accounts, all banks and
assets, so the expense account wasn't there to pick. The entry put BCA in and
out for the same figure and recorded nothing.

* A line on the same bank is refused, naming what to pick instead.
* A line on another of our banks is refused too: that is a transfer.
* An expense line goes through, and the bank drops by the amount.
* A wrong one already recorded is undone by voiding it — the journal is
  reversed and the bank is back where it was.
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

BCA, BNI, EKSPEDISI = "1101-01", "1101-02", "6000-18"


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
    fin = await login("finance@demo.local")

    async def bal(no):
        async with SessionLocal() as s:
            a = await s.scalar(select(Account).where(Account.account_no == no))
            return float(a.balance or 0)

    def payment(line_acc):
        return {"kind": "payment", "bank_account_no": BCA, "counterparty": f"FEDEX {TAG}",
                "method": "Transfer", "memo": "Ongkir FedEx",
                "lines": [{"account_no": line_acc, "amount": 1_250_000, "memo": "FedEx"}]}

    print("\n── what it was for ──")
    before = await bal(BCA)
    r = await c.post("/cash", headers=fin, json=payment(BCA))
    check("the bank it came out of can't also be what it was for",
          r.status_code == 400 and "Beban" in str(J(r)), f"{r.status_code} {J(r)}"[:220])
    r = await c.post("/cash", headers=fin, json=payment(BNI))
    check("another of our banks is a transfer, not a payment",
          r.status_code == 400 and "Transfer" in str(J(r)), f"{r.status_code} {J(r)}"[:220])
    check("...and neither moved the bank", await bal(BCA) == before, str(await bal(BCA) - before))

    r = await c.post("/cash", headers=fin, json=payment(EKSPEDISI))
    tx = J(r)
    check("an expense account goes through", r.status_code == 201 and tx.get("number", "").startswith("BKK"),
          f"{r.status_code} {tx}"[:200])
    check("...and BCA drops by 1.250.000", round(await bal(BCA) - before, 2) == -1_250_000,
          str(await bal(BCA) - before))

    print("\n── undoing one ──")
    r = await c.post(f"/cash/{tx['id']}/void", headers=fin, params={"reason": f"wrong entry {TAG}"})
    check("voiding it is allowed", r.status_code == 200 and J(r).get("is_void") is True,
          f"{r.status_code} {J(r)}"[:200])
    check("...and BCA is back where it was", round(await bal(BCA) - before, 2) == 0,
          str(await bal(BCA) - before))

    print("\n── a transfer still works ──")
    r = await c.post("/cash", headers=fin, json={"kind": "transfer", "bank_account_no": BCA,
                                                 "to_account_no": BNI, "amount": 10_000})
    check("BCA to BNI on the Transfer tab", r.status_code == 201, f"{r.status_code} {J(r)}"[:200])
    await c.post(f"/cash/{J(r)['id']}/void", headers=fin, params={"reason": "test"})

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

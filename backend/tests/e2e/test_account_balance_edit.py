"""The director sets any account's balance, and removes what has no record.

Piutang showed a 12.5B "No record" line — a figure brought in with the chart,
explained by nothing — and Equitas Saldo Awal couldn't be erased or changed.

* The director removes the "No record" amount: the balance drops by exactly
  that, the row leaves the ledger, the audit keeps who and when.
* Nothing left to remove is a 400; anyone but the director is refused.
* The director changes a balance on the chart: it shows on the ledger as
  set by hand, with their name. Finance and admin can't change a balance —
  admin can still edit the rest of the account.
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
    from app.models.audit import AuditLog
    from sqlalchemy import select, update
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d, fin, adm = [await login(f"{x}@demo.local") for x in ("director", "finance", "admin")]

    async def ledger(no):
        return J(await c.get(f"/journals/account/{no}", headers=fin))

    def unrecorded(L):
        return [i for i in L["items"] if i["kind"] == "unrecorded"]

    # An account carrying a figure nothing explains (as the chart brought in).
    no = f"1199{TAG}"
    acc = J(await c.post("/accounts", headers=d, json={
        "account_no": no, "name": f"Piutang Uji {TAG}", "account_type": "Receivable",
        "balance": 0}))
    async with SessionLocal() as s:
        await s.execute(update(Account).where(Account.account_no == no).values(balance=12_500_000))
        await s.commit()

    print("\n── removing the No record amount ──")
    L = await ledger(no)
    check("the ledger shows the unexplained 12.5M as No record",
          len(unrecorded(L)) == 1 and abs(unrecorded(L)[0]["delta"] - 12_500_000) < 0.01,
          str(unrecorded(L))[:200])
    r = await c.post(f"/accounts/{no}/clear-unrecorded", headers=fin)
    check("finance can't remove it", r.status_code == 403, str(r.status_code))
    r = await c.post(f"/accounts/{no}/clear-unrecorded", headers=d)
    check("the director removes it", r.status_code == 200 and abs(J(r).get("removed", 0) - 12_500_000) < 0.01,
          f"{r.status_code} {J(r)}"[:200])
    L = await ledger(no)
    check("...the balance drops by exactly that", abs(L["account"]["balance"]) < 0.01,
          str(L["account"]["balance"]))
    check("...and the No record row is gone", not unrecorded(L), str(unrecorded(L))[:200])
    check("...the ledger still closes on the balance",
          abs(L["closing_balance"] - L["account"]["balance"]) < 0.01)
    async with SessionLocal() as s:
        log = await s.scalar(select(AuditLog).where(
            AuditLog.entity == "account", AuditLog.entity_id == uuid.UUID(acc["id"]),
            AuditLog.action == "clear_unrecorded"))
    check("the audit keeps what was removed",
          log is not None and abs(float(log.after["removed"]) - 12_500_000) < 0.01)
    r = await c.post(f"/accounts/{no}/clear-unrecorded", headers=d)
    check("nothing left to remove is refused", r.status_code == 400, str(r.status_code))

    print("\n── changing a balance by hand ──")
    r = await c.patch(f"/accounts/{acc['id']}", headers=fin, json={"balance": 5_000_000})
    check("finance can't change a balance", r.status_code == 403, str(r.status_code))
    r = await c.patch(f"/accounts/{acc['id']}", headers=adm, json={"balance": 5_000_000})
    check("admin can't either", r.status_code == 403, str(r.status_code))
    r = await c.patch(f"/accounts/{acc['id']}", headers=adm,
                      json={"description": f"catatan {TAG}", "balance": 0})
    check("...but admin can still edit the rest (same balance sent back)",
          r.status_code == 200, f"{r.status_code} {J(r)}"[:200])
    r = await c.patch(f"/accounts/{acc['id']}", headers=d, json={"balance": 5_000_000})
    check("the director changes it", r.status_code == 200 and abs(float(J(r)["balance"]) - 5_000_000) < 0.01,
          f"{r.status_code}")
    L = await ledger(no)
    hand = [i for i in L["items"] if i["kind"] == "by_hand"]
    check("it shows on the ledger as set by hand, with the director's name",
          hand and abs(hand[-1]["delta"] - 5_000_000) < 0.01 and hand[-1]["by"],
          str(hand)[:200])
    check("...and nothing reads as No record", not unrecorded(L))

    # Erasing Equitas Saldo Awal — any account the director picks.
    async with SessionLocal() as s:
        eq = await s.scalar(select(Account).where(Account.name.ilike("%saldo awal%"),
                                                  Account.is_parent.is_(False)))
    if eq:
        before = float(eq.balance or 0)
        r = await c.patch(f"/accounts/{eq.id}", headers=d, json={"balance": 0})
        L = await ledger(eq.account_no)
        check("the director erases Equitas Saldo Awal",
              r.status_code == 200 and abs(L["account"]["balance"]) < 0.01
              and abs(L["closing_balance"]) < 0.01, f"{r.status_code} {L['account']['balance']}")
        await c.patch(f"/accounts/{eq.id}", headers=d, json={"balance": before})

    # Leave the books as found: the test account back to nothing.
    await c.patch(f"/accounts/{acc['id']}", headers=d, json={"balance": 0})

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

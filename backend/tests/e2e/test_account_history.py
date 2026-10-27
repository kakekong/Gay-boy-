"""Every account's ledger explains its whole balance.

Utang Usaha IDR held 1.805.495.980 and its ledger said "Nothing has ever been
posted to this account": the page read only the general journal, while goods
receipts, supplier and customer payments, a quotation won, payroll and a PO's
cost are posted by the app straight to the books. Balances typed in on the
chart of accounts weren't shown either.

The ledger now reads all of it — journal entries, the app's own postings
(linked to the PO or invoice behind them), balances set by hand (with who and
when) — and whatever is still unexplained is one row saying there is no
record of it. So the closing figure is always the account's balance.
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
    from sqlalchemy import select, update
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    fin = await login("finance@demo.local")
    pur = await login("purchasing@demo.local")

    async def ledger(no, **params):
        return J(await c.get(f"/journals/account/{no}", headers=fin, params=params))

    def closes(L):
        return abs(L["closing_balance"] - L["account"]["balance"]) < 0.01

    print("\n── Belum Ditagih: goods receipts show ──")
    sup = J(await c.post("/purchasing/suppliers", headers=pur, json={"name": f"PT Riwayat {TAG}"}))["id"]
    po = J(await c.post("/purchasing/po", headers=d, json={
        "supplier_id": sup, "po_date": "2026-10-18",
        "items": [{"description": f"ROLLER {TAG}", "qty": 3, "uom": "pcs",
                   "unit_price": 150_000, "amount": 450_000}], "total": 450_000}))
    await c.post(f"/purchasing/po/{po['id']}/gr", headers=pur, json={
        "items": [{"description": f"ROLLER {TAG}", "qty": 3}]})
    # Received and not yet invoiced: Hutang Pembelian Belum Ditagih, until
    # the supplier's invoice moves it to Utang Usaha.
    L = await ledger("2102-03")
    mine = [i for i in L["items"] if i.get("source_ref") == po["number"]]
    check("the goods receipt is a line on Hutang Pembelian Belum Ditagih",
          len(mine) == 1 and mine[0]["kind"] == "auto" and mine[0]["credit"] == 450_000
          and mine[0]["label"] == "Goods received", str(mine)[:300])
    check("...linked to the PO it was received on",
          mine and mine[0]["link"] == f"/purchase-orders/{po['id']}", str(mine and mine[0]["link"]))
    check("...and the ledger closes at the account's balance", closes(L),
          f'{L["closing_balance"]} vs {L["account"]["balance"]}')
    P = await ledger("210101", period="2026-10")
    walked = round(P["opening_balance"] + sum(
        (i["credit"] - i["debit"]) for i in P["items"]), 2)
    check("a month's view adds up: opening + the month = closing",
          abs(walked - P["closing_balance"]) < 0.01, f"{walked} vs {P['closing_balance']}")

    print("\n── a balance set by hand ──")
    no = f"1199{TAG}"
    r = await c.post("/accounts", headers=d, json={
        "account_no": no, "name": f"Piutang Lain {TAG}", "account_type": "Other Current Asset",
        "balance": 5_000_000})
    check("an account is made with a balance typed in", r.status_code == 201, f"{r.status_code} {J(r)}"[:200])
    await c.patch(f"/accounts/{J(r)['id']}", headers=d, json={"balance": 6_000_000})
    L = await ledger(no)
    hand = [i for i in L["items"] if i["kind"] == "by_hand"]
    check("both the typed-in balance and the edit are on its ledger",
          [i["debit"] for i in hand] == [5_000_000, 1_000_000], str(hand)[:300])
    check("...saying who did it", all(i["by"] == "Director Demo" for i in hand)
          or all(i["by"] for i in hand), str([i["by"] for i in hand]))
    check("...and it closes at 6.000.000", closes(L) and L["closing_balance"] == 6_000_000,
          str(L["closing_balance"]))

    print("\n── a balance nothing explains ──")
    no2 = f"1198{TAG}"
    r = await c.post("/accounts", headers=d, json={
        "account_no": no2, "name": f"Uang Muka {TAG}", "account_type": "Other Current Asset"})
    async with SessionLocal() as s:     # as if brought in with the chart
        await s.execute(update(Account).where(Account.account_no == no2).values(balance=2_500_000))
        await s.commit()
    L = await ledger(no2)
    rest = [i for i in L["items"] if i["kind"] == "unrecorded"]
    check("what no record explains is one row saying so",
          len(rest) == 1 and rest[0]["debit"] == 2_500_000 and "No record" in rest[0]["memo"],
          str(rest)[:300])
    check("...so the ledger still closes at the balance", closes(L))

    print("\n── journal entries aren't counted twice ──")
    r = await c.post("/journals", headers=fin, json={
        "entry_date": "2026-10-18", "memo": f"reclass {TAG}", "post": True,
        "lines": [{"account_no": no2, "debit": 100_000},
                  {"account_no": no, "credit": 100_000}]})
    check("a journal entry between the two", r.status_code == 201, f"{r.status_code} {J(r)}"[:200])
    L = await ledger(no2)
    j = [i for i in L["items"] if i["kind"] == "journal"]
    check("...shows once, as a journal line", len(j) == 1 and j[0]["debit"] == 100_000
          and not [i for i in L["items"] if i["kind"] == "auto"], str(L["items"])[:300])
    check("...and the account still closes at its balance", closes(L),
          f'{L["closing_balance"]} vs {L["account"]["balance"]}')

    # The balances set here are one-sided on purpose; zero them so the
    # shared test database's balance sheet still balances for other tests.
    async with SessionLocal() as s:
        await s.execute(update(Account).where(Account.account_no.in_([no, no2]))
                        .values(balance=0))
        await s.commit()

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

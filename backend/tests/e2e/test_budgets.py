"""Anggaran, Monitor Anggaran, Transfer Anggaran.

A budget is worth having only if it can be compared to something. So what
is checked here is the comparison, not the data entry:

- **The actual comes from the ledger, over the same span, on the same
  account.** The test posts a real entry through Kas & Bank and then asks
  the monitor what it sees — a monitor fed its own numbers proves nothing.
- **It is signed the way the account is read.** Spending on an expense
  account counts up; a credit back counts down. Taking the raw debit total
  instead makes every refund look like more spending, and it would still
  pass a test that only ever spends.
- **It says which budget it used.** A month measured against its own figure
  and a month measured against a twelfth of the annual one are different
  claims, and the answer has to distinguish them.
- **An unbudgeted cost is the finding, not a missing row.** The account
  with spending and no budget has to appear.
- **A transfer cannot move budget that is not there.** Otherwise it is an
  increase wearing a transfer's clothes, and the record is wrong about
  where it came from.
"""
import asyncio, os, sys, uuid
from datetime import date
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
def why(r):
    b = J(r)
    return str(b.get("detail")
               or (b.get("errors") or [{}])[0].get("message", "")).lower()


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)
    tag = uuid.uuid4().hex[:5]
    today = date.today()
    YEAR, MONTH = today.year, today.month

    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    fin = await login("finance@demo.local")
    mgr = await login("manager@demo.local")
    s1 = await login("sales1@demo.local")

    async def make_account(no, name, kind):
        r = await c.post("/accounts", headers=d, json={
            "account_no": no, "name": name, "account_type": kind})
        return r.status_code in (200, 201, 409), J(r)

    TRAVEL, TRAINING = f"6501{tag[:2]}", f"6502{tag[:2]}"
    UNPLANNED, BANKACC = f"6503{tag[:2]}", f"1103{tag[:2]}"
    made = [await make_account(TRAVEL, f"Beban Perjalanan {tag}", "Expense"),
            await make_account(TRAINING, f"Beban Pelatihan {tag}", "Expense"),
            await make_account(UNPLANNED, f"Beban Tak Terduga {tag}", "Expense"),
            await make_account(BANKACC, f"Bank Anggaran {tag}", "Cash & Bank")]
    check("the accounts to budget against exist", all(ok for ok, _ in made),
          str([b for ok, b in made if not ok])[:200])

    print("\n=== Setting a budget ===")
    r = await c.post("/budgets", headers=fin, json={
        "period_year": YEAR, "period_month": MONTH,
        "account_no": TRAVEL, "amount": 50_000_000})
    check("finance sets a monthly figure", r.status_code == 201,
          f"{r.status_code} {J(r)}")
    travel = J(r)
    check("...named, not just numbered", bool(travel.get("account_name")),
          str(travel))

    r = await c.post("/budgets", headers=fin, json={
        "period_year": YEAR, "period_month": MONTH,
        "account_no": TRAVEL, "amount": 60_000_000})
    check("setting it again revises it rather than adding a second",
          r.status_code == 201 and J(r)["amount"] == 60_000_000,
          f"{r.status_code} {J(r)}")
    rows = J(await c.get("/budgets", headers=fin,
                         params={"year": YEAR, "month": MONTH}))
    check("...so there is exactly one line for that account",
          len([x for x in rows if x["account_no"] == TRAVEL]) == 1,
          str(len(rows)))

    # A heading cannot be budgeted: it is the sum of what is under it.
    accs = J(await c.get("/accounts", headers=fin, params={"limit": 500}))
    accs = accs if isinstance(accs, list) else accs.get("items", [])
    heading = next((a for a in accs if a.get("is_parent")), None)
    if heading:
        r = await c.post("/budgets", headers=fin, json={
            "period_year": YEAR, "period_month": MONTH,
            "account_no": heading["account_no"], "amount": 1_000_000})
        check("a heading cannot be budgeted", r.status_code == 400,
              f"{r.status_code} {J(r)}")
        check("...because budgeting it and its children counts it twice",
              "twice" in why(r), str(J(r))[:180])

    r = await c.post("/budgets", headers=mgr, json={
        "period_year": YEAR, "period_month": MONTH,
        "account_no": TRAINING, "amount": 1})
    check("a manager reads the budget but does not set it",
          r.status_code in (401, 403), str(r.status_code))
    r = await c.get("/budgets", headers=s1)
    check("sales does not see it at all", r.status_code in (401, 403),
          str(r.status_code))

    print("\n=== The actual comes from the ledger ===")
    # Real money out through Kas & Bank, so the monitor is reading the same
    # entries the rest of the books do.
    r = await c.post("/cash", headers=fin, json={
        "kind": "payment", "bank_account_no": BANKACC,
        "tx_date": f"{YEAR}-{MONTH:02d}-05", "counterparty": "Garuda",
        "memo": "Tiket dinas",
        "lines": [{"account_no": TRAVEL, "amount": 22_000_000}]})
    check("a payment posts against the budgeted account", r.status_code == 201,
          f"{r.status_code} {J(r)}")
    r = await c.post("/cash", headers=fin, json={
        "kind": "payment", "bank_account_no": BANKACC,
        "tx_date": f"{YEAR}-{MONTH:02d}-08", "counterparty": "Vendor",
        "memo": "Biaya tak terduga",
        "lines": [{"account_no": UNPLANNED, "amount": 9_000_000}]})
    check("...and one against an account nobody budgeted", r.status_code == 201,
          f"{r.status_code} {J(r)}")

    m = J(await c.get("/budgets/monitor", headers=fin,
                      params={"year": YEAR, "month": MONTH}))
    by_acc = {i["account_no"]: i for i in m["items"]}
    check("the monitor sees the spending", TRAVEL in by_acc
          and by_acc[TRAVEL]["actual"] == 22_000_000,
          str(by_acc.get(TRAVEL)))
    check("...against the figure that was set",
          by_acc[TRAVEL]["budget"] == 60_000_000, str(by_acc.get(TRAVEL)))
    check("...and says which budget that was",
          by_acc[TRAVEL]["basis"] == "monthly", str(by_acc[TRAVEL].get("basis")))
    check("...with what is left",
          by_acc[TRAVEL]["variance"] == 38_000_000, str(by_acc.get(TRAVEL)))
    check("an unbudgeted cost is listed, not left out",
          UNPLANNED in by_acc and by_acc[UNPLANNED]["actual"] == 9_000_000,
          str(by_acc.get(UNPLANNED)))
    check("...and marked as having no budget at all",
          by_acc[UNPLANNED]["basis"] == "unbudgeted"
          and by_acc[UNPLANNED]["budget"] == 0, str(by_acc.get(UNPLANNED)))

    print("\n=== Money coming back counts down, not up ===")
    r = await c.post("/cash", headers=fin, json={
        "kind": "receipt", "bank_account_no": BANKACC,
        "tx_date": f"{YEAR}-{MONTH:02d}-12", "counterparty": "Garuda",
        "memo": "Refund tiket batal",
        "lines": [{"account_no": TRAVEL, "amount": 4_000_000}]})
    check("a refund posts back against the same account", r.status_code == 201,
          f"{r.status_code} {J(r)}")
    m = J(await c.get("/budgets/monitor", headers=fin,
                      params={"year": YEAR, "month": MONTH}))
    by_acc = {i["account_no"]: i for i in m["items"]}
    check("...and the monitor takes it off rather than adding it on",
          by_acc[TRAVEL]["actual"] == 18_000_000, str(by_acc.get(TRAVEL)))
    check("...so what is left goes up",
          by_acc[TRAVEL]["variance"] == 42_000_000, str(by_acc.get(TRAVEL)))

    print("\n=== Over budget is flagged ===")
    r = await c.post("/budgets", headers=fin, json={
        "period_year": YEAR, "period_month": MONTH,
        "account_no": UNPLANNED, "amount": 5_000_000})
    check("a small budget is set on the overspent account", r.status_code == 201,
          str(r.status_code))
    m = J(await c.get("/budgets/monitor", headers=fin,
                      params={"year": YEAR, "month": MONTH}))
    by_acc = {i["account_no"]: i for i in m["items"]}
    check("...and 9m against 5m is over", by_acc[UNPLANNED]["over"] is True,
          str(by_acc.get(UNPLANNED)))
    check("...by how much", by_acc[UNPLANNED]["variance"] == -4_000_000,
          str(by_acc.get(UNPLANNED)))
    check("...at 180% used", by_acc[UNPLANNED]["used_pct"] == 180.0,
          str(by_acc[UNPLANNED].get("used_pct")))
    check("under-budget accounts are not flagged",
          by_acc[TRAVEL]["over"] is False, str(by_acc.get(TRAVEL)))
    only = J(await c.get("/budgets/monitor", headers=fin,
                         params={"year": YEAR, "month": MONTH,
                                 "over_only": True}))
    check("...and the over-only view shows just those",
          all(i["over"] for i in only["items"]) and len(only["items"]) >= 1,
          str([i["account_no"] for i in only["items"]]))

    print("\n=== An annual figure, pro-rated ===")
    r = await c.post("/budgets", headers=fin, json={
        "period_year": YEAR, "account_no": TRAINING, "amount": 120_000_000})
    check("an annual figure with no month is accepted", r.status_code == 201
          and J(r)["period_month"] is None, f"{r.status_code} {J(r)}")
    m = J(await c.get("/budgets/monitor", headers=fin,
                      params={"year": YEAR, "month": MONTH}))
    by_acc = {i["account_no"]: i for i in m["items"]}
    check("a month with no figure of its own falls back to a twelfth",
          by_acc[TRAINING]["budget"] == 10_000_000, str(by_acc.get(TRAINING)))
    check("...and says so, rather than looking like a monthly figure",
          by_acc[TRAINING]["basis"] == "annual pro-rated",
          str(by_acc[TRAINING].get("basis")))
    y = J(await c.get("/budgets/monitor", headers=fin, params={"year": YEAR}))
    by_year = {i["account_no"]: i for i in y["items"]}
    check("the year reads the annual figure whole",
          by_year[TRAINING]["budget"] == 120_000_000, str(by_year.get(TRAINING)))
    check("...and sums the monthly ones for the accounts that have them",
          by_year[TRAVEL]["budget"] == 60_000_000, str(by_year.get(TRAVEL)))

    print("\n=== Transfer Anggaran ===")
    r = await c.post("/budgets/transfer", headers=fin, json={
        "period_year": YEAR, "period_month": MONTH,
        "from_account_no": TRAVEL, "to_account_no": TRAINING,
        "amount": 90_000_000})
    check("moving more than is budgeted is refused", r.status_code == 409,
          f"{r.status_code} {J(r)}")
    check("...and says what is actually there", "60,000,000" in why(r)
          or "60.000.000" in str(J(r)), str(J(r))[:220])
    r = await c.post("/budgets/transfer", headers=fin, json={
        "period_year": YEAR, "period_month": MONTH,
        "from_account_no": TRAVEL, "to_account_no": TRAVEL, "amount": 1})
    check("the same account on both sides is refused", r.status_code == 400,
          str(r.status_code))

    r = await c.post("/budgets/transfer", headers=fin, json={
        "period_year": YEAR, "period_month": MONTH,
        "from_account_no": TRAVEL, "to_account_no": TRAINING,
        "amount": 20_000_000, "memo": "Kurangi dinas, tambah pelatihan"})
    check("a real move goes through", r.status_code == 201,
          f"{r.status_code} {J(r)}")
    mv = J(r)
    check("...taking it off one side", mv["from"]["amount"] == 40_000_000,
          str(mv.get("from")))
    check("...and putting it on the other", mv["to"]["amount"] == 20_000_000,
          str(mv.get("to")))

    m = J(await c.get("/budgets/monitor", headers=fin,
                      params={"year": YEAR, "month": MONTH}))
    by_acc = {i["account_no"]: i for i in m["items"]}
    check("the monitor measures against the moved yardstick",
          by_acc[TRAVEL]["budget"] == 40_000_000, str(by_acc.get(TRAVEL)))
    check("...and the receiving account now has a monthly figure of its own",
          by_acc[TRAINING]["budget"] == 20_000_000
          and by_acc[TRAINING]["basis"] == "monthly", str(by_acc.get(TRAINING)))

    moves = J(await c.get("/budgets/transfers", headers=fin,
                          params={"year": YEAR}))
    mine = [x for x in moves if x["from_account_no"] == TRAVEL
            and x["amount"] == 20_000_000]
    check("the move is on the record as one act, not two edits",
          len(mine) == 1, str(len(mine)))
    check("...with both ends named and the reason kept",
          mine and mine[0]["to_account_no"] == TRAINING
          and "pelatihan" in (mine[0]["memo"] or "").lower(), str(mine[:1])[:220])

    r = await c.post("/budgets/transfer", headers=mgr, json={
        "period_year": YEAR, "period_month": MONTH,
        "from_account_no": TRAVEL, "to_account_no": TRAINING, "amount": 1})
    check("a manager does not move budget either", r.status_code in (401, 403),
          str(r.status_code))

    print("\n=== Taking a line out ===")
    r = await c.delete(f"/budgets/{travel['id']}", headers=fin)
    check("a budget line can be removed", r.status_code == 200,
          f"{r.status_code} {J(r)}")
    m = J(await c.get("/budgets/monitor", headers=fin,
                      params={"year": YEAR, "month": MONTH}))
    by_acc = {i["account_no"]: i for i in m["items"]}
    check("...and the spending against it is still shown, unbudgeted",
          by_acc[TRAVEL]["actual"] == 18_000_000
          and by_acc[TRAVEL]["basis"] == "unbudgeted", str(by_acc.get(TRAVEL)))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)


asyncio.run(main())

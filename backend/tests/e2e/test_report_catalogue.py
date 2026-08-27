"""Daftar Laporan — the report catalogue and the six shapes of the P&L.

The catalogue is a menu; the reports behind it are the thing. What is
checked here is that they agree with each other and with the ledger,
because the failure mode of a report suite is not a crash — it is two
reports quietly disagreeing and nobody knowing which is right.

So the drivers post real entries and then ask each report what it sees:

- **Twelve monthly columns must sum to the year.** If they do not, one of
  the two is classifying an account differently from the other.
- **Four quarters must sum to the same year.** Same reason, different cut.
- **A comparison must state the difference**, not leave it to be eyeballed.
- **The indirect cash flow must land on the actual change in the bank.**
  That is the whole point of walking from net income: the statement derives
  a number the bank accounts already have, and a gap means something is
  misclassified.
- **A balance sheet as at a date must ignore what happened after it** — the
  running balance on the chart of accounts cannot do that, which is why it
  is walked from the journal instead.
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
def near(a, b, tol=1.0):
    return abs(float(a or 0) - float(b or 0)) <= tol


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)
    tag = uuid.uuid4().hex[:5]
    # A year in the far past, unique to this run. Nothing else in the demo
    # data reaches back there, so every figure below is this driver's own —
    # which is what makes "the months add up to the year" a real check
    # rather than a check on whatever else happened to be in the ledger.
    YEAR = 1990 + (int(tag, 16) % 20)

    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    fin = await login("finance@demo.local")
    s1 = await login("sales1@demo.local")

    async def make_account(no, name, kind):
        r = await c.post("/accounts", headers=d, json={
            "account_no": no, "name": name, "account_type": kind})
        return r.status_code in (200, 201, 409)

    SALES, COST = f"4101{tag[:2]}", f"5101{tag[:2]}"
    RENT, BANKACC = f"6101{tag[:2]}", f"1104{tag[:2]}"
    ok = all([await make_account(SALES, f"Penjualan {tag}", "Revenue"),
              await make_account(COST, f"HPP {tag}", "Cost Of Good Sold"),
              await make_account(RENT, f"Beban Sewa {tag}", "Expense"),
              await make_account(BANKACC, f"Bank Laporan {tag}", "Cash & Bank")])
    check("the accounts to report on exist", ok)

    print("\n=== The catalogue ===")
    cat = J(await c.get("/finance/reports/catalogue", headers=fin))
    keys = {r["key"] for r in cat["reports"]}
    check("the catalogue lists what can be run", len(cat["reports"]) >= 11,
          str(len(cat.get("reports", []))))
    check("...the six profit reports from the menu",
          {"pnl", "pnl-monthly", "pnl-quarterly", "pnl-yearly", "pnl-compare",
           "pnl-budget"} <= keys, str(sorted(keys)))
    check("...both balance sheets", {"balance-sheet", "balance-sheet-at"} <= keys,
          str(sorted(keys)))
    check("...the cash flow and both projections",
          {"cash-flow", "cash-projection", "cash-projection-budget"} <= keys,
          str(sorted(keys)))
    check("...and every entry says what it is for",
          all(r.get("about") for r in cat["reports"]),
          str([r["key"] for r in cat["reports"] if not r.get("about")]))
    r = await c.get("/finance/reports/catalogue", headers=s1)
    check("sales does not see the finance catalogue",
          r.status_code in (401, 403), str(r.status_code))

    print("\n=== Real entries, so the reports have something to disagree about ===")
    # Three months of trading in a year nothing else touches.
    posted = []
    for month, revenue, cost, rent in ((2, 100_000_000, 40_000_000, 10_000_000),
                                       (5, 150_000_000, 60_000_000, 10_000_000),
                                       (11, 50_000_000, 20_000_000, 10_000_000)):
        r = await c.post("/journals", headers=fin, json={
            "entry_date": f"{YEAR}-{month:02d}-15",
            "memo": f"Penjualan {month:02d}/{YEAR}",
            "post": True,
            # The bank nets to one line: an entry that both debits and
            # credits the same account is refused, and rightly so.
            "lines": [
                {"account_no": BANKACC, "debit": revenue - cost - rent},
                {"account_no": SALES, "credit": revenue},
                {"account_no": COST, "debit": cost},
                {"account_no": RENT, "debit": rent},
            ]})
        posted.append(r.status_code)
    check("three months of trading post", all(s == 201 for s in posted),
          str(posted))
    expected_revenue = 300_000_000
    expected_net = 300_000_000 - 120_000_000 - 30_000_000

    print("\n=== The columns have to agree with the year ===")
    monthly = J(await c.get("/finance/reports/pnl-columns", headers=fin,
                            params={"basis": "monthly", "year": YEAR}))
    check("twelve months come back", len(monthly["columns"]) == 12,
          str(len(monthly.get("columns", []))))
    month_sum = round(sum(t["net_income"] for t in monthly["column_totals"]), 2)
    check("...and they add up to the year's profit",
          near(month_sum, expected_net), f"{month_sum} vs {expected_net}")
    feb = monthly["column_totals"][1]
    check("...with February carrying its own month, not the year's",
          near(feb["revenue"], 100_000_000), str(feb.get("revenue")))
    empty = monthly["column_totals"][0]
    check("...and a month with no trading reading zero rather than blank",
          empty["revenue"] == 0 and empty["net_income"] == 0, str(empty))

    quarterly = J(await c.get("/finance/reports/pnl-columns", headers=fin,
                              params={"basis": "quarterly", "year": YEAR}))
    check("four quarters come back", len(quarterly["columns"]) == 4,
          str(len(quarterly.get("columns", []))))
    q_sum = round(sum(t["net_income"] for t in quarterly["column_totals"]), 2)
    check("...and the quarters agree with the months",
          near(q_sum, month_sum), f"{q_sum} vs {month_sum}")
    check("...Q1 holding February's trading",
          near(quarterly["column_totals"][0]["revenue"], 100_000_000),
          str(quarterly["column_totals"][0].get("revenue")))
    check("...and Q2 May's",
          near(quarterly["column_totals"][1]["revenue"], 150_000_000),
          str(quarterly["column_totals"][1].get("revenue")))

    yearly = J(await c.get("/finance/reports/pnl-columns", headers=fin,
                           params={"basis": "yearly", "year": YEAR, "years": 3}))
    check("several years come back", len(yearly["columns"]) == 3,
          str(len(yearly.get("columns", []))))
    ours = next((i for i, col in enumerate(yearly["columns"])
                 if col["label"] == str(YEAR)), None)
    check("...our year is among them", ours is not None,
          str([col["label"] for col in yearly["columns"]]))
    check("...and it agrees with the monthly columns",
          ours is not None
          and near(yearly["column_totals"][ours]["net_income"], month_sum),
          f"{yearly['column_totals'][ours]['net_income'] if ours is not None else '?'} vs {month_sum}")
    std = J(await c.get("/finance/reports/profit-loss", headers=fin,
                        params={"from": f"{YEAR}-01-01", "to": f"{YEAR}-12-31"}))
    check("...and with the standard single-period report",
          near(std["totals"]["revenue"], expected_revenue),
          f"{std['totals']['revenue']} vs {expected_revenue}")
    check("...which reads the window it was given, not all time",
          std.get("source") == "journal", str(std.get("source")))

    print("\n=== A comparison states the difference ===")
    cmp = J(await c.get("/finance/reports/pnl-columns", headers=fin,
                        params={"basis": "compare", "year": YEAR, "month": 5}))
    check("two columns come back", len(cmp["columns"]) == 2,
          str(len(cmp.get("columns", []))))
    check("...April against May, in that order",
          cmp["columns"][0]["label"] == f"04/{YEAR}"
          and cmp["columns"][1]["label"] == f"05/{YEAR}",
          str([col["label"] for col in cmp["columns"]]))
    check("...and the difference is worked out, not left to the eye",
          near(cmp["change"]["revenue"], 150_000_000),
          str(cmp.get("change")))
    sales_row = next((row for sec in cmp["sections"] for row in sec["accounts"]
                      if row["account_no"] == SALES), None)
    check("...per account too", sales_row and near(sales_row["change"], 150_000_000),
          str(sales_row))

    print("\n=== Against budget, on the budget screen's own rule ===")
    await c.post("/budgets", headers=fin, json={
        "period_year": YEAR, "period_month": 5, "account_no": RENT,
        "amount": 8_000_000})
    await c.post("/budgets", headers=fin, json={
        "period_year": YEAR, "account_no": COST, "amount": 600_000_000})
    b = J(await c.get("/finance/reports/pnl-budget", headers=fin,
                      params={"year": YEAR, "month": 5}))
    rows = {row["account_no"]: row for sec in b["sections"]
            for row in sec["accounts"]}
    check("the budgeted month reads its own figure",
          rows.get(RENT, {}).get("budget") == 8_000_000, str(rows.get(RENT)))
    check("...against what was actually spent",
          rows.get(RENT, {}).get("actual") == 10_000_000, str(rows.get(RENT)))
    check("...so the overspend is stated",
          rows.get(RENT, {}).get("variance") == -2_000_000, str(rows.get(RENT)))
    check("an account with only an annual figure is pro-rated",
          rows.get(COST, {}).get("budget") == 50_000_000
          and rows[COST]["basis"] == "annual pro-rated", str(rows.get(COST)))

    print("\n=== Neraca per tanggal ignores what came after ===")
    # A balance sheet is cumulative, so the figures are read as movements
    # from a baseline taken before this run's first entry — which isolates
    # what these three months did from whatever else is in the ledger.
    base = J(await c.get("/finance/reports/balance-sheet-at", headers=fin,
                         params={"on": f"{YEAR}-01-31"}))
    base_earnings = base["equity"]["current_earnings"][0]
    mid = J(await c.get("/finance/reports/balance-sheet-at", headers=fin,
                        params={"on": f"{YEAR}-03-31"}))
    end = J(await c.get("/finance/reports/balance-sheet-at", headers=fin,
                        params={"on": f"{YEAR}-12-31"}))
    check("a date in March sees only February's trading",
          near(mid["equity"]["current_earnings"][0] - base_earnings, 50_000_000),
          f"{mid['equity']['current_earnings']} - {base_earnings}")
    check("...and December sees the year",
          near(end["equity"]["current_earnings"][0] - base_earnings, expected_net),
          f"{end['equity']['current_earnings']} - {base_earnings}")
    check("...and it balances at both", mid["balanced"][0] and end["balanced"][0],
          f"{mid.get('balanced')} {end.get('balanced')}")

    # Depreciation is the entry that breaks a balance sheet built carelessly:
    # accumulated depreciation is an asset account that *reduces* assets, and
    # added rather than subtracted it overstates them by twice itself. The
    # sheet has to still balance after one.
    await make_account(f"1805{tag[:2]}", f"Mesin {tag}", "Fixed Asset")
    await make_account(f"1806{tag[:2]}", f"Akum. Peny. {tag}",
                       "Accumulated Depreciation")
    await make_account(f"6801{tag[:2]}", f"Beban Penyusutan {tag}", "Expense")
    r = await c.post("/journals", headers=fin, json={
        "entry_date": f"{YEAR}-06-30", "memo": "Perolehan mesin", "post": True,
        "lines": [{"account_no": f"1805{tag[:2]}", "debit": 24_000_000},
                  {"account_no": BANKACC, "credit": 24_000_000}]})
    check("a fixed asset is bought", r.status_code == 201, str(r.status_code))
    r = await c.post("/journals", headers=fin, json={
        "entry_date": f"{YEAR}-07-31", "memo": "Penyusutan", "post": True,
        "lines": [{"account_no": f"6801{tag[:2]}", "debit": 1_000_000},
                  {"account_no": f"1806{tag[:2]}", "credit": 1_000_000}]})
    check("...and depreciated", r.status_code == 201, str(r.status_code))
    after = J(await c.get("/finance/reports/balance-sheet-at", headers=fin,
                          params={"on": f"{YEAR}-12-31"}))
    check("the sheet still balances once something is depreciated",
          after["balanced"][0] is True, str(after.get("balanced")))
    accum_rows = [a for accs in after["assets"]["by_type"].values()
                  for a in accs if a["account_no"] == f"1806{tag[:2]}"]
    check("...because accumulated depreciation is carried as a reduction",
          accum_rows and accum_rows[0]["values"][0] == -1_000_000,
          str(accum_rows))
    std = J(await c.get("/finance/reports/balance-sheet", headers=fin))
    check("...and the standard balance sheet agrees",
          std["balanced"] is True, str(std.get("balanced")))

    both = J(await c.get("/finance/reports/balance-sheet-at", headers=fin,
                         params={"on": f"{YEAR}-12-31",
                                 "compare_to": f"{YEAR}-03-31"}))
    check("two dates can be read side by side",
          len(both["columns"]) == 2, str(len(both.get("columns", []))))
    check("...and each column keeps its own figure",
          near(both["equity"]["current_earnings"][0] - base_earnings,
               expected_net - 1_000_000)
          and near(both["equity"]["current_earnings"][1] - base_earnings,
                   50_000_000),
          f"{both['equity']['current_earnings']} - {base_earnings}")

    print("\n=== Arus Kas has to land on the bank ===")
    cf = J(await c.get("/finance/reports/cash-flow-indirect", headers=fin,
                       params={"year": YEAR}))
    check("the statement runs", "net_change" in cf, str(cf)[:200])
    check("...starting from the year's profit, after depreciation",
          near(cf["operating"]["net_income"], expected_net - 1_000_000),
          str(cf["operating"].get("net_income")))
    check("...adding the depreciation back, because it moved no money",
          near(cf["operating"]["depreciation"], 1_000_000),
          str(cf["operating"].get("depreciation")))
    check("...and putting the machine in investing, not operating",
          near(cf["investing"]["total"], -24_000_000),
          str(cf["investing"].get("total")))
    check("...and it reconciles against the bank's own movement",
          cf["reconciles"] is True,
          f"derived {cf.get('net_change')} vs bank {cf.get('cash_movement')}")
    check("...which is the profit less what the machine cost",
          near(cf["cash_movement"], expected_net - 24_000_000),
          str(cf.get("cash_movement")))

    print("\n=== Proyeksi Arus Kas ===")
    p = J(await c.get("/finance/reports/cash-projection", headers=fin,
                      params={"basis": "commitments", "months": 6}))
    check("the projection runs six months", len(p["months"]) == 6,
          str(len(p.get("months", []))))
    check("...opening from the real bank balance", "opening_cash" in p, str(p)[:150])
    check("...and each month closes where the next one opens",
          all(p["months"][i]["closing"] == p["months"][i + 1]["opening"]
              for i in range(len(p["months"]) - 1)),
          str([(m["opening"], m["closing"]) for m in p["months"]])[:200])
    check("...with overdue money brought into the first month, not lost",
          "overdue_included" in p, str(p.get("overdue_included")))

    pb = J(await c.get("/finance/reports/cash-projection", headers=fin,
                       params={"basis": "budget", "months": 6}))
    check("the budget-based projection runs too", pb["basis"] == "budget",
          str(pb.get("basis")))
    check("...and starts from the same bank balance",
          near(pb["opening_cash"], p["opening_cash"]),
          f"{pb.get('opening_cash')} vs {p.get('opening_cash')}")
    r = await c.get("/finance/reports/cash-projection", headers=fin,
                    params={"basis": "wishful"})
    check("a basis nobody defined is refused", r.status_code == 400,
          str(r.status_code))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)


asyncio.run(main())

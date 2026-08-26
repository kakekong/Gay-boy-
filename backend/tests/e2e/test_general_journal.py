"""The books become double-entry: Jurnal Umum, and an account you can walk.

Finance asked for the accounting module the company's old software has —
Buku Besar, Neraca, Kas & Bank, Aset Tetap, the report catalogue. All of it
stands on one thing this app did not have: entries that name both sides.

The ledger here was single-entry by design — one signed line per account,
balance is the running sum — and that answers "how much cash" and "what did
we sell in March", which is what it was built for. It cannot answer the rest.
A balance sheet that balances, an account history you can hand an auditor, a
bank reconciliation, a depreciation run, a correction with a reason on it:
every one of them assumes each transaction says what was debited and what was
credited, adding to the same number.

So this is the foundation, and its rules are the whole of it:

**It balances or it does not exist.** Not saved as a draft to fix later —
refused. The moment one unbalanced entry exists the balance sheet stops
balancing and nobody can tell which entry did it.

**Posted is permanent.** Never edited, never deleted. A correction is the
reverse entry posted beside it, so both stay on the record and the account
history explains itself six months later.

Run this on a fresh database (`run_all.sh --fresh`) to exercise the whole of
it: opening balances are written down once per set of books, so the section
that proves an account ledger reconciles to its account only means anything
the first time.

**And the old reports keep working.** Every posted line still writes the
single-entry row the existing profit/cash/balance reports read, so the
double-entry record becomes the truth without rewriting all of them in the
same breath.
"""
import asyncio, os, sys, uuid
from datetime import date, timedelta
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
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)
    tag = uuid.uuid4().hex[:5]

    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    fin = await login("finance@demo.local")
    mgr = await login("manager@demo.local")
    s1 = await login("sales1@demo.local")
    adm = await login("admin@demo.local")
    pur = await login("purchasing@demo.local")

    # Two real accounts off the seeded chart: a bank (debit-normal) and an
    # expense (debit-normal), plus a liability to test the other side.
    accs = J(await c.get("/accounts", headers=fin, params={"limit": 500}))
    rows = accs if isinstance(accs, list) else accs.get("items", [])
    def pick(t):
        return next((a for a in rows
                     if a["account_type"] == t and not a.get("is_parent")
                     and not a.get("is_suspended")), None)
    bank, expense = pick("Cash & Bank"), pick("Expense")
    payable = pick("Payable") or pick("Other Current Liability")
    check("the chart of accounts has what a journal needs",
          all([bank, expense, payable]),
          f"{bank} / {expense} / {payable}")
    if not all([bank, expense, payable]):
        sys.exit(1)

    async def balance(no, hdr=None):
        # /accounts/{id} takes the row's UUID, not its number — the number is
        # what a person knows, so look it up by that.
        data = J(await c.get("/accounts", headers=hdr or fin,
                             params={"q": no, "limit": 500}))
        got = data if isinstance(data, list) else data.get("items", [])
        row = next((a for a in got if a["account_no"] == no), None)
        return float((row or {}).get("balance") or 0)

    bank_before = await balance(bank["account_no"])
    exp_before = await balance(expense["account_no"])
    today = date.today()

    # ══ where the balances that were already here came from ══════════════════
    # First, before anything is posted — which is what "opening" means, and
    # is now the rule: written afterwards they would state a second time what
    # the journal has already explained.
    print("\n── opening balances ──")
    r = await c.post("/journals/opening-balances", headers=fin,
                     params={"on": (today - timedelta(days=1)).isoformat()})
    # Three honest outcomes here, and which one you get depends on the state
    # of the books: written down (a chart carrying balances, the production
    # case), nothing to write down (a chart at zero), or refused because a
    # previous run already started the journal on this database.
    ob = J(r)
    # Whether the ledger can reconcile to its account later depends on this:
    # opening balances written (or nothing to write) means the journal
    # explains the whole balance; refused means it explains only the part
    # posted since, which is the honest state of a book already in progress.
    explained = r.status_code == 201
    check("the opening balances are dealt with, one way or another",
          r.status_code in (201, 409), f"{r.status_code} {str(ob)[:170]}")
    if r.status_code == 409:
        print("     (the journal already has entries — needs a fresh database)")
        check("...and the refusal names where the journal starts",
              "JU-" in str(ob), str(ob)[:200])
    elif ob.get("written"):
        check("...as one entry covering the chart",
              len(ob.get("lines") or []) >= 2, str(len(ob.get("lines") or [])))
        # It balances like any other entry. Whatever the accounts do not
        # balance among themselves is carried to opening equity — and when
        # they already do, no equity line is needed, which is the definition
        # working rather than a missing line.
        d_sum = sum(float(ln["debit"]) for ln in ob.get("lines", []))
        c_sum = sum(float(ln["credit"]) for ln in ob.get("lines", []))
        check("...balancing like any other entry", abs(d_sum - c_sum) < 0.01,
              f"{d_sum} vs {c_sum}")
        # Whatever the accounts do not balance among themselves is carried to
        # opening equity — and when they already do, there is no equity line,
        # which is the definition working rather than a line missing.
        eq = [ln for ln in ob["lines"] if ln["account_no"] == "300001"]
        rest = [ln for ln in ob["lines"] if ln["account_no"] != "300001"]
        gap = round(sum(float(x["debit"]) - float(x["credit"]) for x in rest), 2)
        check("...carrying any difference to opening equity, and nothing when "
              "there is none",
              (abs(gap) < 0.01 and not eq)
              or (len(eq) == 1
                  and abs((float(eq[0]["credit"]) - float(eq[0]["debit"])) - gap) < 0.01),
              f"gap {gap} / equity {eq}")
        check("...and changing no balance, because they were already right",
              abs(await balance(bank["account_no"]) - bank_before) < 0.01,
              f"{await balance(bank['account_no'])} vs {bank_before}")
    else:
        print("     (this chart of accounts is at zero — nothing to write down)")
        check("...saying so plainly rather than writing an empty entry",
              "zero" in str(ob).lower(), str(ob)[:170])
    again = await c.post("/journals/opening-balances", headers=fin)
    check("...and never written a second time", again.status_code == 409,
          f"{again.status_code} {str(J(again))[:150]}")

    # ══ an entry balances, or it is refused ══════════════════════════════════
    print("\n── what a journal entry has to be ──")
    async def post(lines, memo="", when=None, hdr=None):
        return await c.post("/journals", headers=hdr or fin, json={
            "entry_date": (when or today).isoformat(),
            "memo": memo or f"test {tag}", "post": True, "lines": lines})

    r = await post([{"account_no": expense["account_no"], "debit": 500000},
                    {"account_no": bank["account_no"], "credit": 400000}])
    check("an entry that doesn't balance is refused", r.status_code == 400,
          f"{r.status_code} {str(J(r))[:130]}")
    check("...and says by how much, so it can be found",
          "100" in str(J(r)) and "match" in str(J(r)).lower(), str(J(r))[:200])

    r = await post([{"account_no": expense["account_no"], "debit": 500000}])
    check("one line is only half an entry", r.status_code == 400,
          f"{r.status_code} {str(J(r))[:130]}")
    r = await post([{"account_no": expense["account_no"], "debit": 100, "credit": 100},
                    {"account_no": bank["account_no"], "credit": 100, "debit": 100}])
    check("a line that is both a debit and a credit is refused",
          r.status_code == 400, f"{r.status_code} {str(J(r))[:130]}")
    r = await post([{"account_no": f"NOPE-{tag}", "debit": 100},
                    {"account_no": bank["account_no"], "credit": 100}])
    check("an account that doesn't exist is refused", r.status_code == 400,
          f"{r.status_code} {str(J(r))[:130]}")
    parent = next((a for a in rows if a.get("is_parent")), None)
    if parent:
        r = await post([{"account_no": parent["account_no"], "debit": 100},
                        {"account_no": bank["account_no"], "credit": 100}])
        check("...and so is posting to a heading, which is a sum of its children",
              r.status_code == 400, f"{r.status_code} {str(J(r))[:130]}")
    r = await post([{"account_no": expense["account_no"], "debit": -100},
                    {"account_no": bank["account_no"], "credit": -100}])
    check("a negative amount is the other column, not a minus sign",
          r.status_code == 400, f"{r.status_code} {str(J(r))[:130]}")

    # ══ a good one moves both accounts ═══════════════════════════════════════
    print("\n── posting one ──")
    amount = 750000.0
    r = await post([{"account_no": expense["account_no"], "debit": amount,
                     "memo": f"office rent {tag}"},
                    {"account_no": bank["account_no"], "credit": amount}],
                   memo=f"Rent {tag}")
    check("a balanced entry posts", r.status_code == 201,
          f"{r.status_code} {str(J(r))[:170]}")
    entry = J(r)
    check("...numbered as a journal entry", entry["number"].startswith("JU-"),
          str(entry.get("number")))
    check("...carrying both sides", len(entry["lines"]) == 2, str(entry)[:200])
    check("...and posted, not left as a draft", entry["is_posted"] is True,
          str(entry.get("is_posted")))

    check("the expense went up by what was debited",
          abs(await balance(expense["account_no"]) - (exp_before + amount)) < 0.01,
          f"{await balance(expense['account_no'])} vs {exp_before + amount}")
    check("...and the bank down by what was credited",
          abs(await balance(bank["account_no"]) - (bank_before - amount)) < 0.01,
          f"{await balance(bank['account_no'])} vs {bank_before - amount}")

    # A credit-normal account moves the other way for the same column.
    pay_before = await balance(payable["account_no"])
    r = await post([{"account_no": expense["account_no"], "debit": 250000},
                    {"account_no": payable["account_no"], "credit": 250000}],
                   memo=f"Accrual {tag}")
    check("crediting a liability increases it — the other normal side",
          r.status_code == 201
          and abs(await balance(payable["account_no"]) - (pay_before + 250000)) < 0.01,
          f"{await balance(payable['account_no'])} vs {pay_before + 250000}")

    # ══ the account, walked ══════════════════════════════════════════════════
    print("\n── the account ledger ──")
    period = today.strftime("%Y-%m")
    led = J(await c.get(f"/journals/account/{bank['account_no']}",
                        headers=fin, params={"period": period}))
    check("an account's ledger opens", led.get("account", {}).get("account_no")
          == bank["account_no"], str(led)[:170])
    check("...with an opening balance, which is what explains the closing one",
          "opening_balance" in led, str(sorted(led))[:200])
    mine = [x for x in led["items"] if tag in (x.get("memo") or "")]
    check("...and the entry just posted on it", len(mine) >= 1,
          str(led["items"])[:200])
    check("...on the correct side", mine and float(mine[0]["credit"]) == amount,
          str(mine[0] if mine else None)[:200])
    check("...with a running balance, not just a list of movements",
          all("balance" in x for x in led["items"]), str(led["items"][:1]))
    # With the opening balances written down first, the ledger explains the
    # whole of the account rather than the part posted since — which is the
    # first thing anybody checks. On a book that was already in progress
    # when this ran, the gap is real and the page says so instead.
    if explained:
        check("...that reconciles to the account it describes",
              abs(led["closing_balance"] - await balance(bank["account_no"])) < 0.01,
              f"{led['closing_balance']} vs {await balance(bank['account_no'])}")
    else:
        check("...that explains what has been posted since the journal started",
              led["closing_balance"] != 0 or not led["items"],
              f"{led['closing_balance']} over {len(led['items'])} line(s)")
    check("...and adds the two columns up",
          led["total_credit"] >= amount, str(led["total_credit"]))

    old = J(await c.get(f"/journals/account/{bank['account_no']}", headers=fin,
                        params={"period": (today - timedelta(days=400)).strftime("%Y-%m")}))
    check("a month with nothing in it says so rather than looking broken",
          old["items"] == [], str(old["items"])[:150])

    print("\n── and once the journal has started ──")
    r = await c.post("/journals/opening-balances", headers=fin)
    check("opening balances are refused once entries exist",
          r.status_code == 409, f"{r.status_code} {str(J(r))[:150]}")
    # Either reason is a correct refusal, and which one you get depends on
    # whether they were written down a moment ago or the journal simply
    # started without them.
    why = str(J(r)).lower()
    check("...saying why, either way",
          "starting point" in why or "already recorded" in why, str(J(r))[:220])

    # ══ posted is permanent ══════════════════════════════════════════════════
    print("\n── correcting one ──")
    r = await c.patch(f"/journals/{entry['id']}", headers=fin,
                      json={"memo": "changed my mind"})
    check("a posted entry cannot be edited", r.status_code == 409,
          f"{r.status_code} {str(J(r))[:130]}")
    check("...and says to reverse it instead", "revers" in str(J(r)).lower(),
          str(J(r))[:170])
    r = await c.delete(f"/journals/{entry['id']}", headers=fin)
    check("...nor deleted", r.status_code == 409,
          f"{r.status_code} {str(J(r))[:130]}")

    exp_now = await balance(expense["account_no"])
    r = await c.post(f"/journals/{entry['id']}/reverse", headers=fin,
                     params={"reason": f"wrong account {tag}"})
    check("it can be reversed", r.status_code == 200,
          f"{r.status_code} {str(J(r))[:150]}")
    mirror = J(r)["reversal"]
    check("...which posts a new entry, not a deletion",
          mirror["number"].startswith("JU-") and mirror["number"] != entry["number"],
          str(mirror.get("number")))
    check("...carrying the reason", tag in (mirror.get("memo") or ""),
          str(mirror.get("memo")))
    check("...and undoing the balance exactly",
          abs(await balance(expense["account_no"]) - (exp_now - amount)) < 0.01,
          f"{await balance(expense['account_no'])} vs {exp_now - amount}")
    again = await c.post(f"/journals/{entry['id']}/reverse", headers=fin)
    check("...once only", again.status_code == 409,
          f"{again.status_code} {str(J(again))[:130]}")
    back = J(await c.get(f"/journals/{entry['id']}", headers=fin))
    check("the original still stands on the record, marked",
          back["is_posted"] is True and back.get("reversed_by_id"),
          str(back)[:200])

    # ══ a draft touches nothing ══════════════════════════════════════════════
    print("\n── drafts ──")
    r = await c.post("/journals", headers=fin, json={
        "entry_date": today.isoformat(), "memo": f"draft {tag}", "post": False,
        "lines": [{"account_no": expense["account_no"], "debit": 111000},
                  {"account_no": bank["account_no"], "credit": 111000}]})
    draft = J(r)
    exp_at_draft = await balance(expense["account_no"])
    check("a draft is written but not posted",
          r.status_code == 201 and draft["is_posted"] is False, str(draft)[:150])
    check("...and moves no balance",
          abs(exp_at_draft - (exp_now - amount)) < 0.01, str(exp_at_draft))
    r = await c.patch(f"/journals/{draft['id']}", headers=fin,
                      json={"memo": f"draft {tag} fixed"})
    check("...a draft can be corrected", r.status_code == 200,
          f"{r.status_code} {str(J(r))[:130]}")
    r = await c.post(f"/journals/{draft['id']}/post", headers=fin)
    check("...and posted when it is right", r.status_code == 200,
          f"{r.status_code} {str(J(r))[:130]}")
    check("...which is when the balance moves",
          abs(await balance(expense["account_no"]) - (exp_at_draft + 111000)) < 0.01,
          str(await balance(expense["account_no"])))

    r = await c.post("/journals", headers=fin, json={
        "entry_date": today.isoformat(), "memo": f"scrap {tag}", "post": False,
        "lines": [{"account_no": expense["account_no"], "debit": 1000},
                  {"account_no": bank["account_no"], "credit": 1000}]})
    scrap = J(r)["id"]
    r = await c.delete(f"/journals/{scrap}", headers=fin)
    check("an unposted draft can be thrown away", r.status_code == 204,
          str(r.status_code))

    # ══ the existing reports keep working ════════════════════════════════════
    print("\n── the reports built on the old journal ──")
    tx = J(await c.get("/finance/reports/transactions", headers=fin,
                       params={"period": period, "limit": 200}))
    recent = tx.get("entries", [])
    check("a posted journal also writes the single-entry rows the reports read",
          any(tag in str(x.get("memo") or "") for x in recent),
          str(recent[:2])[:250])
    check("...on both sides of it, not just one",
          len([x for x in recent if tag in str(x.get("memo") or "")]) >= 2,
          str(len(recent)))
    check("...and a bank credit reads as money going out",
          any(tag in str(x.get("memo") or "") and float(x.get("cash_delta") or 0) < 0
              for x in recent),
          str([x.get("cash_delta") for x in recent][:6]))
    r = await c.get("/finance/reports/profit-loss", headers=fin,
                    params={"period": period})
    check("the profit & loss report still answers", r.status_code == 200,
          f"{r.status_code} {str(J(r))[:130]}")
    r = await c.get("/finance/reports/balance-sheet", headers=fin)
    check("...and the balance sheet", r.status_code == 200,
          f"{r.status_code} {str(J(r))[:130]}")

    # ══ who keeps the books ══════════════════════════════════════════════════
    print("\n── who may write, and who may only read ──")
    r = await c.post("/journals", headers=d, json={
        "entry_date": today.isoformat(), "memo": f"director {tag}", "post": True,
        "lines": [{"account_no": expense["account_no"], "debit": 5000},
                  {"account_no": bank["account_no"], "credit": 5000}]})
    check("the director can post — they sign off on the numbers",
          r.status_code == 201, f"{r.status_code} {str(J(r))[:130]}")
    r = await c.get("/journals", headers=mgr)
    check("a manager can read the journal", r.status_code == 200, str(r.status_code))
    r = await c.post("/journals", headers=mgr, json={
        "entry_date": today.isoformat(), "post": True,
        "lines": [{"account_no": expense["account_no"], "debit": 100},
                  {"account_no": bank["account_no"], "credit": 100}]})
    check("...but not write one — oversight is not bookkeeping",
          r.status_code in (401, 403), str(r.status_code))
    for label, hdr in (("sales", s1), ("admin", adm), ("purchasing", pur)):
        r = await c.get("/journals", headers=hdr)
        check(f"{label} cannot open the journal at all",
              r.status_code in (401, 403), str(r.status_code))
        r = await c.get(f"/journals/account/{bank['account_no']}", headers=hdr)
        check(f"...nor an account's ledger ({label})",
              r.status_code in (401, 403), str(r.status_code))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)


asyncio.run(main())

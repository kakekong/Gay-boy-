"""Correcting what the company actually holds.

"Cash on hand" is the headline figure on the financial reports page, and it
is not a number anybody typed: it is the sum of the Cash & Bank balances,
and each of those is the sum of everything ever posted to that account. So
making it editable could not mean writing over the total — the ledger that
explains it would stay where it was, and the next report would contradict
the screen.

It means saying what an account really holds, and posting the difference.
That is what is checked here: a correction becomes an ordinary, balanced,
dated journal entry — the cash account on one side, opening-balance equity
on the other — which moves the balance, moves the headline figure, shows up
in the general journal, and can be reversed there like anything else.

And the guard rails around it, because this is the one screen where a number
can be asserted rather than derived: it is finance's and the director's,
nobody else's; it refuses an account that is not cash, a heading that is the
sum of the accounts under it, a correction to the figure already on the
books, and two cash accounts on both sides — which is not a correction at
all, it is a transfer, and it belongs on the Cash & bank page.
"""
import asyncio, os, sys, uuid
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123",
    STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import httpx, logging; logging.disable(logging.INFO)
TAG = uuid.uuid4().hex[:6]
PASS, FAIL = [], []
def check(n, c, d=""):
    (PASS if c else FAIL).append(n); print(("  PASS " if c else "  FAIL ")+n+(f"  [{d}]" if d and not c else ""))
def J(r):
    try: return r.json()
    except Exception: return {"_": r.text[:200]}
def why(r):
    b = J(r)
    return str(b.get("detail") or (b.get("errors") or [{}])[0].get("message", "")).lower()

CASH = "1102-01"      # Kas Kecil
BANK = "1101-01"      # Bank Bca
EQUITY = "300001"     # Equitas Saldo Awal


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.scripts.coa_seed import COA_SEED  # noqa: F401  (schema sanity)
    from app.main import app
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)

    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    fin = await login("finance@demo.local")
    mgr = await login("manager@demo.local")
    adm = await login("admin@demo.local")
    s1 = await login("sales1@demo.local")

    async def summary(hdr=None):
        return J(await c.get("/finance/reports/cash", headers=hdr or fin))

    async def balance(no):
        from app.core.db import SessionLocal
        from sqlalchemy import select
        from app.models.account import Account
        async with SessionLocal() as db:
            a = await db.scalar(select(Account).where(Account.account_no == no))
            return round(float(a.balance or 0), 2) if a else None

    # ══ the figure, and who may touch it ═════════════════════════════════
    print("\n── the figure says who may correct it ──")
    s = await summary(fin)
    check("finance is told they may", s.get("may_adjust") is True, str(s.get("may_adjust")))
    check("...and the director", (await summary(d)).get("may_adjust") is True, "director")
    check("...but not the manager, who reads the reports",
          (await summary(mgr)).get("may_adjust") is False, "manager")
    check("...and not admin", (await summary(adm)).get("may_adjust") is False, "admin")
    check("the editor is given every cash account, empty ones included",
          any(a["account_no"] == CASH for a in s.get("accounts") or []),
          str(len(s.get("accounts") or [])))
    check("...while the report itself still lists only what holds money",
          all(abs(float(h["balance"])) > 0 for h in s.get("held") or []),
          str(s.get("held"))[:160])
    check("...and it names where the other side goes",
          s.get("counter_account_no") == EQUITY, str(s.get("counter_account_no")))

    for who, hdr in (("the manager", mgr), ("admin", adm), ("sales", s1)):
        r = await c.post("/finance/reports/cash/adjust", headers=hdr,
                         json={"account_no": CASH, "new_balance": 1})
        check(f"{who} cannot correct the cash figure", r.status_code == 403,
              f"HTTP{r.status_code}")

    # ══ the correction ═══════════════════════════════════════════════════
    print("\n── finance says what the tin actually holds ──")
    before_acc = await balance(CASH)
    before_eq = await balance(EQUITY)
    before_total = float((await summary())["total_held"])
    target = round(before_acc + 2_500_000, 2)
    r = await c.post("/finance/reports/cash/adjust", headers=fin, json={
        "account_no": CASH, "new_balance": target,
        "memo": f"counted against the tin {TAG}"})
    check("the correction is accepted", r.status_code == 201,
          f"{r.status_code} {why(r)}")
    body = J(r)
    check("...for exactly the difference",
          abs(float(body.get("delta") or 0) - 2_500_000) < 0.01, str(body.get("delta")))
    check("...and it says so as a numbered journal entry",
          str(body.get("journal_number", "")).startswith("JU-"),
          str(body.get("journal_number")))
    check("the account now holds what was typed",
          await balance(CASH) == target, f"{await balance(CASH)} != {target}")
    check("...the other side landing on opening-balance equity",
          abs((await balance(EQUITY)) - (before_eq + 2_500_000)) < 0.01,
          f"{await balance(EQUITY)} vs {before_eq}")
    s = await summary()
    check("...and the headline figure moves with it",
          abs(float(s["total_held"]) - (before_total + 2_500_000)) < 0.01,
          f"{s['total_held']} vs {before_total}")

    # A figure that moved with nothing in the journal to explain it is the
    # whole reason this is not a plain edit.
    je = J(await c.get("/journals", headers=fin, params={"source_type": "adjustment"}))
    rows = je if isinstance(je, list) else (je.get("items") or je.get("entries") or [])
    mine = next((x for x in rows if x.get("number") == body.get("journal_number")), None)
    check("the entry is in the general journal", mine is not None, str(rows)[:200])
    check("...posted, not left as a draft", mine and mine.get("is_posted") is True,
          str(mine)[:200])
    check("...and carrying the reason that was typed",
          mine and TAG in str(mine.get("memo")), str(mine and mine.get("memo"))[:160])

    print("\n── and down again ──")
    r = await c.post("/finance/reports/cash/adjust", headers=d, json={
        "account_no": CASH, "new_balance": before_acc})
    check("the director puts it back", r.status_code == 201, f"{r.status_code} {why(r)}")
    check("...by posting the opposite difference",
          abs(float(J(r).get("delta") or 0) + 2_500_000) < 0.01, str(J(r).get("delta")))
    check("...leaving the account where it started",
          await balance(CASH) == before_acc, f"{await balance(CASH)} vs {before_acc}")
    check("...and equity too — the two corrections net to nothing",
          abs((await balance(EQUITY)) - before_eq) < 0.01,
          f"{await balance(EQUITY)} vs {before_eq}")

    # ══ what it refuses ══════════════════════════════════════════════════
    print("\n── what it will not do ──")
    r = await c.post("/finance/reports/cash/adjust", headers=fin,
                     json={"account_no": CASH, "new_balance": await balance(CASH)})
    check("correcting a figure to what it already is is refused",
          r.status_code == 409 and "already" in why(r), f"{r.status_code} {why(r)}")
    r = await c.post("/finance/reports/cash/adjust", headers=fin,
                     json={"account_no": "110301", "new_balance": 1_000})
    check("a receivable is not cash — refused",
          r.status_code == 400 and "cash" in why(r), f"{r.status_code} {why(r)}")
    r = await c.post("/finance/reports/cash/adjust", headers=fin,
                     json={"account_no": "1102", "new_balance": 1_000})
    check("a heading cannot be corrected — it is the sum of what is under it",
          r.status_code == 400 and "heading" in why(r), f"{r.status_code} {why(r)}")
    r = await c.post("/finance/reports/cash/adjust", headers=fin,
                     json={"account_no": f"9999-{TAG[:2]}", "new_balance": 1_000})
    check("an account that does not exist is refused", r.status_code == 404,
          f"HTTP{r.status_code}")
    r = await c.post("/finance/reports/cash/adjust", headers=fin, json={
        "account_no": CASH, "new_balance": (await balance(CASH)) + 1_000,
        "counter_account_no": BANK})
    check("cash on both sides is a transfer, not a correction",
          r.status_code == 400 and "transfer" in why(r), f"{r.status_code} {why(r)}")
    check("...and nothing moved on the refusal",
          await balance(CASH) == before_acc, str(await balance(CASH)))

    # ══ naming a different counter-account ═══════════════════════════════
    # ══ naming a different counter-account ═══════════════════════════════
    #
    # Equity is the default because "the cash figure was wrong" usually means
    # the starting point was wrong. But a shortfall found on a bank statement
    # has a better home: the charge that caused it. Naming it books the
    # difference where it belongs, and — because the counter is read in its
    # own normal direction — the expense goes UP as the bank goes down, which
    # is the whole point of letting it be named.
    print("\n── the other side can be named ──")
    other = "7200-02"   # Beban Adm. Bank — where a bank charge belongs
    from app.core.db import SessionLocal
    from sqlalchemy import select
    from app.models.account import Account
    async with SessionLocal() as db:
        exists = await db.scalar(select(Account).where(Account.account_no == other))
    if exists is None:
        check("(skipped: no alternate counter-account seeded)", True)
    else:
        before_other = await balance(other)
        before_bank = await balance(BANK)
        r = await c.post("/finance/reports/cash/adjust", headers=fin, json={
            "account_no": BANK, "new_balance": before_bank - 750_000,
            "counter_account_no": other, "memo": f"bank charge found {TAG}"})
        check("a correction may balance against an account you name",
              r.status_code == 201, f"{r.status_code} {why(r)}")
        check("...the bank coming down by the shortfall",
              abs((await balance(BANK)) - (before_bank - 750_000)) < 0.01,
              f"{await balance(BANK)} vs {before_bank}")
        check("...and the charge that explains it going up",
              abs((await balance(other)) - (before_other + 750_000)) < 0.01,
              f"{await balance(other)} vs {before_other}")

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)


asyncio.run(main())

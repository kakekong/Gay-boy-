"""The director deletes an account — and can get it back.

Deleting writes the account and every line posted to it into a file in the
document store (Cloudflare R2 in production) and takes both out of the
database. For a week a copy is also kept in the database for an instant
restore; after that only the file is left — and the file restores it, lines
and balance, exactly as it was.

* Only the director deletes; protected accounts, headings with accounts
  under them and accounts a live journal entry uses are refused.
* Deleted: gone from the chart and the ledger; listed under Recently deleted.
* Restored from the database copy within the week.
* Past the week the copy here is dropped — and the file still restores it.
"""
import asyncio, json, os, sys, uuid
from datetime import date, timedelta
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
    from app.models.account import Account, AccountArchive
    from app.models.finance import LedgerEntry
    from app.services import storage
    from app.services.ledger import journal_post, _bump
    from sqlalchemy import select, func, update
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d, fin, adm = [await login(f"{x}@demo.local") for x in ("director", "finance", "admin")]

    # An account with a balance and two lines the app posted to it.
    no = f"1109{TAG}"
    acc = J(await c.post("/accounts", headers=d, json={
        "account_no": no, "name": f"Kas Uji {TAG}", "account_type": "Cash & Bank", "balance": 0}))
    async with SessionLocal() as s:
        for amt in (250_000, -50_000):
            m = await _bump(s, no, amt)
            await journal_post(s, entry_date=date.today(), account_no=no,
                               account_type=m["account_type"], account_name=m["name"],
                               amount=amt, source_type="manual", source_ref=f"T-{TAG}",
                               memo=f"test {TAG}")
        await s.commit()

    async def lines():
        async with SessionLocal() as s:
            return await s.scalar(select(func.count()).select_from(LedgerEntry)
                                  .where(LedgerEntry.account_no == no))

    async def on_chart():
        return any(a["account_no"] == no for a in J(await c.get("/accounts", headers=d, params={"q": no})))

    print("\n── who may delete what ──")
    r = await c.delete(f"/accounts/{acc['id']}", headers=adm)
    check("admin can't delete an account", r.status_code == 403, str(r.status_code))
    r = await c.delete(f"/accounts/{acc['id']}", headers=fin)
    check("nor can finance", r.status_code == 403, str(r.status_code))
    coa = J(await c.get("/accounts", headers=d))
    byno = {a["account_no"]: a for a in coa}
    r = await c.delete(f"/accounts/{byno['210101']['id']}", headers=d)
    check("Utang Usaha can't go — the app posts to it", r.status_code == 409 and "post" in J(r)["errors"][0]["message"],
          f"{r.status_code} {J(r)}"[:200])
    head = next(a for a in coa if a["is_parent"] and any(k["parent_account_no"] == a["account_no"] for k in coa))
    r = await c.delete(f"/accounts/{head['id']}", headers=d)
    check("a heading with accounts under it can't go", r.status_code == 409, str(r.status_code))
    other = f"1108{TAG}"
    oth = J(await c.post("/accounts", headers=d, json={
        "account_no": other, "name": f"Kas Lain {TAG}", "account_type": "Cash & Bank", "balance": 0}))
    je = J(await c.post("/journals", headers=d, json={"entry_date": date.today().isoformat(),
        "memo": f"pakai {TAG}", "lines": [{"account_no": other, "debit": 1000},
                                         {"account_no": "1101-01", "credit": 1000}]}))
    r = await c.delete(f"/accounts/{oth['id']}", headers=d)
    check("an account a journal entry uses can't go until it is voided",
          r.status_code == 409 and "void" in J(r)["errors"][0]["message"], f"{r.status_code} {J(r)}"[:200])

    print("\n── deleted ──")
    r = await c.delete(f"/accounts/{acc['id']}", headers=d, params={"reason": f"test {TAG}"})
    check("the director deletes it", r.status_code == 200 and J(r)["entries"] == 2, f"{r.status_code} {J(r)}"[:200])
    arc_id = J(r).get("archive_id")
    check("it is off the chart", not await on_chart())
    check("...and its lines are out of the database", await lines() == 0)
    r = await c.get(f"/journals/account/{no}", headers=fin)
    check("...its ledger is gone", r.status_code == 404, str(r.status_code))
    bin_ = J(await c.get("/accounts/archives", headers=d))
    row = next((a for a in bin_ if a["id"] == arc_id), None)
    check("it is under Recently deleted, kept here for a week, with a file",
          row and row["in_database"] and row["has_file"] and row["entry_count"] == 2
          and abs(row["balance"] - 200_000) < 0.01 and row["reason"] == f"test {TAG}", str(row)[:250])
    r = await c.get("/accounts/archives", headers=fin)
    check("only the director sees the list", r.status_code == 403, str(r.status_code))
    async with SessionLocal() as s:
        arc = await s.get(AccountArchive, uuid.UUID(arc_id))
        blob = await storage.load(arc.storage_path)
    data = json.loads(blob) if blob else {}
    check("the file holds the account and its lines",
          data.get("account", {}).get("account_no") == no and len(data.get("ledger_entries", [])) == 2)
    r = await c.get(f"/accounts/archives/{arc_id}/file", headers=d)
    check("...and can be downloaded", r.status_code == 200 and json.loads(r.content)["account"]["account_no"] == no)

    print("\n── restored within the week ──")
    r = await c.post(f"/accounts/archives/{arc_id}/restore", headers=d)
    check("restored from the copy here", r.status_code == 200 and J(r)["from_file"] is False, f"{r.status_code} {J(r)}"[:200])
    L = J(await c.get(f"/journals/account/{no}", headers=fin, params={"all": True}))
    check("...back on the chart with its balance and both lines",
          await on_chart() and await lines() == 2 and abs(L["account"]["balance"] - 200_000) < 0.01,
          str(L.get("account")))
    r = await c.post(f"/accounts/archives/{arc_id}/restore", headers=d)
    check("restoring twice is refused", r.status_code == 409, str(r.status_code))

    print("\n── past the week: only the file ──")
    acc2 = next(a for a in J(await c.get("/accounts", headers=d, params={"q": no})) if a["account_no"] == no)
    r = await c.delete(f"/accounts/{acc2['id']}", headers=d)
    arc2 = J(r)["archive_id"]
    async with SessionLocal() as s:
        await s.execute(update(AccountArchive).where(AccountArchive.id == uuid.UUID(arc2))
                        .values(deleted_at=AccountArchive.deleted_at - timedelta(days=8)))
        await s.commit()
    bin_ = J(await c.get("/accounts/archives", headers=d))
    row = next((a for a in bin_ if a["id"] == arc2), None)
    check("after a week the copy here is dropped — the file remains",
          row and row["in_database"] is False and row["has_file"], str(row)[:200])
    async with SessionLocal() as s:
        arc = await s.get(AccountArchive, uuid.UUID(arc2))
    check("...the row left is only a pointer", arc.data is None and arc.storage_path)
    r = await c.post(f"/accounts/archives/{arc2}/restore", headers=d)
    check("the file restores it", r.status_code == 200 and J(r)["from_file"] is True, f"{r.status_code} {J(r)}"[:200])
    L = J(await c.get(f"/journals/account/{no}", headers=fin, params={"all": True}))
    check("...exactly as it was: balance and both lines",
          await on_chart() and await lines() == 2 and abs(L["account"]["balance"] - 200_000) < 0.01)

    # Leave the books as found.
    async with SessionLocal() as s:
        from sqlalchemy import delete
        await s.execute(delete(LedgerEntry).where(LedgerEntry.account_no == no))
        await s.execute(update(Account).where(Account.account_no == no).values(balance=0))
        await s.commit()

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

"""Aset Tetap — the register, the monthly run, and what happens to an asset.

The arithmetic is checked on its own in tests/test_depreciation.py. What is
checked here is everything the arithmetic is embedded in, which is where
fixed assets actually go wrong:

- **A month runs once.** Depreciation is the one entry nobody looks at, so a
  double-run is invisible until the year does not close. The guard is a row,
  not a flag, and the refusal names what the first run posted.
- **A run can be looked at before it is real.** It touches every asset at
  once; the alternative to previewing it is reversing it.
- **An asset with no accounts is named, not skipped.** Silently dropping it
  under-depreciates the company by exactly the amount nobody noticed.
- **Disposal produces a number.** Cost off, accumulated off, proceeds in,
  and the residual is the gain or the loss — which is the entire reason to
  dispose of an asset rather than delete it.
- **The two categories disagree on purpose.** The commercial books use the
  life the company expects; the tax return uses the statutory group. The
  test asserts they differ, because a system that quietly made them agree
  would look like it was working.
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

    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    fin = await login("finance@demo.local")
    mgr = await login("manager@demo.local")
    s1 = await login("sales1@demo.local")

    async def balance(no):
        rows = J(await c.get("/accounts", headers=fin, params={"limit": 500}))
        rows = rows if isinstance(rows, list) else rows.get("items", [])
        for a in rows:
            if a["account_no"] == no:
                return float(a.get("balance") or 0)
        return None

    # Accounts to hang the category on. Made rather than borrowed, so the
    # figures below are this test's and nobody else's.
    # The chart is the director's to shape, not finance's — so these are
    # made as the director, which is also the real permission boundary.
    async def make_account(no, name, kind):
        r = await c.post("/accounts", headers=d, json={
            "account_no": no, "name": name, "account_type": kind})
        return r.status_code in (200, 201, 409), J(r)
    ASSET, ACCUM, EXPENSE = f"1801{tag[:2]}", f"1802{tag[:2]}", f"6801{tag[:2]}"
    GAIN, BANKACC = f"7801{tag[:2]}", f"1102{tag[:2]}"
    made = [await make_account(ASSET, f"Kendaraan {tag}", "Fixed Asset"),
            # Contra-asset: credit-normal, so a month's depreciation raises
            # it rather than lowering it.
            await make_account(ACCUM, f"Akum. Peny. Kendaraan {tag}",
                               "Accumulated Depreciation"),
            await make_account(EXPENSE, f"Beban Penyusutan {tag}", "Expense"),
            await make_account(GAIN, f"Laba/Rugi Pelepasan {tag}", "Other Income"),
            await make_account(BANKACC, f"Bank Aset {tag}", "Cash & Bank")]
    check("the accounts the register posts to exist",
          all(ok for ok, _ in made), str([b for ok, b in made if not ok])[:200])

    print("\n=== Two categories, because the two answers differ ===")
    groups = J(await c.get("/assets/tax-groups", headers=fin))
    check("the statutory groups are offered, not typed",
          isinstance(groups, list) and len(groups) == 6, str(len(groups)))
    k2 = next((g for g in groups if g["value"] == "kelompok_2"), None)
    check("...Kelompok 2 is eight years at 25% declining",
          k2 and k2["years"] == 8 and k2["declining_pct"] == 25.0, str(k2))
    building = next((g for g in groups
                     if g["value"] == "bangunan_permanen"), None)
    check("...and a building has no declining rate, because the law gives none",
          building and building["declining_pct"] is None, str(building))

    r = await c.post("/assets/categories", headers=fin, json={
        "name": f"Kendaraan {tag}", "scope": "commercial",
        "method": "straight_line", "useful_life_months": 60,
        "asset_account_no": ASSET, "accum_account_no": ACCUM,
        "expense_account_no": EXPENSE})
    check("finance sets up a commercial category", r.status_code == 201,
          f"{r.status_code} {J(r)}")
    cat = J(r)

    r = await c.post("/assets/categories", headers=fin, json={
        "name": f"Kelompok 2 {tag}", "scope": "tax", "tax_group": "kelompok_2",
        "method": "declining_balance"})
    check("...and a fiscal one", r.status_code == 201, f"{r.status_code} {J(r)}")
    tax_cat = J(r)
    check("...whose life is the law's, not the form's",
          tax_cat["useful_life_months"] == 96,
          str(tax_cat.get("useful_life_months")))

    r = await c.post("/assets/categories", headers=fin, json={
        "name": f"Gedung {tag}", "scope": "tax",
        "tax_group": "bangunan_permanen", "method": "declining_balance"})
    check("a declining building is refused — the law has no rate for it",
          r.status_code == 400, f"{r.status_code} {J(r)}")
    check("...and says so", "declining" in why(r), str(J(r))[:160])

    r = await c.post("/assets/categories", headers=fin, json={
        "name": f"Kendaraan {tag}", "scope": "commercial"})
    check("the same category twice is refused", r.status_code == 409,
          str(r.status_code))
    r = await c.post("/assets/categories", headers=mgr, json={
        "name": f"Manager {tag}", "scope": "commercial"})
    check("a manager reads the register but does not set it up",
          r.status_code in (401, 403), str(r.status_code))
    r = await c.get("/assets/categories", headers=s1)
    check("sales has no business in the asset register",
          r.status_code in (401, 403), str(r.status_code))

    print("\n=== The asset itself ===")
    # A truck, acquired at the start of last year so several months are due.
    today = date.today()
    start_year = today.year - 1
    r = await c.post("/assets", headers=fin, json={
        "name": f"Truk Hino {tag}", "category_id": cat["id"],
        "tax_category_id": tax_cat["id"],
        "acquired_on": f"{start_year}-01-15",
        "cost": 600_000_000, "salvage_value": 0,
        "location": "Gudang Cikarang", "serial_no": f"SN-{tag}"})
    check("the asset lands in the register", r.status_code == 201,
          f"{r.status_code} {J(r)}")
    truck = J(r)
    check("...numbered", truck["number"].startswith("AST-"), truck.get("number"))
    check("...on the category's life, since none was typed",
          truck["useful_life_months"] == 60,
          str(truck.get("useful_life_months")))
    check("...and worth what it cost, until something is posted",
          truck["book_value"] == 600_000_000, str(truck.get("book_value")))

    r = await c.post("/assets", headers=fin, json={
        "name": f"Bad {tag}", "category_id": cat["id"],
        "acquired_on": f"{start_year}-01-15", "cost": 10_000_000,
        "salvage_value": 12_000_000})
    check("residual above cost is refused — it would depreciate upwards",
          r.status_code == 400, f"{r.status_code} {J(r)}")
    r = await c.post("/assets", headers=fin, json={
        "name": f"Free {tag}", "acquired_on": f"{start_year}-01-15",
        "cost": 5_000_000})
    check("an asset with no category and no life is refused",
          r.status_code == 400, f"{r.status_code} {J(r)}")

    print("\n=== The commercial and fiscal schedules disagree ===")
    comm = J(await c.get(f"/assets/{truck['id']}/schedule", headers=fin))
    fiscal = J(await c.get(f"/assets/{truck['id']}/schedule", headers=fin,
                           params={"scope": "tax"}))
    check("the commercial schedule runs the company's five years",
          len(comm["items"]) == 60, str(len(comm.get("items", []))))
    check("...at the same amount every month",
          comm["items"][0]["amount"] == 10_000_000,
          str(comm["items"][0]["amount"]))
    check("the fiscal schedule runs the law's eight",
          fiscal["tax_group"] == "kelompok_2"
          and fiscal["method"] == "declining_balance",
          str(fiscal.get("tax_group")))
    check("...heavier in the first year, which is the point of declining",
          fiscal["items"][0]["amount"] > comm["items"][0]["amount"],
          f"{fiscal['items'][0]['amount']} vs {comm['items'][0]['amount']}")
    check("...and the two do not agree in year one — that gap is the "
          "fiscal reconciliation",
          round(sum(x["amount"] for x in fiscal["items"][:12]), 2)
          != round(sum(x["amount"] for x in comm["items"][:12]), 2))

    print("\n=== A month is previewed before it is posted ===")
    r = await c.post("/assets/depreciation/run", headers=fin,
                     json={"year": start_year, "month": 3})
    check("the preview runs", r.status_code == 200, f"{r.status_code} {J(r)}")
    prev = J(r)
    check("...without posting anything", prev["posted"] is False, str(prev.get("posted")))
    check("...and shows the truck at its monthly figure",
          any(i["number"] == truck["number"] and i["amount"] == 10_000_000
              for i in prev["items"]), str(prev.get("items"))[:220])
    before = await balance(ACCUM)
    check("...the ledger has not moved", before == 0, str(before))

    r = await c.post("/assets/depreciation/run", headers=fin,
                     json={"year": today.year + 1, "month": 1})
    check("a month that has not happened yet is refused", r.status_code == 400,
          str(r.status_code))
    r = await c.post("/assets/depreciation/run", headers=fin,
                     json={"year": start_year, "month": 13})
    check("month 13 is refused", r.status_code == 400, str(r.status_code))

    print("\n=== …and then posted, once ===")
    r = await c.post("/assets/depreciation/run", headers=fin,
                     json={"year": start_year, "month": 3, "post": True})
    check("the run posts", r.status_code == 200 and J(r)["posted"] is True,
          f"{r.status_code} {J(r)}")
    run = J(r)
    check("...with an entry behind it", bool(run.get("journal_number")),
          str(run.get("journal_number")))
    check("the accumulated-depreciation account moved by the run total",
          await balance(ACCUM) == run["total_amount"],
          f"{await balance(ACCUM)} vs {run['total_amount']}")
    check("...and the expense account by the same",
          await balance(EXPENSE) == run["total_amount"],
          f"{await balance(EXPENSE)} vs {run['total_amount']}")

    got = J(await c.get(f"/assets/{truck['id']}", headers=fin))
    check("the asset carries the month against it",
          got["accumulated_depreciation"] == 10_000_000,
          str(got.get("accumulated_depreciation")))
    check("...and its book value fell by exactly that",
          got["book_value"] == 590_000_000, str(got.get("book_value")))
    check("...with the month itemised, not just totalled",
          any(e["period_month"] == 3 and e["amount"] == 10_000_000
              for e in got["entries"]), str(got.get("entries"))[:200])

    r = await c.post("/assets/depreciation/run", headers=fin,
                     json={"year": start_year, "month": 3, "post": True})
    check("the same month twice is refused", r.status_code == 409,
          f"{r.status_code} {J(r)}")
    check("...and the refusal says what the first run did",
          "already been run" in why(r), str(J(r))[:180])

    # Depreciating the same month again must not move the ledger at all.
    check("...and nothing moved on the second attempt",
          await balance(ACCUM) == run["total_amount"], str(await balance(ACCUM)))

    print("\n=== An asset with no accounts is named, not dropped ===")
    r = await c.post("/assets/categories", headers=fin, json={
        "name": f"Belum diatur {tag}", "scope": "commercial",
        "useful_life_months": 24})
    bare_cat = J(r)
    r = await c.post("/assets", headers=fin, json={
        "name": f"Mesin tanpa akun {tag}", "category_id": bare_cat["id"],
        "acquired_on": f"{start_year}-01-10", "cost": 24_000_000})
    bare = J(r)
    prev = J(await c.post("/assets/depreciation/run", headers=fin,
                          json={"year": start_year, "month": 4}))
    check("the run names the asset it cannot post",
          any(s["number"] == bare["number"] for s in prev["skipped"]),
          str(prev.get("skipped"))[:200])
    check("...and says why", any("account" in (s.get("why") or "").lower()
                                 for s in prev["skipped"]),
          str(prev.get("skipped"))[:200])
    check("...while still counting the ones it can",
          any(i["number"] == truck["number"] for i in prev["items"]),
          str(prev.get("items"))[:200])

    print("\n=== Perubahan Aset Tetap and Pindah Aset ===")
    r = await c.post(f"/assets/{truck['id']}/move", headers=fin,
                     json={"location": "Gudang Bekasi", "memo": "Pindah proyek"})
    check("an asset moves", r.status_code == 200, f"{r.status_code} {J(r)}")
    r = await c.post(f"/assets/{truck['id']}/move", headers=fin,
                     json={"location": "Gudang Bekasi"})
    check("...but not to where it already is", r.status_code == 400,
          str(r.status_code))
    got = J(await c.get(f"/assets/{truck['id']}", headers=fin))
    check("...and the move is on the record with both ends",
          any(ch["kind"] == "move" and ch["before_value"] == "Gudang Cikarang"
              and ch["after_value"] == "Gudang Bekasi"
              for ch in got["changes"]), str(got.get("changes"))[:250])

    accum_before = await balance(ACCUM)
    r = await c.post(f"/assets/{truck['id']}/adjust", headers=fin,
                     json={"kind": "life", "new_life_months": 84,
                           "memo": "Diperpanjang setelah overhaul"})
    check("a change of expected life is recorded", r.status_code == 200,
          f"{r.status_code} {J(r)}")
    check("...and moves no money, because nothing was bought",
          await balance(ACCUM) == accum_before, str(await balance(ACCUM)))
    got = J(await c.get(f"/assets/{truck['id']}", headers=fin))
    check("...but every month after it is a different number",
          got["useful_life_months"] == 84, str(got.get("useful_life_months")))

    asset_before = await balance(ASSET)
    r = await c.post(f"/assets/{truck['id']}/adjust", headers=fin,
                     json={"kind": "cost", "new_cost": 650_000_000,
                           "counter_account_no": BANKACC,
                           "memo": "Karoseri tambahan"})
    check("a change of cost is recorded", r.status_code == 200,
          f"{r.status_code} {J(r)}")
    check("...and it does move money, because something was bought",
          round(await balance(ASSET) - asset_before, 2) == 50_000_000,
          f"{await balance(ASSET)} vs {asset_before}")
    r = await c.post(f"/assets/{truck['id']}/adjust", headers=fin,
                     json={"kind": "cost", "new_cost": 5_000_000,
                           "counter_account_no": BANKACC})
    check("a cost below what has been written off is refused",
          r.status_code == 409, f"{r.status_code} {J(r)}")

    print("\n=== Aset per Lokasi ===")
    places = J(await c.get("/assets/by-location", headers=fin))
    bekasi = next((p for p in places if p["location"] == "Gudang Bekasi"), None)
    check("the register groups by where things are", bekasi is not None,
          str(places)[:200])
    check("...with what is worth what, there",
          bekasi and bekasi["book_value"] == bekasi["cost"] - bekasi["accumulated"],
          str(bekasi))
    unplaced = next((p for p in places if p["location"] is None), None)
    check("...and 'we do not know where it is' is a finding, not a gap",
          unplaced is not None and unplaced["count"] >= 1, str(unplaced))

    print("\n=== Disposisi Aset ===")
    # A second, small asset so the disposal maths is checkable by hand.
    r = await c.post("/assets", headers=fin, json={
        "name": f"Forklift {tag}", "category_id": cat["id"],
        "acquired_on": f"{start_year}-01-01", "cost": 120_000_000,
        "salvage_value": 0, "opening_accum": 100_000_000,
        "location": "Gudang Bekasi"})
    fork = J(r)
    check("an asset can be entered part-worn", r.status_code == 201
          and fork["book_value"] == 20_000_000, f"{r.status_code} {J(r)}")

    gain_before = await balance(GAIN)
    r = await c.post(f"/assets/{fork['id']}/dispose", headers=fin, json={
        "on": f"{today.year}-{today.month:02d}-01",
        "proceeds": 30_000_000, "proceeds_account_no": BANKACC,
        "gain_loss_account_no": GAIN, "reason": "Dijual"})
    check("the disposal posts", r.status_code == 200, f"{r.status_code} {J(r)}")
    d = J(r)
    check("...and produces the number it exists to produce: a 10m gain",
          d["gain"] == 10_000_000 and d["loss"] == 0, str(d))
    check("...which is proceeds minus book value, not proceeds minus cost",
          d["book_value"] == 20_000_000 and d["proceeds"] == 30_000_000, str(d))
    check("...and lands on the profit report",
          round(await balance(GAIN) - gain_before, 2) == 10_000_000,
          f"{await balance(GAIN)} vs {gain_before}")

    r = await c.post(f"/assets/{fork['id']}/dispose", headers=fin, json={
        "gain_loss_account_no": GAIN})
    check("disposing of it twice is refused", r.status_code == 409,
          str(r.status_code))
    r = await c.post(f"/assets/{fork['id']}/move", headers=fin,
                     json={"location": "Gudang Cikarang"})
    check("...and a disposed asset does not move", r.status_code == 409,
          str(r.status_code))
    got = J(await c.get(f"/assets/{fork['id']}", headers=fin))
    check("...its screen says the door is shut, and why",
          got["may"]["edit"] is False and "disposed" in (got.get("locked_because") or "").lower(),
          f"{got.get('may')} / {got.get('locked_because')}")

    print("\n=== Nothing depreciated is deleted ===")
    r = await c.delete(f"/assets/{truck['id']}", headers=fin)
    check("an asset with posted depreciation cannot be deleted",
          r.status_code == 409, f"{r.status_code} {J(r)}")
    check("...and is told to dispose of it instead", "dispose" in why(r),
          str(J(r))[:180])
    r = await c.delete(f"/assets/{bare['id']}", headers=fin)
    check("one that never was, can be", r.status_code == 200,
          f"{r.status_code} {J(r)}")
    r = await c.delete(f"/assets/categories/{cat['id']}", headers=fin)
    check("a category still in use cannot be deleted", r.status_code == 409,
          f"{r.status_code} {J(r)}")

    print("\n=== A run can be taken back ===")
    runs = J(await c.get("/assets/depreciation/runs", headers=fin))
    mine = next((x for x in runs if x["period_year"] == start_year
                 and x["period_month"] == 3), None)
    check("the run is on the record", mine is not None, str(runs)[:200])
    accum_before = await balance(ACCUM)
    r = await c.post(f"/assets/depreciation/runs/{mine['id']}/reverse",
                     headers=fin, params={"reason": "Salah periode"})
    check("it reverses", r.status_code == 200, f"{r.status_code} {J(r)}")
    check("...and the ledger comes back",
          round(accum_before - await balance(ACCUM), 2) == mine["total_amount"],
          f"{accum_before} → {await balance(ACCUM)}")
    got = J(await c.get(f"/assets/{truck['id']}", headers=fin))
    check("...and so does the asset",
          got["accumulated_depreciation"] == 0,
          str(got.get("accumulated_depreciation")))
    r = await c.post("/assets/depreciation/run", headers=fin,
                     json={"year": start_year, "month": 3, "post": True})
    check("...so the month can be run again", r.status_code == 200,
          f"{r.status_code} {J(r)}")
    r = await c.post(f"/assets/depreciation/runs/{mine['id']}/reverse",
                     headers=fin)
    check("but a reversal is not repeatable either", r.status_code == 409,
          str(r.status_code))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)


asyncio.run(main())

"""Master data — Pajak and Gaji/Tunjangan.

The two lists finance sets up once and picks from everywhere else. What is
being tested is not that a row saves; it is that each row carries the
consequence of choosing it.

**A tax is a pair of accounts, not a rate.** The same tax sits on opposite
sides of the books depending on which way the invoice points — pajak
keluaran is money we are holding for the state, pajak masukan is money we
will claim back. One row holds both, and both have to be accounts you can
actually post to, because a heading or a suspended account is a return that
will not reconcile and nobody finds out until it is filed.

**A payroll component is a type, not an amount.** Gross, net, and the PPh 21
base are three different numbers, and which of the three an amount touches
is decided entirely by its type. "Potongan Gaji (Tidak Mengurangi PPh)" and
"Pengurangan Gaji (Mengurangi PPh)" are the same deduction on a payslip and
different on a tax return — so `/compute` is checked against a case where
they diverge, since a calculator that agrees with itself on the easy input
proves nothing.
"""
import asyncio, os, sys, uuid
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
    """The refusal text, out of the error envelope the app wraps it in."""
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
    fin = await login("finance@demo.local")
    mgr = await login("manager@demo.local")
    s1 = await login("sales1@demo.local")
    hr = await login("hr@demo.local")

    print("\n=== The seven tax types, not free text ===")
    kinds = J(await c.get("/master/tax-types/kinds", headers=fin))
    check("the kinds are offered", isinstance(kinds, list) and len(kinds) == 7,
          str(kinds)[:120])
    values = {k["value"] for k in kinds}
    check("...and they are the ones the forms distinguish",
          {"ppn", "ppnbm", "pph_21", "pph_23"} <= values, str(values))
    r = await c.post("/master/tax-types", headers=fin,
                     json={"kind": "pajak_karangan", "description": "Made up"})
    check("a type nobody files is refused", r.status_code == 400, str(r.status_code))

    print("\n=== A tax is a pair of accounts ===")
    # Real, postable accounts to hang the pair on.
    accs = J(await c.get("/accounts", headers=fin, params={"limit": 500}))
    rows = accs if isinstance(accs, list) else accs.get("items", [])
    postable = [a for a in rows
                if not a.get("is_parent") and not a.get("is_suspended")]
    heading = next((a for a in rows if a.get("is_parent")), None)
    check("the chart has accounts to point at", len(postable) >= 2,
          str(len(postable)))
    out_acc, in_acc = postable[0]["account_no"], postable[1]["account_no"]

    r = await c.post("/master/tax-types", headers=fin, json={
        "kind": "ppn", "description": f"PPN Keluaran 11% {tag}",
        "rate_pct": 11, "sales_account_no": out_acc,
        "purchase_account_no": in_acc})
    check("finance sets up a tax", r.status_code == 201, f"{r.status_code} {J(r)}")
    tax = J(r)
    check("...it keeps both sides apart",
          tax.get("sales_account_no") == out_acc
          and tax.get("purchase_account_no") == in_acc, str(tax)[:160])
    check("...and names them, because 2103 reads to nobody",
          bool(tax.get("sales_account_name")), str(tax.get("sales_account_name")))
    check("...under the label the tax office uses",
          tax.get("kind_label") == "Pajak Pertambahan Nilai",
          str(tax.get("kind_label")))

    if heading:
        r = await c.post("/master/tax-types", headers=fin, json={
            "kind": "ppn", "description": f"Bad heading {tag}",
            "sales_account_no": heading["account_no"]})
        check("a heading is refused as a tax account", r.status_code == 400,
              f"{r.status_code} {J(r)}")
        check("...and the refusal says why", "heading" in why(r), str(J(r))[:160])
    r = await c.post("/master/tax-types", headers=fin, json={
        "kind": "ppn", "description": f"Nowhere {tag}",
        "purchase_account_no": "9999999"})
    check("an account that does not exist is refused", r.status_code == 400,
          str(r.status_code))
    r = await c.post("/master/tax-types", headers=fin, json={
        "kind": "ppn", "description": f"PPN Keluaran 11% {tag}"})
    check("the same tax twice is refused", r.status_code == 409,
          f"{r.status_code} {J(r)}")
    r = await c.post("/master/tax-types", headers=fin, json={
        "kind": "pph_23", "description": f"PPh 23 jasa {tag}", "rate_pct": 140})
    check("a rate that is not a percentage is refused", r.status_code == 400,
          str(r.status_code))

    r = await c.patch(f"/master/tax-types/{tax['id']}", headers=fin,
                      json={"rate_pct": 12})
    check("a rate that changed is edited in place",
          r.status_code == 200 and J(r)["rate_pct"] == 12, f"{r.status_code} {J(r)}")
    r = await c.patch(f"/master/tax-types/{tax['id']}", headers=fin,
                      json={"is_active": False})
    listed = J(await c.get("/master/tax-types", headers=fin,
                           params={"active_only": True}))
    check("...and one taken out of use drops off the pick list",
          all(x["id"] != tax["id"] for x in listed), str(len(listed)))
    listed_all = J(await c.get("/master/tax-types", headers=fin))
    check("...but stays on the record",
          any(x["id"] == tax["id"] for x in listed_all), str(len(listed_all)))

    print("\n=== Who keeps the lists ===")
    r = await c.post("/master/tax-types", headers=mgr,
                     json={"kind": "ppn", "description": f"Manager {tag}"})
    check("a manager reads but does not set tax up", r.status_code in (401, 403),
          str(r.status_code))
    r = await c.get("/master/tax-types", headers=mgr)
    check("...and can read it", r.status_code == 200, str(r.status_code))
    r = await c.get("/master/tax-types", headers=s1)
    check("sales has no business in the tax table", r.status_code in (401, 403),
          str(r.status_code))

    print("\n=== A payroll component is a type ===")
    kinds = J(await c.get("/master/pay-components/kinds", headers=fin))
    check("the fourteen the PPh 21 form distinguishes",
          isinstance(kinds, list) and len(kinds) == 14, str(len(kinds)))
    by_kind = {k["value"]: k for k in kinds}
    check("...a bonus is irregular income", by_kind["tantiem"]["regular"] is False,
          str(by_kind.get("tantiem")))
    check("...a 'Tidak Mengurangi PPh' deduction does not move the base",
          by_kind["potongan"]["direction"] == "deduct"
          and by_kind["potongan"]["taxable"] is False, str(by_kind.get("potongan")))
    check("...and its near-twin does",
          by_kind["pengurangan"]["direction"] == "deduct"
          and by_kind["pengurangan"]["taxable"] is True,
          str(by_kind.get("pengurangan")))

    r = await c.post("/master/pay-components", headers=fin, json={
        "name": f"Gaji Pokok {tag}", "kind": "gaji",
        "account_no": out_acc, "default_amount": 5_000_000})
    check("finance sets up a salary component", r.status_code == 201,
          f"{r.status_code} {J(r)}")
    basic = J(r)
    check("...and the row carries what its type means",
          basic["direction"] == "pay" and basic["taxable"] is True,
          str(basic)[:160])

    r = await c.post("/master/pay-components", headers=fin, json={
        "name": f"Gaji Pokok {tag}", "kind": "gaji"})
    check("the same component twice is refused", r.status_code == 409,
          str(r.status_code))
    r = await c.post("/master/pay-components", headers=fin, json={
        "name": f"Negative {tag}", "kind": "potongan", "default_amount": -1})
    check("a negative amount is refused — the type says which way it goes",
          r.status_code == 400, f"{r.status_code} {J(r)}")
    r = await c.post("/master/pay-components", headers=fin, json={
        "name": f"Unknown {tag}", "kind": "bonus_lebaran"})
    check("a type the form does not know is refused", r.status_code == 400,
          str(r.status_code))

    r = await c.post("/master/pay-components", headers=fin, json={
        "name": f"Potongan Koperasi {tag}", "kind": "potongan",
        "default_amount": 200_000})
    cut = J(r)
    r = await c.post("/master/pay-components", headers=fin, json={
        "name": f"Iuran Pensiun Pekerja {tag}", "kind": "iuran_pekerja",
        "default_amount": 100_000})
    pension = J(r)
    check("both deductions save", bool(cut.get("id")) and bool(pension.get("id")),
          f"{cut.get('id')} {pension.get('id')}")

    print("\n=== Gross, net, and the tax base are three numbers ===")
    # Deliberately a case where they all differ. Two deductions of different
    # types: the koperasi cut reduces the payout only, the pension
    # contribution reduces the payout *and* the tax base. A calculator that
    # treats deductions alike gets net right and the base wrong.
    r = await c.post("/master/pay-components/compute", headers=fin, json={
        "lines": [
            {"component_id": basic["id"], "amount": 5_000_000},
            {"kind": "tunjangan_lain", "amount": 750_000},
            {"kind": "tantiem", "amount": 2_000_000},
            {"component_id": cut["id"], "amount": 200_000},
            {"component_id": pension["id"], "amount": 100_000},
        ]})
    check("the payroll maths runs", r.status_code == 200, f"{r.status_code} {J(r)}")
    m = J(r)
    check("gross is what is paid", m.get("gross") == 7_750_000, str(m.get("gross")))
    check("deductions are what is taken", m.get("deductions") == 300_000,
          str(m.get("deductions")))
    check("net is what lands in the account", m.get("net") == 7_450_000,
          str(m.get("net")))
    check("...and the tax base is neither of those",
          m.get("tax_base") == 7_650_000, str(m.get("tax_base")))
    check("...because only the deduction whose type allows it came off",
          m.get("deductible") == 100_000, str(m.get("deductible")))
    check("regular and irregular income are kept apart",
          m.get("taxable_regular") == 5_750_000
          and m.get("taxable_irregular") == 2_000_000, str(m)[:200])
    r = await c.post("/master/pay-components/compute", headers=fin, json={
        "lines": [{"amount": 1_000}]})
    check("a line with no type is refused rather than guessed",
          r.status_code == 400, str(r.status_code))

    print("\n=== Who reads the payroll list ===")
    r = await c.get("/master/pay-components", headers=hr)
    check("HR reads the components they will pick on a payslip",
          r.status_code == 200, str(r.status_code))
    r = await c.post("/master/pay-components", headers=hr,
                     json={"name": f"HR {tag}", "kind": "gaji"})
    check("...but does not set them up — the accounts are finance's",
          r.status_code in (401, 403), str(r.status_code))
    r = await c.get("/master/pay-components", headers=s1)
    check("sales does not see the payroll table at all",
          r.status_code in (401, 403), str(r.status_code))

    r = await c.delete(f"/master/pay-components/{pension['id']}", headers=fin)
    check("a row entered by mistake can be removed", r.status_code == 200,
          str(r.status_code))
    left = J(await c.get("/master/pay-components", headers=fin))
    check("...and it is gone", all(x["id"] != pension["id"] for x in left),
          str(len(left)))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)


asyncio.run(main())

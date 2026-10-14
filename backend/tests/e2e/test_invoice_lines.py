"""An invoice's lines are written by hand, in the customer's names.

The trade calls one part two different things — the vendor's technical name
and the one the customer knows — and only someone who knows both can turn one
into the other. So the invoice does not guess: whoever issues it writes the
lines the customer will read, and the sheet prints them word for word.

* Until someone does, it prints the customer's PO lines, as it always has.
* The lines must account for the money: exactly what is billed, or more on a
  final invoice (the difference prints as a discount) — never less. A down
  payment's lines must come to its amount exactly.
* Editing the amount past the lines is refused the same way.
* Like the rest of the invoice, they are fixed once finance signs it off, and
  only the desk that issues invoices writes them.
"""
import asyncio, io, os, sys, uuid
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
    from pypdf import PdfReader
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=120)
    tag = uuid.uuid4().hex[:5]

    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    adm = await login("admin@demo.local")
    fin = await login("finance@demo.local")
    s1 = await login("sales1@demo.local")
    pur = await login("purchasing@demo.local")

    async def a_project(label, qc=True):
        cust = J(await c.post("/customers", headers=s1, json={
            "company_name": f"PT Baris {label} {tag}", "industry": "mining"}))["id"]
        pr = J(await c.post("/price-requests", headers=s1, json={
            "customer_id": cust,
            "items": [{"description": f"SR-G2L2 P600 {label} {tag}", "qty": 10,
                       "uom": "pcs"}]}))["id"]
        await c.post(f"/price-requests/{pr}/submit", headers=s1)
        await c.post(f"/price-requests/{pr}/price", headers=d, json={
            "items": [{"line_no": 1, "cost_price": 50000, "basis": "unit"}]})
        await c.post(f"/price-requests/{pr}/approve", headers=d, json={
            "items": [{"line_no": 1, "sell_price": 100000, "basis": "unit"}]})
        q = J(await c.post(f"/quotations/from-price-request/{pr}", headers=s1))["id"]
        await c.post(f"/quotations/{q}/submit", headers=s1)
        await c.post(f"/quotations/{q}/approve", headers=d, json={"notes": ""})
        cpo = J(await c.post("/customer-pos", headers=s1, json={
            "customer_id": cust, "quotation_id": q, "number": f"PO-{label}-{tag}",
            "items": [{"description": f"SR-G2L2 P600 {label} {tag}", "qty": 10,
                       "unit_price": 100000}],
            "is_downpayment": False}))["id"]
        await c.post(f"/quotations/{q}/won", headers=d)
        proj = J(await c.post(f"/customer-pos/{cpo}/approve", headers=d,
                              json={"notes": ""}))["project_id"]
        if qc:
            await c.post(f"/operation/projects/{proj}/qc", headers=adm,
                         json={"decision": "pass"})
        return proj

    async def detail(inv):
        return J(await c.get(f"/finance/invoices/{inv}", headers=adm))

    async def lines(inv, items, who=None):
        return await c.patch(f"/finance/invoices/{inv}", headers=who or adm, json={"items": items})

    async def pdf_text(inv):
        r = await c.get(f"/finance/invoices/{inv}/pdf", headers=fin)
        if r.status_code != 200:
            return f"HTTP {r.status_code}"
        return "".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(r.content)).pages)

    def line(desc, qty, price, uom="pcs", sku=None):
        return {"description": desc, "qty": qty, "unit_price": price, "uom": uom, "sku": sku}

    # ══ a final invoice ══════════════════════════════════════════════════════
    print("\n── before anyone writes them ──")
    proj = await a_project("A")
    r = await c.post(f"/operation/projects/{proj}/issue-invoice", headers=adm,
                     data={"invoice_type": "final"})
    inv = J(r).get("invoice", {}).get("id")
    check("admin issues the invoice", r.status_code == 201 and bool(inv), f"{r.status_code} {J(r)}"[:200])
    v = await detail(inv)
    check("it hasn't been written yet", v.get("lines_typed") is False, str(v.get("lines_typed")))
    check("...so it shows the customer's PO lines it would print",
          any(f"P600 A {tag}" in (x.get("description") or "") for x in v.get("lines", [])),
          str(v.get("lines"))[:200])
    billed = float(v["amount"])
    check("...and bills Rp 1.000.000 off the quotation", billed == 1_000_000, str(billed))

    print("\n── writing them ──")
    r = await lines(inv, [line("Rantai roller RS80 & sprocket", 5, 100000)])
    check("lines that come to less than the bill are refused, saying by how much",
          r.status_code == 400 and "less than" in str(J(r)), f"{r.status_code} {J(r)}"[:200])
    r = await lines(inv, [line("", 10, 100000)])
    check("a line with no name is refused", r.status_code == 400 and "name" in str(J(r)),
          f"{r.status_code} {J(r)}"[:200])
    r = await lines(inv, [line("Rantai roller RS80", 10, 100000)], who=s1)
    check("sales can't write them", r.status_code == 403, str(r.status_code))
    r = await lines(inv, [line("Rantai roller RS80", 10, 100000)], who=pur)
    check("...nor purchasing", r.status_code == 403, str(r.status_code))

    named = [line(f"Rantai roller RS80 & sprocket {tag}", 8, 100000, "meter", "RC-80"),
             line(f"Ongkos pasang {tag}", 1, 200000, "lot")]
    r = await lines(inv, named)
    v = await detail(inv)
    check("admin writes them in the customer's names", r.status_code == 200
          and v.get("lines_typed") is True
          and v["lines"][0]["description"] == f"Rantai roller RS80 & sprocket {tag}",
          f"{r.status_code} {J(r)} {v.get('lines')}"[:240])
    check("...and they're kept as written — unit, code and all",
          v["lines"][0]["uom"] == "meter" and v["lines"][0]["sku"] == "RC-80"
          and v["lines"][1]["uom"] == "lot", str(v["lines"])[:200])

    print("\n── previewing it before finance signs ──")
    r = await c.get(f"/finance/invoices/{inv}/pdf", headers=adm)
    check("the real sheet still waits for finance", r.status_code == 409, str(r.status_code))
    r = await c.get(f"/finance/invoices/{inv}/pdf?draft=1", headers=adm)
    text = ("".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(r.content)).pages)
            if r.status_code == 200 else f"HTTP {r.status_code}")
    check("whoever issued it can preview it as a draft", r.status_code == 200
          and "DRAFT" in text and "NOT YET APPROVED" in text, text[:200])
    check("...showing the lines they wrote", f"Rantai roller RS80 & sprocket {tag}" in text, text[:300])
    check("...and named as a draft when saved", "DRAFT-" in r.headers.get("content-disposition", ""),
          r.headers.get("content-disposition", ""))
    v = await detail(inv)
    check("the invoice page offers the preview", v["may"].get("preview") is True
          and v["may"].get("download") is False, str(v["may"]))
    mgr = await login("manager@demo.local")
    r = await c.get(f"/finance/invoices/{inv}/pdf?draft=1", headers=mgr)
    check("the manager can look at it too", r.status_code == 200, str(r.status_code))
    r = await c.get(f"/finance/invoices/{inv}/pdf?draft=1", headers=s1)
    check("sales can't", r.status_code == 403, str(r.status_code))

    r = await c.patch(f"/finance/invoices/{inv}", headers=adm, json={"amount": 1_500_000})
    check("raising the amount past the lines is refused", r.status_code == 400
          and "less than" in str(J(r)), f"{r.status_code} {J(r)}"[:200])
    v = await detail(inv)
    check("...and nothing changed", float(v["amount"]) == 1_000_000, str(v["amount"]))

    r = await lines(inv, [])
    v = await detail(inv)
    check("clearing them goes back to the PO lines", r.status_code == 200
          and v.get("lines_typed") is False, f"{r.status_code} {v.get('lines_typed')}")

    over = [line(f"Rantai roller RS80 & sprocket {tag}", 12, 100000, "meter")]
    r = await lines(inv, over)
    check("lines worth more than the bill are allowed on a final invoice",
          r.status_code == 200, f"{r.status_code} {J(r)}"[:200])

    print("\n── what the customer gets ──")
    r = await c.post(f"/finance/invoices/{inv}/approve", headers=fin,
                     data={"faktur_pajak_no": ""})
    check("finance signs it off", r.status_code in (200, 201), f"{r.status_code} {J(r)}"[:200])
    text = await pdf_text(inv)
    check("the sheet prints the written name, '&' and all",
          f"Rantai roller RS80 & sprocket {tag}" in text, text[:300])
    check("...not the PO's technical name", f"P600 A {tag}" not in text)
    check("...and the extra Rp 200.000 as the discount",
          "POTONGAN HARGA" in text and "200.000" in text, text[-500:])
    r = await lines(inv, named)
    check("once signed off, the lines are fixed", r.status_code == 409, str(r.status_code))
    r = await c.get(f"/finance/invoices/{inv}/pdf?draft=1", headers=fin)
    text = "".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(r.content)).pages)
    check("...and asking for a draft of a signed invoice gets the real one, unstamped",
          r.status_code == 200 and "NOT YET APPROVED" not in text, text[:200])
    v = await detail(inv)
    check("...so the page offers the real sheet, not the preview",
          v["may"].get("preview") is False and v["may"].get("download") is True, str(v["may"]))

    # ══ a down payment ═══════════════════════════════════════════════════════
    print("\n── a down payment ──")
    proj = await a_project("B", qc=False)
    r = await c.post(f"/operation/projects/{proj}/issue-invoice", headers=adm,
                     data={"invoice_type": "dp", "amount": "300000"})
    dp = J(r).get("invoice", {}).get("id")
    check("a down-payment invoice is issued", r.status_code == 201 and bool(dp),
          f"{r.status_code} {J(r)}"[:200])
    r = await lines(dp, [line("Uang muka 30% rantai RS80", 1, 400000, "lot")])
    check("its lines must equal its amount — more is refused", r.status_code == 400
          and "down payment" in str(J(r)), f"{r.status_code} {J(r)}"[:200])
    r = await lines(dp, [line(f"Uang muka 30% rantai roller RS80 {tag}", 1, 300000, "lot")])
    check("...exact is fine", r.status_code == 200, f"{r.status_code} {J(r)}"[:200])
    await c.post(f"/finance/invoices/{dp}/approve", headers=fin, data={"faktur_pajak_no": ""})
    text = await pdf_text(dp)
    check("the down-payment sheet prints the written line, not the stock wording",
          f"Uang muka 30% rantai roller RS80 {tag}" in text
          and "Uang muka pekerjaan" not in text, text[:400])

    # ══ untouched invoices print as before ═══════════════════════════════════
    print("\n── an invoice nobody wrote lines for ──")
    proj = await a_project("C")
    r = await c.post(f"/operation/projects/{proj}/issue-invoice", headers=adm,
                     data={"invoice_type": "final"})
    plain = J(r).get("invoice", {}).get("id")
    await c.post(f"/finance/invoices/{plain}/approve", headers=fin, data={"faktur_pajak_no": ""})
    text = await pdf_text(plain)
    check("prints the customer's PO lines, as it always has", f"P600 C {tag}" in text, text[:300])

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

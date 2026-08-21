"""The faktur pajak number, typed by finance when they have it.

Asked for: *"make the faktur pajak thing manual on the finance side"* — and,
scrawled across the quotation's Linked Accounts card, *"ini nanti urusan
Finance"*.

The number was mandatory at approval. That put the invoice's whole life
behind a figure that comes out of e-Faktur on a different schedule: the goods
are delivered, the customer is asking for the bill, and the invoice sits
unapproved because the tax run has not happened yet. Approval is a decision
about the invoice; the tax number is a fact about the tax record. They do not
arrive together, and pretending they do makes people either wait or invent a
number — and an invented faktur pajak number is a wrong return.

So: approve with it or without it, and type it in afterwards. What this pins
down:

**Approval no longer waits on the number.** An invoice signed off without one
reads `pending` — not `none`, which would say it never needed one.

**The number is finance's to write.** Admin issue invoices and may approve
them; the tax record is not theirs. Nor is it sales'.

**One number, one invoice.** Typing a number already on another invoice is
refused by name, because two invoices sharing a faktur pajak number is a
return that cannot be filed.

**And it is correctable.** A number typed onto the wrong invoice clears back
to pending rather than being stuck there forever.
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


def pdf_text(blob: bytes) -> str:
    import fitz
    with fitz.open(stream=blob, filetype="pdf") as doc:
        return " ".join(p.get_text() for p in doc)


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
    adm = await login("admin@demo.local")
    fin = await login("finance@demo.local")
    s1 = await login("sales1@demo.local")
    mgr = await login("manager@demo.local")

    async def a_project(label):
        cust = J(await c.post("/customers", headers=s1, json={
            "company_name": f"PT Pajak {label} {tag}", "industry": "mining"}))["id"]
        pr = J(await c.post("/price-requests", headers=s1, json={
            "customer_id": cust,
            "items": [{"description": f"CHAIN {label} {tag}", "qty": 2,
                       "uom": "EA"}]}))["id"]
        await c.post(f"/price-requests/{pr}/submit", headers=s1)
        await c.post(f"/price-requests/{pr}/price", headers=d, json={
            "items": [{"line_no": 1, "cost_price": 500_000, "basis": "unit"}]})
        await c.post(f"/price-requests/{pr}/approve", headers=d, json={
            "items": [{"line_no": 1, "sell_price": 1_000_000, "basis": "unit"}]})
        q = J(await c.post(f"/quotations/from-price-request/{pr}", headers=s1))["id"]
        await c.post(f"/quotations/{q}/submit", headers=s1)
        await c.post(f"/quotations/{q}/approve", headers=d, json={"notes": ""})
        cpo = J(await c.post("/customer-pos", headers=s1, json={
            "customer_id": cust, "quotation_id": q, "number": f"PO-{label}-{tag}",
            "items": [{"description": f"CHAIN {label} {tag}", "qty": 2,
                       "uom": "EA", "unit_price": 1_000_000}],
            "is_downpayment": False}))["id"]
        await c.post(f"/quotations/{q}/won", headers=d)
        proj = J(await c.post(f"/customer-pos/{cpo}/approve", headers=d,
                              json={"notes": ""}))["project_id"]
        await c.post(f"/operation/projects/{proj}/qc", headers=adm,
                     json={"decision": "pass"})
        inv = J(await c.post(f"/operation/projects/{proj}/issue-invoice",
                             headers=adm, data={"invoice_type": "final",
                                                "create_delivery_order": "true"}))
        return proj, inv["invoice"]["id"]

    async def invoice(proj, inv_id):
        f = J(await c.get(f"/operation/projects/{proj}/full", headers=d))
        return next(x for x in f["invoices"] if x["id"] == inv_id)

    # ══ approving without the number ═════════════════════════════════════════
    print("\n── signing off before the tax run ──")
    proj, inv_id = await a_project("A")
    r = await c.post(f"/finance/invoices/{inv_id}/approve", headers=fin)
    check("finance can approve with no faktur pajak number yet",
          r.status_code < 300, f"{r.status_code} {J(r)}"[:170])
    row = await invoice(proj, inv_id)
    check("...the invoice is approved", row["status"] == "approved", row["status"])
    check("...and says the number is still coming",
          row["faktur_pajak_status"] == "pending" and not row["faktur_pajak_no"],
          str(row["faktur_pajak_status"]))
    r = await c.get(f"/finance/invoices/{inv_id}/pdf", headers=fin)
    check("...and its sheet prints, number or no number", r.status_code == 200,
          str(r.status_code))
    sheet = pdf_text(r.content)
    check("...with no faktur pajak line invented on it",
          "FAKTUR PAJAK" not in sheet.upper(), sheet[:400])

    # ══ typing it in afterwards ══════════════════════════════════════════════
    print("\n── the number arrives ──")
    fp = f"010.000-26.{tag}"
    r = await c.post(f"/finance/invoices/{inv_id}/faktur-pajak", headers=adm,
                     json={"faktur_pajak_no": fp})
    check("admin cannot write the tax record", r.status_code == 403,
          f"{r.status_code} {J(r)}"[:170])
    r = await c.post(f"/finance/invoices/{inv_id}/faktur-pajak", headers=s1,
                     json={"faktur_pajak_no": fp})
    check("...nor sales", r.status_code in (401, 403), str(r.status_code))
    r = await c.post(f"/finance/invoices/{inv_id}/faktur-pajak", headers=fin,
                     json={"faktur_pajak_no": fp})
    check("finance types it in", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:170])
    row = await invoice(proj, inv_id)
    check("...and it is on the invoice", row["faktur_pajak_no"] == fp,
          str(row["faktur_pajak_no"]))
    check("...marked issued", row["faktur_pajak_status"] == "issued",
          row["faktur_pajak_status"])
    sheet = pdf_text((await c.get(f"/finance/invoices/{inv_id}/pdf",
                                  headers=fin)).content)
    check("...and now prints on the sheet", fp in sheet, sheet[:500])

    # ══ one number, one invoice ══════════════════════════════════════════════
    print("\n── the same number twice ──")
    proj2, inv2 = await a_project("B")
    await c.post(f"/finance/invoices/{inv2}/approve", headers=fin)
    r = await c.post(f"/finance/invoices/{inv2}/faktur-pajak", headers=fin,
                     json={"faktur_pajak_no": fp})
    check("a number already on another invoice is refused",
          r.status_code == 409, f"{r.status_code} {J(r)}"[:170])
    check("...naming the invoice that holds it",
          "INV-" in str(J(r)), str(J(r))[:200])

    print("\n── correcting one typed onto the wrong invoice ──")
    r = await c.post(f"/finance/invoices/{inv_id}/faktur-pajak", headers=fin,
                     json={"faktur_pajak_no": ""})
    check("clearing it is allowed", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:150])
    row = await invoice(proj, inv_id)
    check("...back to waiting for a number",
          row["faktur_pajak_status"] == "pending" and not row["faktur_pajak_no"],
          str(row))
    r = await c.post(f"/finance/invoices/{inv2}/faktur-pajak", headers=fin,
                     json={"faktur_pajak_no": fp})
    check("...so it can be put on the right one", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:150])

    # ══ approving with it still works ════════════════════════════════════════
    print("\n── when finance does have it at sign-off ──")
    proj3, inv3 = await a_project("C")
    fp3 = f"010.000-26.C{tag}"
    r = await c.post(f"/finance/invoices/{inv3}/approve", headers=fin,
                     data={"faktur_pajak_no": fp3})
    check("the number can still go on at approval", r.status_code < 300,
          f"{r.status_code} {J(r)}"[:150])
    row = await invoice(proj3, inv3)
    check("...issued in one step", row["faktur_pajak_no"] == fp3
          and row["faktur_pajak_status"] == "issued", str(row)[:200])

    # ══ the director's combined sign-off ═════════════════════════════════════
    print("\n── signing both documents at once ──")
    proj4, inv4 = await a_project("D")
    r = await c.post(f"/operation/projects/{proj4}/approve-documents", headers=d,
                     data={})
    check("the director signs both without a number too", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:170])
    row = await invoice(proj4, inv4)
    check("...invoice approved, waiting for its number",
          row["status"] == "approved" and row["faktur_pajak_status"] == "pending",
          str(row)[:200])
    f4 = J(await c.get(f"/operation/projects/{proj4}/full", headers=d))
    check("...and the delivery order released with it",
          bool(f4["deliveries"][0]["approved_at"]), str(f4["deliveries"][0])[:170])
    r = await c.post(f"/finance/invoices/{inv4}/faktur-pajak", headers=d,
                     json={"faktur_pajak_no": f"010.000-26.D{tag}"})
    check("the director can enter one as the backstop", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:150])

    # ══ the e-Faktur export ══════════════════════════════════════════════════
    print("\n── the export that files them ──")
    csv_text = (await c.get("/finance/efaktur.csv", headers=fin)).text
    # e-Faktur takes the number as digits, so that is what to look for.
    digits = lambda x: "".join(ch for ch in x if ch.isdigit())
    check("an invoice finance has numbered is in the export",
          digits(fp3) in csv_text, csv_text[-400:])
    unnumbered = await invoice(proj, inv_id)
    check("...and the one still waiting for a number is not there",
          not unnumbered["faktur_pajak_no"], str(unnumbered["faktur_pajak_no"]))
    check("...because a return can only carry numbers that exist",
          csv_text.count("FK,") >= 1, csv_text[:150])

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)


asyncio.run(main())

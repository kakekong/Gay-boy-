"""Fixing a delivery order or an invoice before anyone has signed it off.

Asked for, written across a project page showing two identical DOs and two
identical invoices: *"sebelum di approve bisa edit dan hapus"* — before it is
approved, it should be editable and deletable.

Both documents come out of one button. Admin press "Issue invoice + DO" on
the project and the pair is created together, numbered off a counter, with
the amount defaulted from the quotation. Press it twice — which is exactly
what happens when the first press seems not to have worked — and the project
carries a duplicate invoice asking the customer for the money a second time,
and a duplicate shipment that will sit there forever asking for proof and
keeping the project from ever reading as delivered.

There was no way back from either. An invoice could be deleted, but only by
finance, so admin had to queue for someone else to remove a document that
someone else never wanted. A delivery order could not be touched at all.
Nothing could be corrected in place: a due date agreed on the phone, tax the
customer is exempt from, a courier typed wrong.

The line this draws is *signed off*, not *created*:

**A delivery order is ours until the director verifies its proof.** After
that the verification is a decision about a specific document, and silently
renumbering it underneath would make that decision a lie. Uploading new
proof is the legitimate way through — that withdraws the verification.

**An invoice is ours until finance approves it.** After that it carries a
faktur pajak number and the tax record refers to it; a correction is a
credit note, not an edit. Verified payments stop both edit and delete
whatever the status, because the ledger is already pointing at the figure.

**Admin may withdraw what they issued, not what finance approved.** Deleting
their own pending duplicate is tidying up after themselves. An approved
invoice stays finance's and the director's to remove.

**The money is edited in its two halves.** The e-Faktur export files the DPP
and the PPN separately, so the total is recomputed from them rather than
typed — a total that is not the sum of its parts files a return that does
not add up.
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

PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>"


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
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

    async def a_project(label):
        cust = J(await c.post("/customers", headers=s1, json={
            "company_name": f"PT Ubah {label} {tag}", "industry": "mining"}))["id"]
        pr = J(await c.post("/price-requests", headers=s1, json={
            "customer_id": cust,
            "items": [{"description": f"WIDGET {label} {tag}", "qty": 10,
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
            "items": [{"description": f"WIDGET {label} {tag}", "qty": 10,
                       "unit_price": 100000}],
            "is_downpayment": False}))["id"]
        await c.post(f"/quotations/{q}/won", headers=d)
        proj = J(await c.post(f"/customer-pos/{cpo}/approve", headers=d,
                              json={"notes": ""}))["project_id"]
        await c.post(f"/operation/projects/{proj}/qc", headers=adm,
                     json={"decision": "pass"})
        return proj

    async def full(proj, headers=None):
        return J(await c.get(f"/operation/projects/{proj}/full",
                             headers=headers or d))

    proj = await a_project("A")

    # ══ the double press ═════════════════════════════════════════════════════
    print("\n── admin presses Issue twice ──")
    first = J(await c.post(f"/operation/projects/{proj}/issue-invoice",
                           headers=adm, data={"invoice_type": "final"}))
    second = J(await c.post(f"/operation/projects/{proj}/issue-invoice",
                            headers=adm, data={"invoice_type": "final"}))
    f0 = await full(proj)
    check("the project now carries two invoices", len(f0["invoices"]) == 2,
          str(len(f0["invoices"])))
    # The shipment is no longer duplicated by a second press: the invoice now
    # bills against the delivery order already on the project rather than
    # raising another one. A real second shipment is raised deliberately.
    check("...but only one shipment — the second bill went on the first DO",
          len(f0["deliveries"]) == 1, str(len(f0["deliveries"])))
    check("...asking for the same money twice",
          f0["invoices"][0]["total"] == f0["invoices"][1]["total"],
          str([i["total"] for i in f0["invoices"]]))
    dupe_inv = second["invoice"]["id"]
    keep_inv = first["invoice"]["id"]
    keep_do = first["delivery_order"]["id"]
    # A genuine second shipment, raised on purpose — this is the duplicate
    # the rest of the checks withdraw.
    dupe_do = J(await c.post(f"/operation/projects/{proj}/delivery-order",
                             headers=adm))["delivery_order"]["id"]
    check("a second shipment can still be raised deliberately",
          len((await full(proj))["deliveries"]) == 2,
          str(len((await full(proj))["deliveries"])))

    # ══ correcting the delivery order ════════════════════════════════════════
    print("\n── correcting the delivery order that stays ──")
    r = await c.patch(f"/operation/deliveries/{keep_do}", headers=adm, json={
        "number": f"DO-MANUAL-{tag}", "split_index": 2,
        "courier": "JNE Trucking", "tracking_no": f"JNE{tag}"})
    check("admin can correct number, split, courier and tracking",
          r.status_code == 200, f"{r.status_code} {J(r)}"[:170])
    row = next(x for x in (await full(proj))["deliveries"] if x["id"] == keep_do)
    check("...and every one of them stuck",
          row["number"] == f"DO-MANUAL-{tag}" and row["split_index"] == 2
          and row["courier"] == "JNE Trucking" and row["tracking_no"] == f"JNE{tag}",
          str(row))
    r = await c.patch(f"/operation/deliveries/{dupe_do}", headers=adm,
                      json={"number": f"DO-MANUAL-{tag}"})
    check("a number another DO holds is refused", r.status_code == 409,
          f"{r.status_code} {J(r)}"[:150])
    r = await c.patch(f"/operation/deliveries/{keep_do}", headers=adm,
                      json={"number": "  "})
    check("...and so is an empty one", r.status_code == 400,
          f"{r.status_code} {J(r)}"[:150])
    r = await c.patch(f"/operation/deliveries/{keep_do}", headers=adm,
                      json={"split_index": 0})
    check("...and a split that starts below 1", r.status_code == 400,
          f"{r.status_code} {J(r)}"[:150])
    r = await c.patch(f"/operation/deliveries/{keep_do}", headers=adm,
                      json={"courier": "   "})
    check("clearing the courier empties it rather than storing blanks",
          r.status_code == 200 and J(r)["courier"] is None, str(J(r))[:150])

    # ══ withdrawing the duplicate ════════════════════════════════════════════
    print("\n── withdrawing the duplicate shipment ──")
    r = await c.post(f"/attachments", headers=adm,
                     data={"owner_type": "delivery_order", "owner_id": dupe_do},
                     files={"file": (f"slip-{tag}.pdf", io.BytesIO(PDF), "application/pdf")})
    att = J(r).get("id")
    check("a file filed against the duplicate", r.status_code in (200, 201), J(r))
    r = await c.delete(f"/operation/deliveries/{dupe_do}", headers=adm)
    check("admin can withdraw it", r.status_code == 204,
          f"{r.status_code} {J(r)}"[:150])
    f1 = await full(proj)
    check("...leaving one shipment on the project", len(f1["deliveries"]) == 1,
          str([x["number"] for x in f1["deliveries"]]))
    check("...and the file that hung off it is gone too",
          (await c.get(f"/attachments/{att}/download", headers=d)).status_code == 404,
          "still downloadable")
    r = await c.delete(f"/operation/deliveries/{dupe_do}", headers=adm)
    check("withdrawing it twice says not found", r.status_code == 404,
          str(r.status_code))

    # ══ once it is signed off ════════════════════════════════════════════════
    print("\n── once the director has verified it ──")
    await c.post(f"/operation/deliveries/{keep_do}/proof", headers=adm,
                 files={"file": (f"pod-{tag}.pdf", io.BytesIO(PDF), "application/pdf")})
    await c.post(f"/operation/deliveries/{keep_do}/verify", headers=d)
    r = await c.patch(f"/operation/deliveries/{keep_do}", headers=adm,
                      json={"courier": "Someone else"})
    check("editing a verified DO is refused", r.status_code == 409,
          f"{r.status_code} {J(r)}"[:150])
    check("...and says how to do it properly — new proof",
          "proof" in str(J(r)).lower(), str(J(r))[:200])
    r = await c.delete(f"/operation/deliveries/{keep_do}", headers=adm)
    check("deleting it is refused too", r.status_code == 409,
          f"{r.status_code} {J(r)}"[:150])
    # New proof withdraws the verification, and with it the lock.
    await c.post(f"/operation/deliveries/{keep_do}/proof", headers=adm,
                 files={"file": (f"pod2-{tag}.pdf", io.BytesIO(PDF), "application/pdf")})
    r = await c.patch(f"/operation/deliveries/{keep_do}", headers=adm,
                      json={"courier": "JNE Trucking"})
    check("re-uploading proof reopens it, as the message said",
          r.status_code == 200, f"{r.status_code} {J(r)}"[:150])

    # ══ who may ══════════════════════════════════════════════════════════════
    print("\n── who may touch a delivery order ──")
    for who, hdr in (("sales", s1), ("purchasing", pur), ("finance", fin)):
        r = await c.patch(f"/operation/deliveries/{keep_do}", headers=hdr,
                          json={"courier": "nope"})
        check(f"{who} cannot edit one", r.status_code in (401, 403),
              str(r.status_code))
    r = await c.delete(f"/operation/deliveries/{keep_do}", headers=s1)
    check("...nor delete one", r.status_code in (401, 403), str(r.status_code))
    r = await c.patch(f"/operation/deliveries/{keep_do}", headers=d,
                      json={"courier": "JNE Trucking"})
    check("the director can", r.status_code == 200, str(r.status_code))

    # ══ correcting the invoice ═══════════════════════════════════════════════
    print("\n── correcting the invoice ──")
    inv0 = next(x for x in (await full(proj))["invoices"] if x["id"] == keep_inv)
    check("it defaulted to the quotation's figure", inv0["total"] > 0,
          str(inv0["total"]))
    r = await c.patch(f"/finance/invoices/{keep_inv}", headers=adm, json={
        "number": f"INV-MANUAL-{tag}", "due_date": "2026-09-30",
        "amount": 900000, "tax_amount": 99000})
    check("admin can correct number, due date and both halves of the money",
          r.status_code == 200, f"{r.status_code} {J(r)}"[:170])
    check("...and the total is recomputed, not taken on trust",
          float(J(r)["total"]) == 999000.0, str(J(r).get("total")))
    inv1 = next(x for x in (await full(proj))["invoices"] if x["id"] == keep_inv)
    check("...as the project page reads it back",
          inv1["number"] == f"INV-MANUAL-{tag}"
          and inv1["due_date"] == "2026-09-30"
          and inv1["total"] == 999000.0, str(inv1)[:200])
    r = await c.patch(f"/finance/invoices/{dupe_inv}", headers=adm,
                      json={"number": f"INV-MANUAL-{tag}"})
    check("a number another invoice holds is refused", r.status_code == 409,
          f"{r.status_code} {J(r)}"[:150])
    r = await c.patch(f"/finance/invoices/{keep_inv}", headers=adm,
                      json={"amount": -5})
    check("...and a negative figure", r.status_code == 400,
          f"{r.status_code} {J(r)}"[:150])
    r = await c.patch(f"/finance/invoices/{keep_inv}", headers=fin,
                      json={"due_date": "2026-10-15"})
    check("finance can correct one too", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:150])
    for who, hdr in (("sales", s1), ("purchasing", pur)):
        r = await c.patch(f"/finance/invoices/{keep_inv}", headers=hdr,
                          json={"due_date": "2026-12-01"})
        check(f"{who} cannot", r.status_code in (401, 403), str(r.status_code))

    # ══ withdrawing the duplicate invoice ════════════════════════════════════
    print("\n── withdrawing the duplicate invoice ──")
    r = await c.delete(f"/finance/invoices/{dupe_inv}", headers=adm)
    check("admin can withdraw the one they issued by mistake",
          r.status_code == 204, f"{r.status_code} {J(r)}"[:150])
    check("...leaving one invoice on the project",
          len((await full(proj))["invoices"]) == 1,
          str([i["number"] for i in (await full(proj))["invoices"]]))

    # ══ once finance has signed it ═══════════════════════════════════════════
    print("\n── once finance has approved it ──")
    r = await c.post(f"/finance/invoices/{keep_inv}/approve", headers=fin,
                     data={"faktur_pajak_no": f"FP-{tag}"})
    check("finance approves it with a faktur pajak number", r.status_code < 300,
          f"{r.status_code} {J(r)}"[:150])
    r = await c.patch(f"/finance/invoices/{keep_inv}", headers=adm,
                      json={"amount": 1})
    check("editing it afterwards is refused", r.status_code == 409,
          f"{r.status_code} {J(r)}"[:150])
    check("...and names the reason — the tax record points at it",
          "faktur pajak" in str(J(r)).lower(), str(J(r))[:200])
    r = await c.patch(f"/finance/invoices/{keep_inv}", headers=fin,
                      json={"due_date": "2026-11-01"})
    check("...for finance as much as for admin", r.status_code == 409,
          f"{r.status_code} {J(r)}"[:150])
    r = await c.delete(f"/finance/invoices/{keep_inv}", headers=adm)
    check("and admin can no longer delete it", r.status_code == 403,
          f"{r.status_code} {J(r)}"[:150])

    # ══ money already banked ═════════════════════════════════════════════════
    print("\n── an invoice with money against it ──")
    proj2 = await a_project("B")
    paid = J(await c.post(f"/operation/projects/{proj2}/issue-invoice",
                          headers=adm, data={"invoice_type": "final"}))["invoice"]["id"]
    await c.post(f"/finance/invoices/{paid}/approve", headers=fin,
                 data={"faktur_pajak_no": f"FP2-{tag}"})
    r = await c.post("/payments/manual", headers=fin, json={
        "invoice_id": paid, "amount": 250000, "method": "transfer",
        "reference": f"PAY-{tag}"})
    check("finance banks a part payment", r.status_code == 201,
          f"{r.status_code} {J(r)}"[:150])
    r = await c.delete(f"/finance/invoices/{paid}", headers=fin)
    check("even finance cannot delete an invoice with money against it",
          r.status_code == 409, f"{r.status_code} {J(r)}"[:150])
    r = await c.patch(f"/finance/invoices/{paid}", headers=fin,
                      json={"amount": 1})
    check("...nor edit it — the status alone would already have stopped this",
          r.status_code == 409, f"{r.status_code} {J(r)}"[:150])

    # ══ the duplicate is gone for good ═══════════════════════════════════════
    print("\n── nothing left behind ──")
    r = await c.patch(f"/finance/invoices/{dupe_inv}", headers=adm,
                      json={"due_date": "2026-12-31"})
    check("the withdrawn invoice is not editable — it is not there",
          r.status_code == 404, str(r.status_code))
    r = await c.get(f"/operation/projects/{proj}/full", headers=adm)
    check("the project page loads cleanly with the survivors",
          r.status_code == 200 and len(J(r)["deliveries"]) == 1
          and len(J(r)["invoices"]) == 1,
          f"{r.status_code} {len(J(r).get('deliveries', []))}/{len(J(r).get('invoices', []))}")

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)


asyncio.run(main())

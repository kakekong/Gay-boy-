"""Which document comes first, and who signs which.

Asked for: the delivery order first, then the invoice; the invoice signed by
finance and the delivery order by the director; and an option to do both at
once, signed by the director.

The order is not bureaucracy. You bill for goods you have sent, so a final
invoice on a project with no delivery order is a bill for nothing
identifiable — and when the customer's accounts department queries it, the DO
number is the thing that answers them. The signatures are not bureaucracy
either: the delivery order says goods in this condition left our building,
which is the director's to say, and the invoice carries a faktur pajak number
into the tax record, which is finance's.

The exception, and it is a real one: a **down-payment** invoice is billed
before delivery by definition. Nothing has gone out, so there is no delivery
order for it to follow, and requiring one would make the deposit unbillable.

And the shortcut: on a small order, two documents needing two people is two
people waiting on each other over a decision neither disagrees with. The
director outranks both signatures, so they can give both in one action —
director-only, because finance signing the delivery order, or admin signing
either, is a person approving their own paperwork.

One thing that fell out of putting the delivery order first: pressing Issue
twice no longer duplicates the shipment. The second press bills against the
delivery order already on the project instead of raising another one, which
is what the duplicate rows on the screenshot that started all this were. A
genuine second shipment is now raised deliberately, which is the only time
anybody wants one.
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

    async def a_project(label, *, qc=True):
        cust = J(await c.post("/customers", headers=s1, json={
            "company_name": f"PT Urutan {label} {tag}", "industry": "mining",
            "delivery_address": "SITE, KALIMANTAN SELATAN"}))["id"]
        pr = J(await c.post("/price-requests", headers=s1, json={
            "customer_id": cust,
            "items": [{"description": f"CHAIN {label} {tag}", "qty": 4,
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
            "items": [{"description": f"CHAIN {label} {tag}", "qty": 4,
                       "uom": "EA", "unit_price": 1_000_000}],
            "is_downpayment": False}))["id"]
        await c.post(f"/quotations/{q}/won", headers=d)
        proj = J(await c.post(f"/customer-pos/{cpo}/approve", headers=d,
                              json={"notes": ""}))["project_id"]
        if qc:
            await c.post(f"/operation/projects/{proj}/qc", headers=adm,
                         json={"decision": "pass"})
        return proj

    async def full(proj):
        return J(await c.get(f"/operation/projects/{proj}/full", headers=d))

    # ══ the delivery order comes first ═══════════════════════════════════════
    print("\n── billing before anything has gone out ──")
    p1 = await a_project("A")
    r = await c.post(f"/operation/projects/{p1}/issue-invoice", headers=adm,
                     data={"invoice_type": "final", "create_delivery_order": "false"})
    check("a final invoice with no delivery order is refused",
          r.status_code == 409, f"{r.status_code} {J(r)}"[:170])
    check("...and says which document comes first",
          "delivery order first" in str(J(r)).lower(), str(J(r))[:200])
    check("nothing was filed by the attempt",
          not (await full(p1))["invoices"] and not (await full(p1))["deliveries"],
          str((await full(p1))["invoices"]))

    print("\n── the delivery order, on its own ──")
    r = await c.post(f"/operation/projects/{p1}/delivery-order", headers=adm)
    check("admin raises it alone", r.status_code == 201,
          f"{r.status_code} {J(r)}"[:170])
    do1 = J(r)["delivery_order"]
    check("...with the goods already on it",
          len(do1["items"]) == 1 and "CHAIN" in str(do1["items"][0]["description"]),
          str(do1["items"])[:170])
    check("...and the site address for the printed remarks",
          "KALIMANTAN" in (do1["remarks"] or ""), str(do1["remarks"]))
    check("...and no invoice yet", not (await full(p1))["invoices"],
          str((await full(p1))["invoices"]))

    r = await c.post(f"/operation/projects/{p1}/issue-invoice", headers=adm,
                     data={"invoice_type": "final", "create_delivery_order": "false"})
    check("now the invoice may follow", r.status_code == 201,
          f"{r.status_code} {J(r)}"[:170])
    f1 = await full(p1)
    check("...one shipment, one bill",
          len(f1["deliveries"]) == 1 and len(f1["invoices"]) == 1,
          f"{len(f1['deliveries'])}/{len(f1['invoices'])}")
    inv1 = f1["invoices"][0]["id"]

    print("\n── who signs which ──")
    r = await c.post(f"/operation/deliveries/{do1['id']}/approve", headers=fin)
    check("finance cannot release the delivery order", r.status_code == 403,
          str(r.status_code))
    r = await c.post(f"/finance/invoices/{inv1}/approve", headers=fin,
                     data={"faktur_pajak_no": f"010.000-26.{tag}"})
    check("finance signs the invoice", r.status_code < 300,
          f"{r.status_code} {J(r)}"[:150])
    r = await c.post(f"/operation/deliveries/{do1['id']}/approve", headers=d)
    check("the director releases the delivery order", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:150])
    check("...and each document knows who signed it",
          (await full(p1))["deliveries"][0]["approved_by_name"] is not None,
          str((await full(p1))["deliveries"][0])[:200])

    # ══ the down-payment exception ═══════════════════════════════════════════
    print("\n── a deposit, billed before delivery ──")
    p2 = await a_project("B", qc=False)
    r = await c.post(f"/operation/projects/{p2}/issue-invoice", headers=adm,
                     data={"invoice_type": "dp", "amount": 400_000})
    check("a DP invoice needs no delivery order — nothing has gone out yet",
          r.status_code == 201, f"{r.status_code} {J(r)}"[:170])
    f2 = await full(p2)
    check("...and none was raised for it", not f2["deliveries"],
          str(f2["deliveries"]))
    check("...just the deposit to bill", len(f2["invoices"]) == 1,
          str(len(f2["invoices"])))

    # ══ both at once ═════════════════════════════════════════════════════════
    print("\n── both in one press ──")
    p3 = await a_project("C")
    r = await c.post(f"/operation/projects/{p3}/issue-invoice", headers=adm,
                     data={"invoice_type": "final", "create_delivery_order": "true"})
    check("one press still files the pair", r.status_code == 201,
          f"{r.status_code} {J(r)}"[:170])
    both = J(r)
    check("...and hands back both documents",
          both["invoice"]["id"] and both["delivery_order"]["id"], str(both)[:200])
    f3 = await full(p3)
    check("...the delivery order first, by its own timestamp",
          f3["deliveries"][0]["id"] == both["delivery_order"]["id"],
          str(f3["deliveries"])[:150])

    r = await c.post(f"/operation/projects/{p3}/issue-invoice", headers=adm,
                     data={"invoice_type": "final", "create_delivery_order": "true"})
    f3 = await full(p3)
    check("pressing it twice no longer duplicates the shipment",
          len(f3["deliveries"]) == 1, str(len(f3["deliveries"])))
    check("...though it does bill twice, which is deletable",
          len(f3["invoices"]) == 2, str(len(f3["invoices"])))
    dupe = J(r)["invoice"]["id"]
    await c.delete(f"/finance/invoices/{dupe}", headers=adm)

    print("\n── the director signs both at once ──")
    fp3 = f"010.000-26.C{tag}"
    r = await c.post(f"/operation/projects/{p3}/approve-documents", headers=fin,
                     data={"faktur_pajak_no": fp3})
    check("finance cannot sign both", r.status_code == 403,
          f"{r.status_code} {J(r)}"[:170])
    r = await c.post(f"/operation/projects/{p3}/approve-documents", headers=adm,
                     data={"faktur_pajak_no": fp3})
    check("...nor admin, on their own paperwork", r.status_code == 403,
          str(r.status_code))
    r = await c.post(f"/operation/projects/{p3}/approve-documents", headers=mgr,
                     data={"faktur_pajak_no": fp3})
    check("...nor a manager", r.status_code == 403, str(r.status_code))
    # The faktur pajak number is finance's, entered when e-Faktur produces it
    # (see test_faktur_pajak_manual), so it does not hold up this signature.
    r = await c.post(f"/operation/projects/{p3}/approve-documents", headers=d,
                     data={"faktur_pajak_no": fp3})
    check("the director signs both in one action", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:170])
    done = J(r)
    check("...naming what it signed",
          len(done["delivery_orders"]) == 1 and len(done["invoices"]) == 1,
          str(done))
    f3 = await full(p3)
    check("the delivery order is released", f3["deliveries"][0]["approved_at"],
          str(f3["deliveries"][0])[:170])
    check("...the invoice approved with that number",
          f3["invoices"][0]["status"] == "approved"
          and f3["invoices"][0]["faktur_pajak_no"] == fp3,
          str(f3["invoices"][0])[:200])
    check("...and both sheets now print",
          (await c.get(f"/operation/deliveries/{f3['deliveries'][0]['id']}/pdf",
                       headers=adm)).status_code == 200
          and (await c.get(f"/finance/invoices/{f3['invoices'][0]['id']}/pdf",
                           headers=adm)).status_code == 200,
          "one of them refused")
    r = await c.post(f"/operation/projects/{p3}/approve-documents", headers=d,
                     data={"faktur_pajak_no": fp3})
    check("signing again says there is nothing left waiting",
          r.status_code == 409, f"{r.status_code} {J(r)}"[:150])

    # An already-signed document is not re-stamped by the combined press.
    print("\n── what is already signed stays signed ──")
    p4 = await a_project("D")
    both4 = J(await c.post(f"/operation/projects/{p4}/issue-invoice", headers=adm,
                           data={"invoice_type": "final",
                                 "create_delivery_order": "true"}))
    await c.post(f"/finance/invoices/{both4['invoice']['id']}/approve", headers=fin,
                 data={"faktur_pajak_no": f"010.000-26.D{tag}"})
    r = await c.post(f"/operation/projects/{p4}/approve-documents", headers=d,
                     data={"faktur_pajak_no": f"010.000-26.DD{tag}"})
    check("the combined press signs only what was still waiting",
          r.status_code == 200 and J(r)["invoices"] == []
          and len(J(r)["delivery_orders"]) == 1, f"{r.status_code} {J(r)}"[:200])
    inv4 = (await full(p4))["invoices"][0]
    check("...leaving finance's faktur pajak number as finance wrote it",
          inv4["faktur_pajak_no"] == f"010.000-26.D{tag}",
          str(inv4["faktur_pajak_no"]))

    # ══ the delivery order as a document somebody fills in ═══════════════════
    print("\n── making one, the way a quotation or a PO is made ──")
    p6 = await a_project("F")
    r = await c.get(f"/operation/projects/{p6}/delivery-order/prefill", headers=adm)
    check("the form arrives prefilled from the customer's order",
          r.status_code == 200 and len(J(r)["items"]) == 1,
          f"{r.status_code} {J(r)}"[:200])
    pre = J(r)
    line = pre["items"][0]
    check("...with what was ordered and what is left to send",
          line["qty_ordered"] == 4.0 and line["qty_sent"] == 0.0
          and line["qty"] == 4.0, str(line))
    check("...a number off the counter, ready to be overtyped",
          pre["suggested_number"].startswith("DO-"), pre["suggested_number"])
    check("...and where the customer takes deliveries",
          "KALIMANTAN" in (pre["remarks"] or ""), str(pre["remarks"]))

    # Half now — the reason the lines are editable at all.
    r = await c.post(f"/operation/projects/{p6}/delivery-order", headers=adm, json={
        "number": f"SJ-MANUAL-{tag}", "split_index": 1,
        "courier": "JNE Trucking", "tracking_no": f"JNE{tag}",
        "remarks": "BARANG DI KIRIM KE: GUDANG SITE",
        "items": [{"description": line["description"], "qty": 2,
                   "uom": line["uom"]}]})
    check("a part shipment can be written down as one", r.status_code == 201,
          f"{r.status_code} {J(r)}"[:200])
    made = J(r)["delivery_order"]
    check("...under the number that was typed", made["number"] == f"SJ-MANUAL-{tag}",
          made["number"])
    check("...carrying two of the four", float(made["items"][0]["qty"]) == 2.0,
          str(made["items"]))
    check("...with the courier and resi on it",
          made["courier"] == "JNE Trucking" and made["tracking_no"] == f"JNE{tag}",
          str(made))
    check("...and the site it is going to", "GUDANG SITE" in (made["remarks"] or ""),
          str(made["remarks"]))

    r = await c.get(f"/operation/projects/{p6}/delivery-order/prefill", headers=adm)
    line2 = J(r)["items"][0]
    check("the next sheet knows two already went",
          line2["qty_sent"] == 2.0 and line2["qty"] == 2.0, str(line2))
    check("...and says which sheet took them",
          line2["sent_on"] == [f"SJ-MANUAL-{tag}"], str(line2["sent_on"]))
    check("...and offers the next split number",
          J(r)["suggested_split"] == 2, str(J(r)["suggested_split"]))

    r = await c.post(f"/operation/projects/{p6}/delivery-order", headers=adm, json={
        "number": f"SJ-MANUAL-{tag}", "items": [
            {"description": line["description"], "qty": 2, "uom": line["uom"]}]})
    check("a number another sheet holds is refused", r.status_code == 409,
          f"{r.status_code} {J(r)}"[:170])
    r = await c.post(f"/operation/projects/{p6}/delivery-order", headers=adm,
                     json={"items": []})
    check("...and a sheet with nothing on it", r.status_code == 400,
          f"{r.status_code} {J(r)}"[:170])
    r = await c.post(f"/operation/projects/{p6}/delivery-order", headers=adm,
                     json={"items": [{"description": "X", "qty": 0, "uom": "EA"}]})
    check("...as is one whose only line ships nothing", r.status_code == 400,
          f"{r.status_code} {J(r)}"[:170])

    r = await c.post(f"/operation/projects/{p6}/delivery-order", headers=adm, json={
        "split_index": 2,
        "items": [{"description": line["description"], "qty": 2,
                   "uom": line["uom"]}]})
    check("the rest goes out on a second sheet", r.status_code == 201,
          f"{r.status_code} {J(r)}"[:170])
    check("...numbered off the counter when nobody types one",
          J(r)["delivery_order"]["number"].startswith("DO-"),
          J(r)["delivery_order"]["number"])
    f6 = await full(p6)
    check("...leaving the project with two shipments", len(f6["deliveries"]) == 2,
          str([x["number"] for x in f6["deliveries"]]))
    check("...and nothing left to send",
          J(await c.get(f"/operation/projects/{p6}/delivery-order/prefill",
                        headers=adm))["items"][0]["qty"] == 0.0,
          "still says there is more")

    # ══ QC still gates the delivery order ════════════════════════════════════
    print("\n── before QC ──")
    p5 = await a_project("E", qc=False)
    r = await c.post(f"/operation/projects/{p5}/delivery-order", headers=adm)
    check("no delivery order before QC has passed", r.status_code == 409,
          f"{r.status_code} {J(r)}"[:170])
    r = await c.post(f"/operation/projects/{p5}/delivery-order", headers=s1)
    check("...and sales never raises one", r.status_code in (401, 403),
          str(r.status_code))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)


asyncio.run(main())

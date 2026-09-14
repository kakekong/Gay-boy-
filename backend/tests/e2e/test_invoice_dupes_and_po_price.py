"""One press, one bill — and finance may fix a price that was typed wrong.

**The duplicates.** Two invoices, same project, same amount, both approved,
sitting on the screen one above the other. The delivery order had already been
taught not to duplicate itself — a second press bills against the sheet that
exists — but nothing ever taught the invoice, so pressing Issue twice produced
two real documents for one shipment. Both can be approved, and a customer can
end up with two bills for the same goods.

A genuine second invoice is a real thing: a part shipment billed on its own, a
staged instalment. So this refuses the *repeat*, not the idea — `additional`
says "I mean another one", which a double-click never does.

The same hole was on the deposit route, where a DP invoice is issued against
the customer PO before any project exists, and it is closed the same way.

**And the faktur pajak number.** Setting one through `POST /faktur-pajak` has
always refused a number already on another invoice. Approving *with* a number
never checked — and on a pair of duplicates, approving is exactly the door
people use, so the same tax number could be signed onto both.

**The PO price.** Finance could set the exchange rate on a supplier PO and
nothing else. They are the desk that reads the vendor's invoice when it lands,
so they are who finds out the agreed figure was typed wrong — and sending that
back through purchasing to retype added a day and a game of telephone. They can
correct a price now. Not the order: a quantity, a description, a line added or
removed is what was agreed with the supplier, and that stays purchasing's. And
like every other non-director edit here, it queues for the director rather than
applying on the spot.
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


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)

    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    adm = await login("admin@demo.local")
    fin = await login("finance@demo.local")
    pur = await login("purchasing@demo.local")
    s1 = await login("sales1@demo.local")

    n = [0]

    async def a_job(label, *, dp=False):
        n[0] += 1
        cust = J(await c.post("/customers", headers=s1, json={
            "company_name": f"PT Ganda {label} {TAG}-{n[0]}", "industry": "mining",
            "delivery_address": "SITE"}))["id"]
        pr = J(await c.post("/price-requests", headers=s1, json={
            "customer_id": cust,
            "items": [{"description": f"Chain {label} {TAG}-{n[0]}", "qty": 4,
                       "uom": "pcs", "category": "roller_chain"}]}))["id"]
        await c.post(f"/price-requests/{pr}/submit", headers=s1)
        await c.post(f"/price-requests/{pr}/price", headers=d,
                     json={"items": [{"line_no": 1, "cost_price": 500, "basis": "unit"}]})
        await c.post(f"/price-requests/{pr}/approve", headers=d,
                     json={"items": [{"line_no": 1, "sell_price": 1000, "basis": "unit"}]})
        q = J(await c.post(f"/quotations/from-price-request/{pr}", headers=s1))["id"]
        await c.post(f"/quotations/{q}/submit", headers=s1)
        await c.post(f"/quotations/{q}/approve", headers=d, json={"decision": "approve"})
        cpo = J(await c.post("/customer-pos", headers=s1, json={
            "customer_id": cust, "quotation_id": q,
            "number": f"PO-{label}-{TAG}-{n[0]}",
            "items": [{"description": f"Chain {label} {TAG}", "qty": 4,
                       "unit_price": 1000}],
            "is_downpayment": dp}))["id"]
        if dp:
            return cust, cpo, None
        await c.post(f"/quotations/{q}/won", headers=d)
        proj = J(await c.post(f"/customer-pos/{cpo}/approve", headers=d,
                              json={"decision": "approve"}))["project_id"]
        await c.post(f"/operation/projects/{proj}/qc", headers=adm,
                     json={"decision": "pass"})
        return cust, cpo, proj

    async def invoices(proj):
        f = J(await c.get(f"/operation/projects/{proj}/full", headers=d))
        return f.get("invoices") or []

    # ══ pressing Issue twice ═════════════════════════════════════════════
    print("\n── the second press does not raise a second bill ──")
    _, _, p1 = await a_job("A")
    r = await c.post(f"/operation/projects/{p1}/issue-invoice", headers=adm,
                     data={"invoice_type": "final"})
    check("the invoice is issued", r.status_code == 201, f"{r.status_code} {why(r)}")
    first = J(r)["invoice"]["number"] if "invoice" in J(r) else None
    check("...one invoice on the project", len(await invoices(p1)) == 1,
          str(len(await invoices(p1))))

    r = await c.post(f"/operation/projects/{p1}/issue-invoice", headers=adm,
                     data={"invoice_type": "final"})
    check("pressing it again is refused", r.status_code == 409,
          f"{r.status_code} {why(r)}")
    check("...naming the invoice that already exists",
          first and first.lower() in why(r), why(r)[:180])
    check("...and says what to do instead", "delete" in why(r), why(r)[:180])
    check("still one invoice", len(await invoices(p1)) == 1,
          str(len(await invoices(p1))))

    print("\n── but a deliberate second one is allowed ──")
    r = await c.post(f"/operation/projects/{p1}/issue-invoice", headers=adm,
                     data={"invoice_type": "final", "additional": "true",
                           "amount": "250000"})
    check("saying 'additional' raises it", r.status_code == 201,
          f"{r.status_code} {why(r)}")
    check("...and now there are two, on purpose", len(await invoices(p1)) == 2,
          str(len(await invoices(p1))))

    print("\n── a rejected one does not block a replacement ──")
    _, _, p2 = await a_job("B")
    await c.post(f"/operation/projects/{p2}/issue-invoice", headers=adm,
                 data={"invoice_type": "final"})
    iv2 = (await invoices(p2))[0]["id"]
    r = await c.post(f"/finance/invoices/{iv2}/reject", headers=fin,
                     data={"reason": "wrong amount"})
    check("finance rejects the wrong one", r.status_code < 300,
          f"{r.status_code} {why(r)}")
    r = await c.post(f"/operation/projects/{p2}/issue-invoice", headers=adm,
                     data={"invoice_type": "final"})
    check("...and a fresh one can be issued without the flag",
          r.status_code == 201, f"{r.status_code} {why(r)}")

    # ══ the deposit route ════════════════════════════════════════════════
    print("\n── the same on the deposit route ──")
    _, dpo, _ = await a_job("C", dp=True)
    await c.post(f"/customer-pos/{dpo}/dp/finance-approve", headers=fin,
                 json={"notes": "ok"})
    r = await c.post(f"/customer-pos/{dpo}/dp-invoice", headers=fin,
                     data={"amount": "1000"})
    check("the DP invoice is issued", r.status_code == 201,
          f"{r.status_code} {why(r)}")
    r = await c.post(f"/customer-pos/{dpo}/dp-invoice", headers=fin,
                     data={"amount": "1000"})
    check("...and a second press is refused", r.status_code == 409,
          f"{r.status_code} {why(r)}")

    # ══ the faktur pajak number ══════════════════════════════════════════
    print("\n── one faktur pajak number, one invoice ──")
    fp = f"010.000-26.{TAG}"
    ivs = await invoices(p1)
    a_id, b_id = ivs[0]["id"], ivs[1]["id"]
    r = await c.post(f"/finance/invoices/{a_id}/approve", headers=fin,
                     data={"faktur_pajak_no": fp})
    check("the first invoice takes the number", r.status_code < 300,
          f"{r.status_code} {why(r)}")
    r = await c.post(f"/finance/invoices/{b_id}/approve", headers=fin,
                     data={"faktur_pajak_no": fp})
    check("the second cannot be approved with the same one",
          r.status_code == 409, f"{r.status_code} {why(r)}")
    check("...and says which invoice holds it",
          "already on invoice" in why(r), why(r)[:180])
    r = await c.post(f"/finance/invoices/{b_id}/approve", headers=fin)
    check("...approving it without a number is fine", r.status_code < 300,
          f"{r.status_code} {why(r)}")

    # ══ finance and the PO price ═════════════════════════════════════════
    print("\n── finance corrects a price on a supplier PO ──")
    sup = J(await c.post("/purchasing/suppliers", headers=pur, json={
        "name": f"PT Vendor {TAG}", "country": "ID"}))["id"]
    po = J(await c.post("/purchasing/po", headers=d, json={
        "supplier_id": sup, "project_id": p1, "po_date": "2026-09-08",
        "items": [{"description": f"Chain A {TAG}", "qty": 4,
                   "unit_price": 100_000, "uom": "pcs"}]}))
    po_id = po["id"]

    async def po_now():
        rows = J(await c.get("/purchasing/po", headers=d))
        rows = rows if isinstance(rows, list) else rows.get("items", [])
        return next((x for x in rows if x["id"] == po_id), None)

    fixed = [{"description": f"Chain A {TAG}", "qty": 4,
              "unit_price": 125_000, "uom": "pcs"}]
    r = await c.patch(f"/purchasing/po/{po_id}", headers=fin,
                      json={"items": fixed, "total": 500_000})
    check("finance may send a corrected price", r.status_code == 200,
          f"{r.status_code} {why(r)}")
    check("...and it waits for the director, like every other edit here",
          J(r).get("pending_approval") is True, str(J(r))[:180])
    check("...so the order still reads the old figure",
          float((await po_now())["items"][0]["unit_price"]) == 100_000,
          str((await po_now())["items"][0]))

    req = [a for a in J(await c.get("/approvals", headers=d))
           if a.get("target_type") == "supplier_po" and a.get("target_id") == po_id]
    check("the director has it in the queue", len(req) == 1, str(len(req)))
    r = await c.post(f"/approvals/{req[0]['id']}/approve", headers=d)
    check("...and approving applies it", r.status_code == 200,
          f"{r.status_code} {why(r)}")
    after = await po_now()
    check("the corrected price is on the order",
          float(after["items"][0]["unit_price"]) == 125_000,
          str(after["items"][0]))
    check("...and the total with it", float(after["total"]) == 500_000,
          str(after["total"]))

    print("\n── but the order itself is still purchasing's ──")
    for label, items in (
        ("a quantity", [{"description": f"Chain A {TAG}", "qty": 9,
                         "unit_price": 125_000, "uom": "pcs"}]),
        ("a description", [{"description": "Something else", "qty": 4,
                            "unit_price": 125_000, "uom": "pcs"}]),
        ("a unit", [{"description": f"Chain A {TAG}", "qty": 4,
                     "unit_price": 125_000, "uom": "meter"}]),
        ("an extra line", [{"description": f"Chain A {TAG}", "qty": 4,
                            "unit_price": 125_000, "uom": "pcs"},
                           {"description": "Bonus", "qty": 1,
                            "unit_price": 1, "uom": "pcs"}]),
    ):
        r = await c.patch(f"/purchasing/po/{po_id}", headers=fin,
                          json={"items": items})
        check(f"finance cannot change {label}", r.status_code == 403,
              f"{r.status_code} {why(r)}")

    r = await c.patch(f"/purchasing/po/{po_id}", headers=fin,
                      json={"number": f"PO-RENAMED-{TAG}"})
    check("nor rename the order", r.status_code == 403, str(r.status_code))
    check("...and the refusal names what they may do", "price" in why(r),
          why(r)[:160])
    r = await c.patch(f"/purchasing/po/{po_id}", headers=fin,
                      json={"fx_rate": 1})
    check("the exchange rate is still theirs, and still immediate",
          r.status_code == 200, f"{r.status_code} {why(r)}")

    print("\n── and purchasing still edits the order it owns ──")
    r = await c.patch(f"/purchasing/po/{po_id}", headers=pur,
                      json={"items": [{"description": f"Chain A {TAG}", "qty": 6,
                                       "unit_price": 125_000, "uom": "pcs"}]})
    check("purchasing may change a quantity", r.status_code == 200,
          f"{r.status_code} {why(r)}")
    check("...and it queues for the director too",
          J(r).get("pending_approval") is True, str(J(r))[:160])

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)


asyncio.run(main())

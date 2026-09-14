"""Both signatures on a shipment belong to finance.

The delivery order used to be the director's, with a manager standing in, while
the invoice beside it was finance's. That put two desks on one shipment: the
goods and the bill go out together, and two people waited on each other over a
decision neither of them disagreed with. The desk that reconciles what was
shipped against what was billed now signs both.

What that changes, and what it does not:

* **The delivery order is addressed to finance**, in the approvals inbox and on
  the project page alike. A manager can no longer release one — they were
  standing in for a director who is no longer the addressee, and leaving them
  on the button while `decide()` refused them in the inbox would mean the two
  routes disagreed about who may sign.
* **The invoice is finance's too, properly this time.** The code let admin
  and a manager approve as well, because they reach the invoice desk to read
  and to issue. Reading is not signing.
* **The director is not a second answer.** A backstop that is never the
  right person to ask is just another version of "whose job is this", so the
  direct buttons are finance's alone. The generic approvals inbox still lets
  the director decide any pending request — that is a property of the
  approval system, not a rule about shipments, and a queue nobody can clear
  is worse. The cost is real: with finance away, nothing here gets signed.
* **Admin still issues and still cannot approve.** Issuing is not approving,
  and that is the one separation left.

Worth stating plainly, because it is the cost: with both signatures on one
desk there is no second pair of eyes between a document being issued and being
approved. That is deliberate, not an oversight.
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
    mgr = await login("manager@demo.local")
    s1 = await login("sales1@demo.local")

    n = [0]

    async def a_shipment(label):
        """A QC-passed job with a delivery order and a final invoice on it."""
        n[0] += 1
        cust = J(await c.post("/customers", headers=s1, json={
            "company_name": f"PT Kirim {label} {TAG}-{n[0]}", "industry": "mining",
            "delivery_address": "SITE, KALIMANTAN"}))["id"]
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
            "customer_id": cust, "quotation_id": q, "number": f"PO-{label}-{TAG}-{n[0]}",
            "items": [{"description": f"Chain {label} {TAG}", "qty": 4,
                       "unit_price": 1000}]}))["id"]
        await c.post(f"/quotations/{q}/won", headers=d)
        proj = J(await c.post(f"/customer-pos/{cpo}/approve", headers=d,
                              json={"decision": "approve"}))["project_id"]
        await c.post(f"/operation/projects/{proj}/qc", headers=adm,
                     json={"decision": "pass"})
        await c.post(f"/operation/projects/{proj}/delivery-order", headers=adm)
        await c.post(f"/operation/projects/{proj}/issue-invoice", headers=adm,
                     data={"invoice_type": "final", "create_delivery_order": "false"})
        f = J(await c.get(f"/operation/projects/{proj}/full", headers=d))
        return proj, f["deliveries"][0]["id"], f["invoices"][0]["id"]

    # ══ the delivery order ═══════════════════════════════════════════════
    print("\n── the delivery order is finance's to release ──")
    p1, do1, inv1 = await a_shipment("A")

    r = await c.post(f"/operation/deliveries/{do1}/approve", headers=s1)
    check("sales cannot release it", r.status_code in (401, 403), str(r.status_code))
    r = await c.post(f"/operation/deliveries/{do1}/approve", headers=adm)
    check("nor admin, who raised it", r.status_code == 403, str(r.status_code))
    r = await c.post(f"/operation/deliveries/{do1}/approve", headers=mgr)
    check("nor a manager, who used to stand in for the director",
          r.status_code == 403, str(r.status_code))
    check("...and the refusal names finance", "finance" in why(r), why(r)[:140])

    r = await c.post(f"/operation/deliveries/{do1}/approve", headers=fin)
    check("finance releases it", r.status_code == 200, f"{r.status_code} {why(r)}")
    f1 = J(await c.get(f"/operation/projects/{p1}/full", headers=d))
    check("...and the sheet is signed", f1["deliveries"][0]["approved_at"],
          str(f1["deliveries"][0])[:160])

    print("\n── and finance's to withdraw ──")
    r = await c.post(f"/operation/deliveries/{do1}/unapprove", headers=mgr)
    check("a manager cannot withdraw it either", r.status_code == 403,
          str(r.status_code))
    r = await c.post(f"/operation/deliveries/{do1}/unapprove", headers=fin)
    check("finance can", r.status_code == 200, f"{r.status_code} {why(r)}")
    r = await c.post(f"/operation/deliveries/{do1}/approve", headers=d)
    check("...and not even the director, on the button", r.status_code == 403,
          f"{r.status_code} {why(r)}")
    r = await c.post(f"/operation/deliveries/{do1}/approve", headers=fin)
    check("...finance signs it again after the withdrawal",
          r.status_code == 200, f"{r.status_code} {why(r)}")

    # ══ the approvals inbox ══════════════════════════════════════════════
    print("\n── a waiting delivery order reaches finance's inbox ──")
    p2, do2, inv2 = await a_shipment("B")
    rows = J(await c.get("/approvals", headers=fin))
    mine = [x for x in (rows if isinstance(rows, list) else [])
            if x.get("target_type") == "delivery_order" and x.get("target_id") == do2]
    check("finance sees it", len(mine) == 1,
          str([x.get("target_type") for x in (rows if isinstance(rows, list) else [])])[:200])
    check("...addressed to finance", mine and mine[0].get("required_role") == "finance",
          str(mine[0].get("required_role")) if mine else "none")

    mrows = J(await c.get("/approvals", headers=mgr))
    check("a manager's inbox does not carry it",
          not [x for x in (mrows if isinstance(mrows, list) else [])
               if x.get("target_id") == do2],
          "manager still sees a DO request")

    r = await c.post(f"/approvals/{mine[0]['id']}/approve", headers=fin)
    check("finance decides it from the inbox", r.status_code == 200,
          f"{r.status_code} {why(r)}")
    f2 = J(await c.get(f"/operation/projects/{p2}/full", headers=d))
    check("...and that released the sheet", f2["deliveries"][0]["approved_at"],
          str(f2["deliveries"][0])[:160])

    # ══ the invoice ══════════════════════════════════════════════════════
    print("\n── the invoice is finance's too, properly this time ──")
    r = await c.post(f"/finance/invoices/{inv2}/approve", headers=adm,
                     data={"faktur_pajak_no": f"010.000-26.{TAG}"})
    check("admin cannot sign it — issuing is not approving", r.status_code == 403,
          f"{r.status_code} {why(r)}")
    r = await c.post(f"/finance/invoices/{inv2}/approve", headers=mgr,
                     data={"faktur_pajak_no": f"010.000-26.{TAG}"})
    check("nor a manager", r.status_code == 403, str(r.status_code))
    r = await c.post(f"/finance/invoices/{inv2}/approve", headers=fin,
                     data={"faktur_pajak_no": f"010.000-26.{TAG}"})
    check("finance signs it", r.status_code < 300, f"{r.status_code} {why(r)}")

    print("\n── and not the director's either ──")
    p3, do3, inv3 = await a_shipment("C")
    r = await c.post(f"/finance/invoices/{inv3}/approve", headers=d)
    check("the director cannot sign an invoice", r.status_code == 403,
          f"{r.status_code} {why(r)}")
    r = await c.post(f"/finance/invoices/{inv3}/approve", headers=fin)
    check("...finance does", r.status_code < 300, f"{r.status_code} {why(r)}")

    # ══ both at once ═════════════════════════════════════════════════════
    print("\n── and both signatures in one press, by the desk that owns them ──")
    p4, do4, inv4 = await a_shipment("D")
    r = await c.post(f"/operation/projects/{p4}/approve-documents", headers=adm,
                     data={"faktur_pajak_no": f"010.000-26.D{TAG}"})
    check("admin cannot", r.status_code == 403, str(r.status_code))
    r = await c.post(f"/operation/projects/{p4}/approve-documents", headers=mgr,
                     data={"faktur_pajak_no": f"010.000-26.D{TAG}"})
    check("nor a manager", r.status_code == 403, str(r.status_code))
    r = await c.post(f"/operation/projects/{p4}/approve-documents", headers=fin,
                     data={"faktur_pajak_no": f"010.000-26.D{TAG}"})
    check("finance signs both", r.status_code == 200, f"{r.status_code} {why(r)}")
    body = J(r)
    check("...naming what it signed",
          len(body.get("delivery_orders") or []) == 1
          and len(body.get("invoices") or []) == 1, str(body)[:200])
    f4 = J(await c.get(f"/operation/projects/{p4}/full", headers=d))
    check("...the sheet is released", f4["deliveries"][0]["approved_at"],
          str(f4["deliveries"][0])[:140])
    check("...and the invoice approved with its number",
          f4["invoices"][0]["status"] == "approved"
          and f4["invoices"][0].get("faktur_pajak_no") == f"010.000-26.D{TAG}",
          str(f4["invoices"][0])[:180])

    p5, do5, inv5 = await a_shipment("E")
    r = await c.post(f"/operation/projects/{p5}/approve-documents", headers=d)
    check("the director cannot use it either", r.status_code == 403,
          f"{r.status_code} {why(r)}")

    # The one door left open, deliberately: a pending request in the generic
    # approvals inbox is still decidable by the director. That is how the
    # approval system works everywhere, and a queue nobody can clear when
    # finance is away is worse than this rule bent once.
    print("\n── except the approvals inbox, which is everyone's backstop ──")
    p6, do6, inv6 = await a_shipment("F")
    rows = J(await c.get("/approvals", headers=d))
    req = [x for x in (rows if isinstance(rows, list) else [])
           if x.get("target_type") == "delivery_order" and x.get("target_id") == do6]
    check("the director sees the waiting sheet", len(req) == 1, str(len(req)))
    r = await c.post(f"/approvals/{req[0]['id']}/approve", headers=d)
    check("...and can still clear it from there", r.status_code == 200,
          f"{r.status_code} {why(r)}")

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)


asyncio.run(main())

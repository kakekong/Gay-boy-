"""Purchasing hears about a new job, and stops seeing the customer's paperwork.

Asked for: *"At purchasing make it so that new project have notification"* and
*"Purchasing don't need to know faktur pajak invoice and delivery and cannot
customer po."*

Two halves of the same idea, which is what purchasing's job actually is.

**The half they were missing.** A project appears the moment a deal is won,
and nothing told purchasing. They found out because somebody mentioned it, or
because they scrolled the Projects list and noticed a code they didn't
recognise — which is a poor way to learn that sourcing was supposed to start
a week ago. Now it is a notification, and it clears itself: a purchase
request or a supplier PO against the job is purchasing picking it up, so the
row goes. A job that needs nothing bought ages out after a month instead of
nagging forever. It names the code and the price request, never the customer
— the customer-blindness rule is why this role exists in the shape it does.

**The half they should never have had.** The customer's own PO, the invoice
raised against it, the delivery order that ships it, the faktur pajak number
on it. None of that is theirs — they buy, they do not bill — and a customer PO
number or a tax-invoice number identifies the customer in all but words,
which is the very thing the price-request screens go to such lengths to hide.

What must NOT change is the sourcing half: the price request they cost, the
supplier orders they raise, the shipments they chase, the drawings, the work
orders, the dates. A rule that takes those away has taken away the job.
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
    pur = await login("purchasing@demo.local")
    mgr = await login("manager@demo.local")

    # ── a won deal, which is what makes a project ───────────────────────────
    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Rahasia {tag}", "industry": "mining",
        "delivery_address": f"SITE {tag}"}))["id"]
    pr = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [{"description": f"CHAIN {tag}", "qty": 4, "uom": "EA"}]}))
    pr_id, pr_no = pr["id"], pr["number"]
    await c.post(f"/price-requests/{pr_id}/submit", headers=s1)
    await c.post(f"/price-requests/{pr_id}/price", headers=pur,
                 json={"items": [{"line_no": 1, "cost_price": 500000, "basis": "unit"}]})
    await c.post(f"/price-requests/{pr_id}/approve", headers=d,
                 json={"items": [{"line_no": 1, "sell_price": 1000000, "basis": "unit"}]})
    q = J(await c.post(f"/quotations/from-price-request/{pr_id}", headers=s1))
    await c.post(f"/quotations/{q['id']}/submit", headers=s1)
    await c.post(f"/quotations/{q['id']}/approve", headers=d, json={"notes": ""})
    po_no = f"PO-SCOPE-{tag}"
    cpo = J(await c.post("/customer-pos", headers=s1, json={
        "customer_id": cust, "quotation_id": q["id"], "number": po_no,
        "items": [{"description": f"CHAIN {tag}", "qty": 4, "uom": "EA",
                   "unit_price": 1000000}],
        "is_downpayment": False}))["id"]
    await c.post(f"/quotations/{q['id']}/won", headers=d)
    spawned = J(await c.post(f"/customer-pos/{cpo}/approve", headers=d, json={"notes": ""}))
    proj = spawned["project_id"]
    code = spawned.get("project_code")

    async def bell(hdr):
        # The bell answers {"items": [...], ...}, not a bare list.
        return (J(await c.get("/notifications", headers=hdr)) or {}).get("items", [])

    def rows(items, kind):
        return [x for x in items if x.get("kind") == kind]

    # ══ the new job reaches purchasing ═══════════════════════════════════════
    print("\n── a project appears ──")
    mine = rows(await bell(pur), "project_new")
    hit = [x for x in mine if proj in (x.get("link") or "")]
    check("purchasing is told a new job landed", len(hit) == 1,
          str([x.get("title") for x in mine])[:250])
    row = hit[0] if hit else {}
    check("...named by its code, not the customer",
          code and code in (row.get("title") or "")
          and f"PT Rahasia {tag}" not in str(row),
          str(row)[:250])
    check("...saying nothing has been ordered against it",
          "nothing ordered" in (row.get("body") or "").lower(), str(row.get("body")))
    check("...pointing at the price request they source from",
          pr_no in (row.get("body") or ""), str(row.get("body")))
    check("...and linking to the job itself",
          row.get("link") == f"/projects/{proj}", str(row.get("link")))
    check("...loud enough to act on", row.get("severity") == "high",
          str(row.get("severity")))

    for label, hdr in (("sales", s1), ("admin", adm), ("finance", fin),
                       ("the director", d), ("a manager", mgr)):
        check(f"{label} is not handed purchasing's sourcing queue",
              not [x for x in rows(await bell(hdr), "project_new")
                   if proj in (x.get("link") or "")],
              f"shown to {label}")

    # ══ and it clears itself when they pick it up ════════════════════════════
    print("\n── purchasing picks it up ──")
    r = await c.post("/purchasing/pr", headers=pur, json={
        "project_id": proj, "notes": f"sourcing {tag}",
        "items": [{"description": f"CHAIN {tag}", "qty": 4, "uom": "EA"}]})
    check("they raise a purchase request against it", r.status_code in (200, 201),
          f"{r.status_code} {J(r)}"[:170])
    check("...and the job stops asking",
          not [x for x in rows(await bell(pur), "project_new")
               if proj in (x.get("link") or "")],
          "still nagging after the PR was raised")

    # ══ the customer's paperwork is not theirs ═══════════════════════════════
    print("\n── the customer's own order ──")
    r = await c.get(f"/customer-pos/{cpo}", headers=pur)
    check("purchasing cannot open a customer PO", r.status_code in (401, 403),
          f"{r.status_code} {str(J(r))[:120]}")
    r = await c.get("/customer-pos", headers=pur)
    check("...nor list them", r.status_code in (401, 403), str(r.status_code))
    r = await c.get("/customer-pos/export.xlsx", headers=pur)
    check("...nor export them", r.status_code in (401, 403), str(r.status_code))
    r = await c.get(f"/customer-pos/{cpo}/export.pdf", headers=pur)
    check("...nor print one", r.status_code in (401, 403), str(r.status_code))
    r = await c.get("/attachments", headers=pur,
                    params={"owner_type": "customer_po", "owner_id": cpo})
    check("...nor read the files filed against it",
          r.status_code in (401, 403), str(r.status_code))
    for label, hdr in (("sales", s1), ("finance", fin), ("admin", adm)):
        r = await c.get(f"/customer-pos/{cpo}", headers=hdr)
        check(f"...while {label} still can — this took nothing from them",
              r.status_code == 200, f"{r.status_code} {str(J(r))[:120]}")

    # ── the close-out documents ──────────────────────────────────────────────
    print("\n── the invoice and the delivery order ──")
    await c.post(f"/operation/projects/{proj}/qc", headers=adm,
                 json={"decision": "pass"})
    issued = J(await c.post(f"/operation/projects/{proj}/issue-invoice", headers=adm,
                            data={"invoice_type": "final",
                                  "create_delivery_order": "true"}))
    inv_id, inv_no = issued["invoice"]["id"], issued["invoice"]["number"]
    do_no = issued["delivery_order"]["number"]
    fp = f"010.000-26.{tag}"
    await c.post(f"/finance/invoices/{inv_id}/approve", headers=fin,
                 data={"faktur_pajak_no": fp})

    full_pur = J(await c.get(f"/operation/projects/{proj}/full", headers=pur))
    check("the project carries no invoices for purchasing",
          full_pur.get("invoices") == [], str(full_pur.get("invoices"))[:200])
    check("...no delivery orders either",
          full_pur.get("deliveries") == [], str(full_pur.get("deliveries"))[:200])
    check("...and no customer PO", full_pur.get("customer_po") is None,
          str(full_pur.get("customer_po")))
    blob = str(full_pur)
    check("...so no faktur pajak number anywhere on the page", fp not in blob,
          blob[:200])
    check("...no invoice number", inv_no not in blob, blob[:200])
    check("...no delivery order number", do_no not in blob, blob[:200])
    check("...and still no customer PO number", po_no not in blob, blob[:200])
    check("...nor the customer's name, as before", f"PT Rahasia {tag}" not in blob,
          blob[:200])

    print("\n── which is not a general blackout ──")
    full_adm = J(await c.get(f"/operation/projects/{proj}/full", headers=adm))
    check("admin still gets the invoices", len(full_adm.get("invoices") or []) == 1,
          str(len(full_adm.get("invoices") or [])))
    check("...the deliveries", len(full_adm.get("deliveries") or []) == 1,
          str(len(full_adm.get("deliveries") or [])))
    check("...and the customer PO", (full_adm.get("customer_po") or {}).get("number") == po_no,
          str(full_adm.get("customer_po")))
    full_d = J(await c.get(f"/operation/projects/{proj}/full", headers=d))
    check("the director sees all three", bool(full_d.get("invoices"))
          and bool(full_d.get("deliveries")) and bool(full_d.get("customer_po")),
          str({k: bool(full_d.get(k)) for k in ("invoices", "deliveries", "customer_po")}))

    # ── the sourcing half is untouched ───────────────────────────────────────
    print("\n── purchasing keeps their own job ──")
    proj_row = full_pur.get("project") or {}
    check("the project still opens for them", bool(proj_row.get("code")),
          str(full_pur)[:150])
    check("...with the price request they source from",
          (full_pur.get("price_request") or {}).get("number") == pr_no,
          str(full_pur.get("price_request"))[:170])
    check("...and the buying cost on it, which is theirs",
          any(i.get("cost_price") for i in
              ((full_pur.get("price_request") or {}).get("items") or [])),
          str(full_pur.get("price_request"))[:250])
    check("...the purchase request they just raised",
          len(full_pur.get("purchase_requests") or []) >= 1,
          str(full_pur.get("purchase_requests"))[:170])
    check("...and the job's own PO number is gone with the rest",
          proj_row.get("po_number") is None, str(proj_row.get("po_number")))
    check("...the work orders", "work_orders" in full_pur, "missing")
    # The shipping dates live on the project row itself, not inside /full —
    # the timeline editor reads them from there — so that is where to look.
    row_pur = J(await c.get(f"/operation/projects/{proj}", headers=pur))
    check("...and the origin-leg shipping dates they own",
          "est_ship_from_origin" in row_pur, str(sorted(row_pur))[:200])
    check("...on a row that still hides the customer's PO number",
          row_pur.get("po_number") is None, str(row_pur.get("po_number")))
    check("...while admin's row still carries it",
          J(await c.get(f"/operation/projects/{proj}", headers=adm))
          .get("po_number") == po_no, "missing for admin")
    r = await c.get("/purchasing/po", headers=pur)
    check("their own purchase orders still open", r.status_code == 200,
          str(r.status_code))
    r = await c.get("/price-requests", headers=pur)
    check("...and their costing queue", r.status_code == 200, str(r.status_code))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)


asyncio.run(main())

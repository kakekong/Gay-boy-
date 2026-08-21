"""Full workflow driver A-H — drives the real ASGI app end to end."""
import asyncio, os, sys, io, uuid
os.environ.update(
    DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123",
    STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import httpx, logging
logging.disable(logging.INFO)

STEP=0; PROBLEMS=[]
def step(t):
    global STEP; STEP+=1; print(f"\n=== STEP {STEP}: {t} ===", flush=True)
def ok(m): print(f"   ✓ {m}", flush=True)
def bad(m): PROBLEMS.append(f"STEP {STEP}: {m}"); print(f"   ✗ PROBLEM: {m}", flush=True)
def J(r):
    try: return r.json()
    except Exception: return {"_raw": r.text[:200]}

async def login(c,e):
    r=await c.post("/auth/login",json={"email":e,"password":"test-pass-123"})
    assert r.status_code==200,f"{e}:{r.text}"; return {"Authorization":f"Bearer {r.json()['access_token']}"}

async def approve_in_inbox(c, H, target_substr, target_id=None):
    """Approve a pending request. Match on target_id when given — the inbox can
    hold leftovers of the same type from earlier runs, and approving one of
    those silently leaves THIS run's document undecided."""
    r=await c.get("/approvals",headers=H["director"]); inbox=r.json()
    reqs=inbox if isinstance(inbox,list) else inbox.get("items",inbox.get("data",[]))
    req=next((x for x in reqs
              if target_substr in str(x.get("target_type","")).lower()
              and (target_id is None or str(x.get("target_id"))==str(target_id))),None)
    if not req: return None,reqs
    r=await c.post(f"/approvals/{req['id']}/approve",headers=H["director"],json={"notes":""})
    return r,req

async def main():
    from app.scripts.seed import ensure_schema
    await ensure_schema()
    from app.main import app
    c=httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://t/api/v1",timeout=40)
    H={r:await login(c,f"{r}@demo.local") for r in
       ["director","sales1","sales2","purchasing","admin","finance","manager","hr"]}
    print("Logged in:", ", ".join(H))

    # ===== PHASE A =====
    step("A1 sales1 creates customer")
    b=J(await c.post("/customers",headers=H["sales1"],json={"company_name":f"PT Alpha {uuid.uuid4().hex[:5]}","industry":"mining"}))
    cust=b["id"]; ok(f"customer={cust} stage={b['stage']}")

    step("A2 sales1 raises price request (no prices)")
    b=J(await c.post("/price-requests",headers=H["sales1"],json={"customer_id":cust,
        "items":[{"description":"Gearbox housing","qty":2,"uom":"pcs","spec":"cast iron"},
                 {"description":"Drive shaft","qty":4,"uom":"pcs"}]}))
    pr=b["id"]; ok(f"PR {b['number']} status={b['status']}")

    step("A3 submit -> pending_purchasing")
    b=J(await c.post(f"/price-requests/{pr}/submit",headers=H["sales1"]))
    ok(f"status={b['status']}") if b.get("status")=="pending_purchasing" else bad(b)

    step("A4 purchasing sees a neutral code, not the company name")
    b=J(await c.get(f"/price-requests/{pr}",headers=H["purchasing"]))
    cn=b.get("customer_name")
    (ok(f"customer_name shown to purchasing = {cn!r} (blinded)") if cn!="PT Alpha Mining"
        else bad(f"purchasing sees real company name {cn!r}"))
    (ok("sell price hidden") if all(i.get("sell_price") in (None,0) for i in b.get("items",[]))
        else bad("purchasing sees sell price"))

    step("A5 purchasing fills cost -> pending_director")
    b=J(await c.post(f"/price-requests/{pr}/price",headers=H["purchasing"],json={
        "items":[{"line_no":1,"cost_price":1000000,"basis":"unit"},
                 {"line_no":2,"cost_price":500000,"basis":"unit"}]}))
    ok(f"status={b['status']}") if b.get("status")=="pending_director" else bad(b)

    step("A6 sales cannot see cost")
    b=J(await c.get(f"/price-requests/{pr}",headers=H["sales1"]))
    (ok("cost hidden from sales") if all(i.get("cost_price") in (None,0) for i in b.get("items",[]))
        else bad("sales sees cost"))

    step("A7 director sets sell price + approves -> approved")
    b=J(await c.post(f"/price-requests/{pr}/approve",headers=H["director"],json={
        "items":[{"line_no":1,"sell_price":1500000,"basis":"unit"},
                 {"line_no":2,"sell_price":800000,"basis":"unit"}]}))
    ok(f"status={b['status']}") if b.get("status")=="approved" else bad(b)

    # ===== PHASE B =====
    step("B1 sales1 generates quotation from PR (prices auto-filled)")
    b=J(await c.post(f"/quotations/from-price-request/{pr}",headers=H["sales1"]))
    q=b["id"]; items=b.get("items",[])
    ok(f"quote {b['number']} status={b['status']} lines={len(items)}")
    (ok("sell prices auto-filled") if items and all((i.get('unit_price') or 0)>0 for i in items)
        else bad(f"missing prices {items}"))

    step("B2 submit -> pending_approval")
    b=J(await c.post(f"/quotations/{q}/submit",headers=H["sales1"])); ok(f"status={b['status']}")

    step("B3 director approves (UI sends {notes:''}) -> approved, stage->quotation")
    r=await c.post(f"/quotations/{q}/approve",headers=H["director"],json={"notes":""}); b=J(r)
    ok(f"status={b.get('status')}") if b.get("status")=="approved" else bad(f"HTTP{r.status_code} {b}")
    st=J(await c.get(f"/customers/{cust}",headers=H["sales1"]))["stage"]
    ok(f"customer stage={st}") if st=="quotation" else bad(f"stage={st}")

    step("B4 exports PDF+Excel")
    for e in ("pdf","xlsx"):
        r=await c.get(f"/quotations/{q}/export.{e}",headers=H["sales1"])
        (ok(f"export.{e}: {len(r.content)}B {r.headers.get('content-type')}") if r.status_code==200 and r.content
            else bad(f"export.{e} HTTP{r.status_code}"))

    step("B5 customer PO first, then mark Won -> director approval -> won")
    # Won rests on the customer's order: the PO is filed here, and the PO's own
    # director approval (which spawns the project) still happens in phase C.
    po_pre=J(await c.post("/customer-pos",headers=H["sales1"],json={"customer_id":cust,"quotation_id":q,
        "number":f"PO-CUST-{uuid.uuid4().hex[:6]}","po_date":"2026-07-20",
        "items":[{"description":"Gearbox","qty":1,"unit_price":9_000_000}],"is_downpayment":False}))
    (ok(f"customer PO filed {po_pre.get('number')}") if po_pre.get("id")
        else bad(f"customer PO not filed: {str(po_pre)[:120]}"))
    r=await c.post(f"/quotations/{q}/won",headers=H["sales1"]); print(f"     won click HTTP {r.status_code} status={J(r).get('status')}")
    ra,req=await approve_in_inbox(c,H,"won",q)
    if ra is None: bad("no won approval in inbox")
    else:
        b=J(await c.get(f"/quotations/{q}",headers=H["sales1"]))
        ok(f"quote status={b['status']}") if b["status"]=="won" else bad(f"status={b['status']}")
        st=J(await c.get(f"/customers/{cust}",headers=H["sales1"]))["stage"]; ok(f"customer stage={st}")

    step("B6 Mark Lost blocked on won quote")
    r=await c.post(f"/quotations/{q}/lost",headers=H["sales1"],params={"reason":"x"})
    (ok(f"lost blocked (HTTP {r.status_code})") if r.status_code>=400 else bad("lost not blocked"))

    # ===== PHASE C =====
    step("C1 the Customer PO filed in B5 is waiting on the director")
    # It was filed before the win, because the win rests on it. What is left
    # here is the director's approval, which is what spawns the project.
    b=J(await c.get(f"/customer-pos/{po_pre['id']}",headers=H["sales1"]))
    cpo=b["id"]
    ok(f"PO {b['number']} status={b['status']}") if b.get("status")=="pending_approval" \
        else bad(f"PO status={b.get('status')}")

    step("C2 director approves Customer PO -> project spawned")
    b=J(await c.post(f"/customer-pos/{cpo}/approve",headers=H["director"],json={"notes":""}))
    proj=b.get("project_id")
    ok(f"PO status={b['status']} project={proj}") if b.get("status")=="approved" and proj else bad(b)
    st=J(await c.get(f"/customers/{cust}",headers=H["sales1"]))["stage"]; ok(f"customer stage={st}")

    # ===== PHASE D: Drawing =====
    step("D1 purchasing files the vendor's sheet, admin the customer's -> submitted, project->drawing")
    # Two documents now: the supplier's is procurement's, the customer's is
    # admin's, and only the customer's sign-off moves the job on.
    await c.post(f"/operation/projects/{proj}/drawings",headers=H["purchasing"],
                 data={"notes":"vendor rev A","kind":"supplier"},
                 files={"file":("supplier.pdf",io.BytesIO(b"%PDF-1.4 vendor"),"application/pdf")})
    files={"file":("drawing.pdf",io.BytesIO(b"%PDF-1.4 fake drawing"),"application/pdf")}
    r=await c.post(f"/operation/projects/{proj}/drawings",headers=H["admin"],
                   data={"notes":"rev A","kind":"customer"},files=files); b=J(r)
    draw=b.get("id") or b.get("drawing",{}).get("id")
    (ok(f"drawing uploaded HTTP{r.status_code} id={draw}") if r.status_code==201 else bad(f"HTTP{r.status_code} {b}"))
    pj=J(await c.get(f"/operation/projects/{proj}",headers=H["director"]))
    ok(f"project status={pj.get('status')}")
    if not draw:  # find it
        full=J(await c.get(f"/operation/projects/{proj}/full",headers=H["director"]))
        ds=full.get("drawings",[]); draw=ds[0]["id"] if ds else None

    step("D2 director approves drawing -> drawing_approved")
    r=await c.post(f"/operation/drawings/{draw}/decide",headers=H["director"],json={"decision":"approve"}); b=J(r)
    pj=J(await c.get(f"/operation/projects/{proj}",headers=H["director"]))
    ok(f"HTTP{r.status_code} project status={pj.get('status')}") if pj.get("status")=="drawing_approved" else bad(f"status={pj.get('status')} {b}")

    # ===== PHASE E: Supplier PO =====
    step("E1 director creates a supplier")
    b=J(await c.post("/purchasing/suppliers",headers=H["director"],json={"name":f"CV Baja {cust[:8]}","category":"steel"}))
    supp=b.get("id"); ok(f"supplier={supp}")

    step("E2 purchasing prefill from price request (buying prices)")
    r=await c.get("/purchasing/po/prefill",headers=H["purchasing"],params={"project_id":proj}); pf=J(r)
    ok(f"prefill linked PR={pf.get('price_request_number')} items={len(pf.get('items',[]))} total={pf.get('total')}")
    if not pf.get("price_request_id"): bad("supplier PO prefill did NOT auto-link the price request")

    step("E3 purchasing issues supplier PO -> pending_approval")
    r=await c.post("/purchasing/po",headers=H["purchasing"],json={"supplier_id":supp,"project_id":proj,
        "items":pf.get("items",[]),"total":pf.get("total",0),"price_request_id":pf.get("price_request_id")}); b=J(r)
    spo=b.get("id"); ok(f"HTTP{r.status_code} supplier PO status={b.get('status')} number={b.get('number')}")

    step("E4 director approves supplier PO -> open")
    ra,req=await approve_in_inbox(c,H,"supplier_po",spo)
    if ra is None: bad("no supplier_po approval in inbox")
    else:
        b=J(await c.get(f"/purchasing/po/{spo}",headers=H["purchasing"]))
        ok(f"supplier PO status={b.get('status')}") if b.get("status")=="open" else bad(f"status={b.get('status')}")

    # ===== PHASE F: Logistics =====
    step("F1 purchasing sets delivery mode + est date (local)")
    r=await c.patch(f"/operation/projects/{proj}/logistics",headers=H["purchasing"],
                    json={"delivery_mode":"local","est_delivery_date":"2026-08-15"}); b=J(r)
    ok(f"HTTP{r.status_code} delivery_mode set")

    step("F2 upload + director-approve the required import docs (local: invoice, packing_list)")
    for key in ("invoice","packing_list"):
        f={"file":(f"{key}.pdf",io.BytesIO(b"doc"),"application/pdf")}
        ru=await c.post(f"/operation/projects/{proj}/import-docs/{key}/upload",headers=H["purchasing"],data={"note":"x"},files=f)
        rd=await c.post(f"/operation/projects/{proj}/import-docs/{key}/decide",headers=H["director"],json={"decision":"approve"})
        print(f"     {key}: upload HTTP{ru.status_code}, approve HTTP{rd.status_code}")
    docs_ok=J(rd).get("docs_approved")
    ok(f"docs_approved={docs_ok}") if docs_ok else bad(f"docs not all approved: {J(rd)}")

    step("F3 confirm delivery -> production + receiving work order")
    r=await c.post(f"/operation/projects/{proj}/confirm-delivery",headers=H["purchasing"]); b=J(r)
    pj=J(await c.get(f"/operation/projects/{proj}",headers=H["director"]))
    ok(f"HTTP{r.status_code} project status={pj.get('status')} receiving_wo={bool(b.get('receiving_work_order'))}") \
        if r.status_code==200 and pj.get("status")=="production" else bad(f"HTTP{r.status_code} status={pj.get('status')} {b}")

    # ===== PHASE G: Ops + QC =====
    step("G1 admin creates a QC work order (requires production) -> project qc")
    r=await c.post(f"/operation/projects/{proj}/work-orders",headers=H["admin"],json={"code":"WO-QC-1","stage":"qc"}); b=J(r)
    pj=J(await c.get(f"/operation/projects/{proj}",headers=H["director"]))
    ok(f"HTTP{r.status_code} project status={pj.get('status')}") if r.status_code==201 else bad(f"HTTP{r.status_code} {b}")

    step("G2 operations records QC pass")
    r=await c.post(f"/operation/projects/{proj}/qc",headers=H["admin"],json={"decision":"pass","findings":"all good"}); b=J(r)
    ok(f"HTTP{r.status_code} qc_decision={b.get('qc_decision')} project status={b.get('status')}") \
        if r.status_code==200 and b.get("qc_decision")=="pass" else bad(f"HTTP{r.status_code} {b}")

    # ===== PHASE H: Invoice/faktur/payment =====
    step("H1a CHECK: can ADMIN issue the invoice? (workflow says yes; code set = {finance,director})")
    r=await c.post(f"/operation/projects/{proj}/issue-invoice",headers=H["admin"],
                   data={"invoice_type":"single","amount":3000000});
    print(f"     admin issue-invoice HTTP {r.status_code}: {J(r).get('errors',[{}])[0].get('message') if r.status_code>=400 else 'allowed'}")
    if r.status_code==403: bad("ADMIN cannot issue invoice, but workflow doc + error message say admin can (role set excludes admin)")

    step("H1b finance issues the invoice + DO")
    r=await c.post(f"/operation/projects/{proj}/issue-invoice",headers=H["finance"],
                   data={"invoice_type":"single","amount":3000000,"create_delivery_order":"true"}); b=J(r)
    inv=b.get("invoice",{}).get("id") or b.get("id") or b.get("invoice_id")
    ok(f"HTTP{r.status_code} invoice={inv} status={b.get('invoice',{}).get('status') or b.get('status')}") \
        if r.status_code==201 else bad(f"HTTP{r.status_code} {b}")
    if not inv:
        pend=J(await c.get("/finance/invoices/pending",headers=H["finance"]))
        rows=pend if isinstance(pend,list) else pend.get("items",[])
        inv=rows[0]["id"] if rows else None

    step("H2 finance approves invoice with faktur pajak (no ledger effect)")
    r=await c.post(f"/finance/invoices/{inv}/approve",headers=H["finance"],data={"faktur_pajak_no":"010.000-26.00000001"}); b=J(r)
    ok(f"HTTP{r.status_code} invoice status={b.get('status')} faktur={b.get('faktur_pajak_no')}") \
        if r.status_code==200 and b.get("status")=="approved" else bad(f"HTTP{r.status_code} {b}")

    step("H2b the faktur pajak number is finance's, typed in when e-Faktur produces it")
    # It used to be mandatory at approval, which parked the invoice behind a
    # number that arrives on the tax office's schedule, not the customer's.
    r=await c.post(f"/finance/invoices/{inv}/faktur-pajak",headers=H["finance"],
                   json={"faktur_pajak_no":"010.000-26.00000009"}); b=J(r)
    ok(f"finance set it manually: {b.get('faktur_pajak_no')} ({b.get('faktur_pajak_status')})") \
        if r.status_code==200 and b.get("faktur_pajak_status")=="issued" \
        else bad(f"HTTP{r.status_code} {b}")
    r=await c.post(f"/finance/invoices/{inv}/faktur-pajak",headers=H["admin"],
                   json={"faktur_pajak_no":"010.000-26.00000010"})
    ok("admin cannot write the tax record") if r.status_code==403 \
        else bad(f"admin set a faktur pajak number (HTTP {r.status_code})")

    step("H3 finance records full manual payment -> project paid->closed")
    r=await c.post("/payments/manual",headers=H["finance"],json={"invoice_id":inv,"amount":3000000,"method":"transfer","reference":"TRX1"}); b=J(r)
    print(f"     manual payment HTTP {r.status_code}: {b if r.status_code>=400 else 'recorded'}")
    pj=J(await c.get(f"/operation/projects/{proj}",headers=H["director"]))
    ok(f"project status={pj.get('status')}")
    st=J(await c.get(f"/customers/{cust}",headers=H["sales1"]))["stage"]; ok(f"customer stage={st}")

    step("H4 admin marks customer received -> delivered")
    r=await c.post(f"/operation/projects/{proj}/customer-received",headers=H["admin"],json={}); b=J(r)
    pj=J(await c.get(f"/operation/projects/{proj}",headers=H["director"]))
    ok(f"HTTP{r.status_code} project status={pj.get('status')}")

    print("\n\n########## SUMMARY ##########")
    print(f"customer={cust} project={proj}")
    print(f"PROBLEMS: {len(PROBLEMS)}")
    for p in PROBLEMS: print("  - "+p)
    await c.aclose()

asyncio.run(main())

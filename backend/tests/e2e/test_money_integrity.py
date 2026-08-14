"""Money/integrity fixes: invoice DPP is net (not tax-inclusive), legacy
payment endpoint posts to the ledger, failed QC can't be forged into a pass."""
import asyncio, os, sys, io, uuid
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123", STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import httpx, logging; logging.disable(logging.INFO)
PASS, FAIL = [], []
def check(n,c,d=""):
    (PASS if c else FAIL).append(n); print(("  PASS " if c else "  FAIL ")+n+(f"  [{d}]" if d and not c else ""))
def J(r):
    try: return r.json()
    except: return {"_":r.text[:150]}
async def login(c,e):
    r=await c.post("/auth/login",json={"email":e,"password":"test-pass-123"})
    return {"Authorization":f"Bearer {r.json()['access_token']}"}

async def build_project(c,H,tag):
    cust=J(await c.post("/customers",headers=H["s"],json={"company_name":f"PT Money {tag}","industry":"mining"}))["id"]
    pr=J(await c.post("/price-requests",headers=H["s"],json={"customer_id":cust,
        "items":[{"description":"Widget","qty":10,"uom":"pcs"}]}))["id"]
    await c.post(f"/price-requests/{pr}/submit",headers=H["s"])
    await c.post(f"/price-requests/{pr}/price",headers=H["d"],json={"items":[{"line_no":1,"cost_price":50000,"basis":"unit"}]})
    await c.post(f"/price-requests/{pr}/approve",headers=H["d"],json={"items":[{"line_no":1,"sell_price":100000,"basis":"unit"}]})
    q=J(await c.post(f"/quotations/from-price-request/{pr}",headers=H["s"]))["id"]
    await c.post(f"/quotations/{q}/submit",headers=H["s"]); await c.post(f"/quotations/{q}/approve",headers=H["d"],json={"notes":""})
    # The customer's PO comes first — Won is refused without it — and Won is
    # what starts the project. Approving the PO afterwards attaches to it.
    cpo=J(await c.post("/customer-pos",headers=H["s"],json={"customer_id":cust,"quotation_id":q,
        "number":f"PO-{tag}","items":[{"description":"Widget","qty":10,"unit_price":100000}],"is_downpayment":False}))["id"]
    await c.post(f"/quotations/{q}/won",headers=H["d"])
    proj=J(await c.post(f"/customer-pos/{cpo}/approve",headers=H["d"],json={"notes":""}))["project_id"]
    return cust,q,proj

async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    c=httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://t/api/v1",timeout=40)
    H={"d":await login(c,"director@demo.local"),"s":await login(c,"sales1@demo.local"),
       "a":await login(c,"admin@demo.local")}
    tag=uuid.uuid4().hex[:6]

    # ---------- 1. Invoice DPP must be NET, not the tax-inclusive quote total ----------
    cust,q,proj=await build_project(c,H,tag)
    quote=J(await c.get(f"/quotations/{q}",headers=H["d"]))
    subtotal=float(quote["subtotal"]); disc=float(quote.get("discount_amount") or 0)
    gross=float(quote["total"]); net=subtotal-disc
    check("quote total is tax-inclusive (gross > net)", gross>net, f"gross={gross} net={net}")

    # drive to QC pass so a final invoice can be issued
    await c.post(f"/operation/projects/{proj}/qc",headers=H["a"],json={"decision":"pass"})
    r=await c.post(f"/operation/projects/{proj}/issue-invoice",headers=H["d"],
                   data={"invoice_type":"single"})   # no amount -> uses the default
    check("invoice issued", r.status_code==201, J(r))
    inv=J(r).get("invoice") or J(r)
    from app.core.db import SessionLocal
    from app.models.finance import Invoice as _Inv
    from sqlalchemy import select as _sel
    async with SessionLocal() as _db:
        row=await _db.scalar(_sel(_Inv).where(_Inv.project_id==proj).order_by(_Inv.created_at.desc()))
        amt=float(row.amount or 0); tax=float(row.tax_amount or 0); inv={"id":str(row.id),"total":float(row.total or 0)}
    check("invoice DPP = net (not the gross quote total)", abs(amt-net)<1,
          f"amount={amt} net={net} gross={gross}")
    check("PPN defaulted from the quote tax rate", tax>0 and abs(amt+tax-gross)<1,
          f"amount={amt} tax={tax} gross={gross}")

    # ---------- 2. Legacy /finance/payments must post to the ledger ----------
    inv_id=inv.get("id")
    await c.post(f"/finance/invoices/{inv_id}/approve",headers=H["d"],
                 data={"faktur_pajak_no":f"010.000-26.{tag}"})
    total=float(inv.get("total") or (amt+tax))
    r=await c.post("/finance/payments",headers=H["d"],
                   params={"invoice_id":inv_id,"amount":total,"method":"transfer","reference":"LEGACY1"})
    check("legacy payment endpoint accepted", r.status_code in (200,201), J(r))
    body=J(r)
    async with SessionLocal() as _db:
        row=await _db.scalar(_sel(_Inv).where(_Inv.id==__import__("uuid").UUID(inv_id)))
        check("legacy payment recomputed invoice status", row.status=="paid", f"status={row.status}")
    pj=J(await c.get(f"/operation/projects/{proj}",headers=H["d"]))
    check("legacy payment advanced the project", pj.get("status") in ("paid","closed"),
          f"project={pj.get('status')}")
    # negative amount now rejected
    r=await c.post("/finance/payments",headers=H["d"],
                   params={"invoice_id":inv_id,"amount":-5,"method":"x"})
    check("legacy payment rejects non-positive amount", r.status_code>=400, str(r.status_code))

    # ---------- 3. Failed QC cannot be forged into a pass ----------
    tag2=uuid.uuid4().hex[:6]
    _,_,proj2=await build_project(c,H,tag2)
    r=await c.post(f"/operation/projects/{proj2}/qc",headers=H["a"],json={"decision":"fail","findings":"cracks"})
    check("QC fail recorded", r.status_code==200, J(r))
    wo=J(await c.post(f"/operation/projects/{proj2}/work-orders",headers=H["a"],
                      json={"code":f"WO-QC-{tag2}","stage":"qc"}))
    woid=wo.get("id")
    await c.patch(f"/operation/work-orders/{woid}",headers=H["a"],params={"completed":"true"})
    pj2=J(await c.get(f"/operation/projects/{proj2}/full",headers=H["d"])).get("project",{})
    check("completing a QC WO does NOT forge a pass after a fail",
          not pj2.get("qc_passed_at") and pj2.get("qc_decision")=="fail",
          f"passed_at={pj2.get('qc_passed_at')} decision={pj2.get('qc_decision')}")
    r=await c.post(f"/operation/projects/{proj2}/issue-invoice",headers=H["d"],
                   data={"invoice_type":"single"})
    check("final invoice still blocked after failed QC", r.status_code==409, str(r.status_code))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL: print("FAILED:",FAIL); sys.exit(1)
asyncio.run(main())

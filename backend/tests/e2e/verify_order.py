"""Prove: doing Supplier PO BEFORE the drawing lets the project reach
production so the QC work order can be filed — vs the documented order."""
import asyncio, os, sys, io, uuid
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123", STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0,"/home/user/Gay-boy-/backend")
import httpx, logging; logging.disable(logging.INFO)

async def login(c,e):
    r=await c.post("/auth/login",json={"email":e,"password":"test-pass-123"}); return {"Authorization":f"Bearer {r.json()['access_token']}"}
def J(r):
    try: return r.json()
    except: return {"_":r.text[:120]}

async def build_project(c,H):
    cust=J(await c.post("/customers",headers=H["s"],json={"company_name":f"PT Order {uuid.uuid4().hex[:5]}","industry":"mining"}))["id"]
    pr=J(await c.post("/price-requests",headers=H["s"],json={"customer_id":cust,"items":[{"description":"X","qty":1,"uom":"pcs"}]}))["id"]
    await c.post(f"/price-requests/{pr}/submit",headers=H["s"])
    await c.post(f"/price-requests/{pr}/price",headers=H["p"],json={"items":[{"line_no":1,"cost_price":100,"basis":"unit"}]})
    await c.post(f"/price-requests/{pr}/approve",headers=H["d"],json={"items":[{"line_no":1,"sell_price":200,"basis":"unit"}]})
    q=J(await c.post(f"/quotations/from-price-request/{pr}",headers=H["s"]))["id"]
    await c.post(f"/quotations/{q}/submit",headers=H["s"]); await c.post(f"/quotations/{q}/approve",headers=H["d"],json={"notes":""})
    # The customer's PO is the evidence Won rests on, so it is filed first.
    cpo=J(await c.post("/customer-pos",headers=H["s"],json={"customer_id":cust,"quotation_id":q,"number":f"PO-{uuid.uuid4().hex[:8]}","items":[{"description":"X","qty":1,"unit_price":200}],"is_downpayment":False}))["id"]
    await c.post(f"/quotations/{q}/won",headers=H["s"])
    inbox=J(await c.get("/approvals",headers=H["d"])); reqs=inbox if isinstance(inbox,list) else inbox.get("items",[])
    wr=next(x for x in reqs if x.get("target_type")=="quotation_won" and str(x.get("target_id"))==str(q)); await c.post(f"/approvals/{wr['id']}/approve",headers=H["d"],json={"notes":""})
    proj=J(await c.post(f"/customer-pos/{cpo}/approve",headers=H["d"],json={"notes":""}))["project_id"]
    return proj

async def supplier_po(c,H,proj):
    supp=J(await c.post("/purchasing/suppliers",headers=H["d"],json={"name":f"Supp-{proj[:8]}"}))["id"]
    pf=J(await c.get("/purchasing/po/prefill",headers=H["p"],params={"project_id":proj}))
    J(await c.post("/purchasing/po",headers=H["p"],json={"supplier_id":supp,"project_id":proj,"items":pf.get("items",[]),"total":pf.get("total",0),"price_request_id":pf.get("price_request_id")}))
    inbox=J(await c.get("/approvals",headers=H["d"])); reqs=inbox if isinstance(inbox,list) else inbox.get("items",[])
    sr=next((x for x in reqs if "supplier_po" in str(x.get("target_type","")).lower()),None)
    if sr: await c.post(f"/approvals/{sr['id']}/approve",headers=H["d"],json={"notes":""})

async def drawing(c,H,proj):
    # Purchasing file the vendor's sheet; admin file the one the customer
    # approves, and only that second sign-off advances the job.
    await c.post(f"/operation/projects/{proj}/drawings",headers=H["p"],data={"notes":"vendor","kind":"supplier"},files={"file":("s.pdf",io.BytesIO(b"x"),"application/pdf")})
    r=await c.post(f"/operation/projects/{proj}/drawings",headers=H["a"],data={"notes":"a","kind":"customer"},files={"file":("d.pdf",io.BytesIO(b"x"),"application/pdf")})
    did=J(r).get("id")
    await c.post(f"/operation/drawings/{did}/decide",headers=H["d"],json={"decision":"approve"})

async def confirm(c,H,proj):
    await c.patch(f"/operation/projects/{proj}/logistics",headers=H["p"],json={"delivery_mode":"local","est_delivery_date":"2026-08-15"})
    for k in ("invoice","packing_list"):
        await c.post(f"/operation/projects/{proj}/import-docs/{k}/upload",headers=H["p"],data={"note":"x"},files={"file":(f"{k}.pdf",io.BytesIO(b"x"),"application/pdf")})
        await c.post(f"/operation/projects/{proj}/import-docs/{k}/decide",headers=H["d"],json={"decision":"approve"})
    await c.post(f"/operation/projects/{proj}/confirm-delivery",headers=H["p"])

async def stat(c,H,proj): return J(await c.get(f"/operation/projects/{proj}",headers=H["d"])).get("status")

async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    c=httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://t/api/v1",timeout=40)
    H={"d":await login(c,"director@demo.local"),"s":await login(c,"sales1@demo.local"),"p":await login(c,"purchasing@demo.local"),"a":await login(c,"admin@demo.local")}

    ok=[0,0]
    def check(label,cond):
        ok[0 if cond else 1]+=1
        print(f"  {'PASS' if cond else 'FAIL'}  {label}")

    print("\n### ORDER 1 (DOCUMENTED): drawing BEFORE supplier PO ###")
    p1=await build_project(c,H); print("  spawn:",await stat(c,H,p1))
    await drawing(c,H,p1); print("  after drawing upload+approve:",await stat(c,H,p1))
    await supplier_po(c,H,p1); print("  after supplier PO:",await stat(c,H,p1))
    await confirm(c,H,p1); s1=await stat(c,H,p1)
    check(f"reaches production after confirm-delivery (got {s1})", s1=="production")
    r=await c.post(f"/operation/projects/{p1}/work-orders",headers=H["a"],json={"code":"WO-QC","stage":"qc"})
    check(f"QC work order accepted (HTTP {r.status_code})", r.status_code<400)

    print("\n### ORDER 2 (CODE'S EXPECTED): supplier PO BEFORE drawing ###")
    p2=await build_project(c,H); print("  spawn:",await stat(c,H,p2))
    await supplier_po(c,H,p2); print("  after supplier PO:",await stat(c,H,p2))
    await drawing(c,H,p2); print("  after drawing upload+approve:",await stat(c,H,p2))
    await confirm(c,H,p2); s2=await stat(c,H,p2)
    check(f"reaches production after confirm-delivery (got {s2})", s2=="production")
    r=await c.post(f"/operation/projects/{p2}/work-orders",headers=H["a"],json={"code":"WO-QC","stage":"qc"})
    check(f"QC work order accepted (HTTP {r.status_code})", r.status_code<400)
    await c.aclose()

    # run_all.sh reads this line to decide pass/fail — keep the wording.
    print(f"\n{ok[0]} passed, {ok[1]} failed")
    sys.exit(1 if ok[1] else 0)

asyncio.run(main())

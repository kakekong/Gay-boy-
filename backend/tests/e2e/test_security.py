"""Verify audit's security claims empirically: can external portal roles
(customer/supplier) read internal data? Can sales touch other reps' projects?"""
import asyncio, os, sys, io, uuid
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123", STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import httpx, logging; logging.disable(logging.INFO)
HOLES, OK = [], []
def probe(name, is_hole, detail=""):
    (HOLES if is_hole else OK).append(name)
    print(("  HOLE " if is_hole else "  ok   ")+name+(f"  [{detail}]" if detail else ""))
def J(r):
    try: return r.json()
    except: return {"_":r.text[:120]}
async def login(c,e,p="test-pass-123"):
    r=await c.post("/auth/login",json={"email":e,"password":p})
    return {"Authorization":f"Bearer {r.json()['access_token']}"} if r.status_code==200 else None

async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    c=httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://t/api/v1",timeout=40)
    d=await login(c,"director@demo.local"); s1=await login(c,"sales1@demo.local"); s2=await login(c,"sales2@demo.local")
    tag=uuid.uuid4().hex[:6]

    # sales1 builds a customer + quotation (private to sales1)
    cust=J(await c.post("/customers",headers=s1,json={"company_name":f"PT Secret {tag}","industry":"mining"}))["id"]

    # director creates a CUSTOMER-portal account linked to that customer
    cu_email=f"portal{tag}@demo.local"
    r=await c.post("/users",headers=d,json={"email":cu_email,"full_name":"Portal User",
        "role":"customer","password":"test-pass-123","linked_customer_id":cust})
    if r.status_code not in (200,201):
        print("could not create portal user:", r.status_code, J(r)); return
    cu=await login(c,cu_email)
    if not cu: print("portal login failed"); return

    # CLAIM 1: customer role can list ALL customers
    r=await c.get("/customers",headers=cu)
    body=J(r); rows=body.get("data") if isinstance(body,dict) else body
    n=len(rows) if isinstance(rows,list) else -1
    probe("customer-portal role can list internal CRM customers",
          r.status_code==200 and n>0, f"HTTP{r.status_code} rows={n}")

    # CLAIM 2: customer role can list quotations
    r=await c.get("/quotations",headers=cu)
    body=J(r); rows=body.get("data") if isinstance(body,dict) else body
    n=len(rows) if isinstance(rows,list) else -1
    probe("customer-portal role can list quotations", r.status_code==200 and n>0,
          f"HTTP{r.status_code} rows={n}")

    # CLAIM 3: customer role can read an EMPLOYEE attachment listing (HR docs)
    emp=J(await c.get("/users",headers=d))
    emp_id=(emp[0]["id"] if isinstance(emp,list) and emp else None)
    if emp_id:
        r=await c.get("/attachments",headers=cu,params={"owner_type":"employee","owner_id":emp_id})
        probe("customer-portal role can list EMPLOYEE (HR) attachments",
              r.status_code==200, f"HTTP{r.status_code}")

    # CLAIM 4: customer role can PATCH an arbitrary customer record
    r=await c.patch(f"/customers/{cust}",headers=cu,json={"company_name":"HACKED"})
    probe("customer-portal role can edit a customer record", r.status_code in (200,201),
          f"HTTP{r.status_code}")

    # CLAIM 5: sales2 can read sales1's project via /full  (build a project first)
    pr=J(await c.post("/price-requests",headers=s1,json={"customer_id":cust,"items":[{"description":"X","qty":1,"uom":"pcs"}]}))["id"]
    await c.post(f"/price-requests/{pr}/submit",headers=s1)
    await c.post(f"/price-requests/{pr}/price",headers=d,json={"items":[{"line_no":1,"cost_price":100,"basis":"unit"}]})
    await c.post(f"/price-requests/{pr}/approve",headers=d,json={"items":[{"line_no":1,"sell_price":200,"basis":"unit"}]})
    q=J(await c.post(f"/quotations/from-price-request/{pr}",headers=s1))["id"]
    await c.post(f"/quotations/{q}/submit",headers=s1); await c.post(f"/quotations/{q}/approve",headers=d,json={"notes":""})
    await c.post(f"/quotations/{q}/won",headers=d)
    cpo=J(await c.post("/customer-pos",headers=s1,json={"customer_id":cust,"quotation_id":q,
        "number":f"PO-{tag}","items":[{"description":"X","qty":1,"unit_price":200}],"is_downpayment":False}))["id"]
    proj=J(await c.post(f"/customer-pos/{cpo}/approve",headers=d,json={"notes":""})).get("project_id")

    r=await c.get(f"/operation/projects/{proj}",headers=s2)
    scoped_detail = r.status_code==403
    r2=await c.get(f"/operation/projects/{proj}/full",headers=s2)
    probe("other sales rep can read /projects/{id}/full (detail is scoped: %s)" % scoped_detail,
          r2.status_code==200 and scoped_detail, f"full=HTTP{r2.status_code} detail=HTTP{r.status_code}")

    # CLAIM 6: sales2 can PATCH sales1's project status
    r=await c.patch(f"/operation/projects/{proj}",headers=s2,json={"status":"closed"})
    probe("other sales rep can PATCH project status", r.status_code in (200,201),
          f"HTTP{r.status_code}")

    await c.aclose()
    print(f"\nCONFIRMED HOLES: {len(HOLES)}")
    for h in HOLES: print("  - "+h)
asyncio.run(main())

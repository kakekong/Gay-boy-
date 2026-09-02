"""The portal must still work for its rightful owner after the lockdown."""
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
    except: return {"_":r.text[:120]}
async def login(c,e,p="test-pass-123"):
    r=await c.post("/auth/login",json={"email":e,"password":p})
    return {"Authorization":f"Bearer {r.json()['access_token']}"} if r.status_code==200 else None

async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    c=httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://t/api/v1",timeout=40)
    d=await login(c,"director@demo.local"); s1=await login(c,"sales1@demo.local")
    tag=uuid.uuid4().hex[:6]

    cust=J(await c.post("/customers",headers=s1,json={"company_name":f"PT Portal {tag}","industry":"mining"}))["id"]
    other=J(await c.post("/customers",headers=s1,json={"company_name":f"PT Other {tag}","industry":"mining"}))["id"]
    email=f"pu{tag}@demo.local"
    await c.post("/users",headers=d,json={"email":email,"full_name":"Portal Owner","role":"customer",
                                          "password":"test-pass-123","linked_customer_id":cust})
    cu=await login(c,email)
    check("portal user can log in", cu is not None)

    # Portal's own endpoints must still work
    for ep in ("/portal/customer/me","/portal/customer/quotations","/portal/customer/projects"):
        r=await c.get(ep,headers=cu)
        check(f"portal endpoint {ep} works", r.status_code==200, f"HTTP{r.status_code}")
    # Payments are finance's own entry now. The portal shows invoices and
    # their status; there is nothing there for a customer to submit, and the
    # endpoints that used to accept it are gone rather than merely hidden.
    r=await c.get("/payments/claims/mine",headers=cu)
    check("the portal's claim list is gone", r.status_code==404, f"HTTP{r.status_code}")
    r=await c.post("/payments/claims",headers=cu,json={"invoice_id":cust,"amount":1})
    check("...and a customer cannot submit one", r.status_code in (404,405),
          f"HTTP{r.status_code}")
    r=await c.get("/payments/claims",headers=cu)
    check("...nor read finance's record of them", r.status_code==403, f"HTTP{r.status_code}")

    # Attachments: OWN customer files allowed, OTHER customer's denied
    fa={"file":("own.txt",io.BytesIO(b"x"),"text/plain")}
    await c.post("/attachments",headers=d,data={"owner_type":"customer","owner_id":cust},files=fa)
    r=await c.get("/attachments",headers=cu,params={"owner_type":"customer","owner_id":cust})
    check("portal can list its OWN customer files", r.status_code==200, f"HTTP{r.status_code}")
    r=await c.get("/attachments",headers=cu,params={"owner_type":"customer","owner_id":other})
    check("portal DENIED another customer's files", r.status_code==403, f"HTTP{r.status_code}")
    r=await c.get("/attachments",headers=cu,params={"owner_type":"employee","owner_id":cust})
    check("portal DENIED employee HR files", r.status_code==403, f"HTTP{r.status_code}")

    # Internal staff unaffected
    r=await c.get("/customers",headers=s1); check("sales still lists customers", r.status_code==200, f"HTTP{r.status_code}")
    r=await c.get("/notifications",headers=s1); check("sales still gets notifications", r.status_code==200, f"HTTP{r.status_code}")
    r=await c.get("/chat/channels",headers=s1); check("sales still uses chat", r.status_code==200, f"HTTP{r.status_code}")
    r=await c.get("/calendar/events",headers=s1,params={"from":"2026-07-01","to":"2026-07-31"})
    check("sales still sees calendar", r.status_code==200, f"HTTP{r.status_code}")
    r=await c.get("/attendance/me",headers=s1); check("attendance still works", r.status_code==200, f"HTTP{r.status_code}")

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL: print("FAILED:",FAIL); sys.exit(1)
asyncio.run(main())

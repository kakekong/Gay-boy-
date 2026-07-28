"""Stale approval requests: entity moves on but the request stays pending."""
import asyncio, os, sys
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
    r=await c.post("/auth/login",json={"email":e,"password":"test-pass-123"}); return {"Authorization":f"Bearer {r.json()['access_token']}"}

async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    import uuid
    c=httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://t/api/v1",timeout=40)
    s=await login(c,"sales1@demo.local"); d=await login(c,"director@demo.local")
    tag=uuid.uuid4().hex[:6]

    # Build an approved quotation owned by sales1
    cust=J(await c.post("/customers",headers=s,json={"company_name":f"PT Stale {tag}","industry":"mining"}))["id"]
    pr=J(await c.post("/price-requests",headers=s,json={"customer_id":cust,"items":[{"description":"X","qty":1,"uom":"pcs"}]}))["id"]
    await c.post(f"/price-requests/{pr}/submit",headers=s)
    await c.post(f"/price-requests/{pr}/price",headers=d,json={"items":[{"line_no":1,"cost_price":100,"basis":"unit"}]})
    await c.post(f"/price-requests/{pr}/approve",headers=d,json={"items":[{"line_no":1,"sell_price":200,"basis":"unit"}]})
    q=J(await c.post(f"/quotations/from-price-request/{pr}",headers=s))["id"]
    await c.post(f"/quotations/{q}/submit",headers=s)
    await c.post(f"/quotations/{q}/approve",headers=d,json={"notes":""})

    # 1. Sales requests Mark-Won -> pending request created
    r=await c.post(f"/quotations/{q}/won",headers=s)
    check("sales won -> 202 pending", r.status_code==202, str(r.status_code))

    def won_reqs(inbox):
        rows=inbox if isinstance(inbox,list) else inbox.get("items",[])
        return [x for x in rows if x.get("target_type")=="quotation_won" and str(x.get("target_id"))==q]

    inbox=J(await c.get("/approvals",headers=d))
    check("request is in the director inbox", len(won_reqs(inbox))==1, str(len(won_reqs(inbox))))

    # 2. Director instead marks it won DIRECTLY from the quotation page
    r=await c.post(f"/quotations/{q}/won",headers=d)
    check("director direct won -> 200", r.status_code==200, str(r.status_code))
    check("quote is won", J(await c.get(f"/quotations/{q}",headers=s)).get("status")=="won", "not won")

    # 3. THE BUG: is the now-pointless request still sitting in the inbox?
    inbox=J(await c.get("/approvals",headers=d))
    left=won_reqs(inbox)
    check("stale mark-won request cleared from inbox", len(left)==0,
          f"{len(left)} stale request(s) still pending on an already-won quote")

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL: print("FAILED:",FAIL); sys.exit(1)
asyncio.run(main())

"""Link attachments: add a link, list it, redirect on download, delete,
per-owner-type + daily-log ownership, url normalization."""
import asyncio, os, sys, io
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123", STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import httpx, logging; logging.disable(logging.INFO)
PASS, FAIL = [], []
def check(n,c,d=""):
    (PASS if c else FAIL).append(n); print(("  PASS " if c else "  FAIL ")+n+(f"  [{d}]" if d and not c else ""))
async def login(c,e):
    r=await c.post("/auth/login",json={"email":e,"password":"test-pass-123"}); return {"Authorization":f"Bearer {r.json()['access_token']}"}
def J(r):
    try: return r.json()
    except: return {"_":r.text[:150]}
async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    c=httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://t/api/v1",timeout=40)
    s=await login(c,"sales1@demo.local"); s2=await login(c,"sales2@demo.local"); d=await login(c,"director@demo.local")
    cust=J(await c.post("/customers",headers=s,json={"company_name":"PT Link Test","industry":"mining"}))["id"]

    # 1. add a link to a customer (bare domain -> https)
    r=await c.post("/attachments/link",headers=s,json={"owner_type":"customer","owner_id":cust,"url":"drive.google.com/file/abc","label":"Spec sheet"})
    check("add link 201", r.status_code==201, J(r))
    lk=J(r); lid=lk.get("id")
    check("is_link true", lk.get("is_link") is True, str(lk))
    check("url normalized https", (lk.get("external_url") or "").startswith("https://drive.google.com"), str(lk))
    check("download_url is the external url", lk.get("download_url")==lk.get("external_url"), str(lk))
    check("label used as filename", lk.get("filename")=="Spec sheet", str(lk))

    # 2. list shows it alongside files
    f={"file":("a.txt",io.BytesIO(b"hi"),"text/plain")}
    await c.post("/attachments",headers=s,data={"owner_type":"customer","owner_id":cust},files=f)
    rows=J(await c.get("/attachments",headers=d,params={"owner_type":"customer","owner_id":cust}))
    check("list has link + file", len(rows)==2 and any(x.get("is_link") for x in rows) and any(not x.get("is_link") for x in rows), str(rows))

    # 3. download endpoint redirects to the external url (no blob)
    r=await c.get(f"/attachments/{lid}/download",headers=d,follow_redirects=False)
    check("download redirects (3xx)", 300<=r.status_code<400, str(r.status_code))
    check("redirect Location = url", r.headers.get("location","").startswith("https://drive.google.com"), r.headers.get("location"))

    # 4. empty url rejected
    r=await c.post("/attachments/link",headers=s,json={"owner_type":"customer","owner_id":cust,"url":"   "})
    check("empty url rejected", r.status_code==400, str(r.status_code))

    # 5. invalid owner_type rejected
    r=await c.post("/attachments/link",headers=s,json={"owner_type":"nope","owner_id":cust,"url":"x.com"})
    check("bad owner_type rejected", r.status_code==400, str(r.status_code))

    # 6. daily_log ownership: only owner can add a link
    log=J(await c.put("/attendance/daily-log",headers=s,json={"date":"2026-07-22","body":"x","links":[]}))
    logid=log["id"]
    r=await c.post("/attachments/link",headers=s,json={"owner_type":"daily_log","owner_id":logid,"url":"docs.com/1"})
    check("owner can add link to own log", r.status_code==201, J(r))
    r=await c.post("/attachments/link",headers=s2,json={"owner_type":"daily_log","owner_id":logid,"url":"docs.com/evil"})
    check("peer cannot add link to others' log", r.status_code==403, str(r.status_code))

    # 7. delete a link (no file on disk) works
    r=await c.delete(f"/attachments/{lid}",headers=d)
    check("delete link ok", r.status_code in (200,204), str(r.status_code))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL: print("FAILED:",FAIL); sys.exit(1)
asyncio.run(main())

"""Customers can be filtered by industry.

The list's API took an `industry` filter the page never offered. The page
now has an industry picker, each industry with how many of *your* customers
are in it, and the filter matches regardless of capitals (an import may
have written "Cement" beside "cement").
"""
import asyncio, os, sys, uuid
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123",
    STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import httpx, logging; logging.disable(logging.INFO)
TAG = uuid.uuid4().hex[:5].upper()
PASS, FAIL = [], []
def check(n, c, d=""):
    (PASS if c else FAIL).append(n); print(("  PASS " if c else "  FAIL ")+n+(f"  [{d}]" if d and not c else ""))
def J(r):
    try: return r.json()
    except Exception: return {"_": r.text[:200]}


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    from app.core.db import SessionLocal
    from app.models.crm import Customer
    from sqlalchemy import update
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    s1 = await login("sales1@demo.local")
    s2 = await login("sales2@demo.local")
    d = await login("director@demo.local")

    async def make(name, industry):
        return J(await c.post("/customers", headers=s1, json={
            "company_name": f"{name} {TAG}", "industry": industry}))["id"]

    semen = await make("PT Semen", "cement")
    semen2 = await make("PT Semen Dua", "cement")
    tambang = await make("PT Tambang", "mining")
    async with SessionLocal() as s:     # as an import might have written it
        await s.execute(update(Customer).where(Customer.id == uuid.UUID(semen2))
                        .values(industry="Cement"))
        await s.commit()

    def ids(r):
        return {x["id"] for x in J(r).get("data", [])}

    r = await c.get("/customers", headers=s1, params={"q": TAG, "industry": "cement"})
    check("filtering by cement finds both cement customers",
          ids(r) == {semen, semen2}, str(ids(r)))
    check("...including the one written 'Cement'", semen2 in ids(r))
    check("...and not the mining one", tambang not in ids(r))
    r = await c.get("/customers", headers=s1, params={"q": TAG, "industry": "mining"})
    check("filtering by mining finds only it", ids(r) == {tambang}, str(ids(r)))

    mine = {i["industry"]: i["count"] for i in J(await c.get("/customers/industries", headers=s1))}
    check("the picker lists each industry with a count, capitals folded together",
          mine.get("cement", 0) >= 2 and "Cement" not in mine and mine.get("mining", 0) >= 1,
          str(mine))
    all_ = {i["industry"]: i["count"] for i in J(await c.get("/customers/industries", headers=d))}
    other = {i["industry"]: i["count"] for i in J(await c.get("/customers/industries", headers=s2))}
    check("...counting only your own customers (a rep's counts are within the director's)",
          all_.get("cement", 0) >= mine["cement"] and other.get("cement", 0) <= all_["cement"] - 2,
          f"{mine.get('cement')} {other.get('cement')} {all_.get('cement')}")

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

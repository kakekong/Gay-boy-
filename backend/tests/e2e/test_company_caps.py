"""Company names are written in capitals.

"PT Jakarta Prima CRANe" typed on the customer form and "PT JAKARTA PRIMA
CRANE" on the letterhead are the same company; the name is stored the one
way, whatever was typed, for customers and suppliers alike — and names from
before are brought into line on boot.
"""
import asyncio, os, sys, uuid
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123",
    STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import httpx, logging; logging.disable(logging.INFO)
TAG = uuid.uuid4().hex[:5]
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
    from sqlalchemy import text
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=120)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")

    r = await c.post("/customers", headers=d, json={
        "company_name": f"  PT Jakarta   Prima CRANe {TAG} ", "industry": "mining"})
    body = J(r)
    check("a customer typed in mixed case is saved in capitals, spaced once",
          r.status_code in (200, 201) and body.get("company_name") == f"PT JAKARTA PRIMA CRANE {TAG.upper()}",
          f"{r.status_code} {str(body)[:200]}")
    cid = body.get("id")
    r = await c.patch(f"/customers/{cid}", headers=d, json={"company_name": f"pt jakarta prima crane {TAG} tbk"})
    check("...and so is an edit", J(r).get("company_name") == f"PT JAKARTA PRIMA CRANE {TAG.upper()} TBK",
          str(J(r))[:200])

    r = await c.post("/purchasing/suppliers", headers=d, json={"name": f"pt Sumber Logam {TAG}"})
    check("a supplier is saved in capitals",
          J(r).get("name") == f"PT SUMBER LOGAM {TAG.upper()}", f"{r.status_code} {str(J(r))[:200]}")
    r = await c.post("/purchasing/suppliers", headers=d, json={"name": f"PT SUMBER logam {TAG}"})
    check("the same supplier typed another way is caught as a duplicate",
          r.status_code == 409, f"{r.status_code} {str(J(r))[:200]}")

    print("\n── names from before ──")
    async with SessionLocal() as db:
        await db.execute(text(
            "INSERT INTO customers (id, company_name, industry, stage, is_pkp, payment_terms, "
            "lifetime_value, meta, is_deleted, created_at, updated_at) VALUES "
            "(gen_random_uuid(), :n, 'mining', 'lead', false, '{}', 0, '{}', false, now(), now())"),
            {"n": f"PT Lama Sekali {TAG}"})
        await db.commit()
    await ensure_schema()
    async with SessionLocal() as db:
        got = await db.scalar(text("SELECT company_name FROM customers WHERE company_name ILIKE :n"),
                              {"n": f"PT Lama Sekali {TAG}"})
    check("an old mixed-case name is capitalised on boot", got == f"PT LAMA SEKALI {TAG.upper()}", str(got))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

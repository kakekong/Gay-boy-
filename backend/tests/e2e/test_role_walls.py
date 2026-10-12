"""Who can reach what — checked at the server, not trusted to the sidebar.

Found by calling every read endpoint as each role:

* The search bar handed purchasing every customer in the book (type "pt"),
  with their quotations and customer POs — purchasing is customer-blind.
* HR could read customers, customer POs, quotations, price requests and
  projects; their work is people, attendance and chat.
* A customer's or supplier's **portal** login could call the AI tools (the
  at-risk deal list with customer names, a project's profit, coaching notes),
  the commission endpoints and the sidebar badges.
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
    from sqlalchemy import select
    from app.core.db import SessionLocal
    from app.core.security import hash_password
    from app.models.user import User
    from app.models.purchasing import Supplier
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    s1 = await login("sales1@demo.local")
    pur = await login("purchasing@demo.local")
    hr = await login("hr@demo.local")
    adm = await login("admin@demo.local")

    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Tembok {TAG}", "industry": "mining"}))
    pr = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust["id"], "items": [{"description": f"TEMBOK BOLT {TAG}", "qty": 1, "uom": "pcs"}]}))
    await c.post(f"/price-requests/{pr['id']}/submit", headers=s1)
    sup = J(await c.post("/purchasing/suppliers", headers=pur, json={"name": f"PT Pemasok Tembok {TAG}"}))

    async with SessionLocal() as s:
        for email, role, kw in ((f"sup-{TAG}@portal.test", "supplier", {"linked_supplier_id": uuid.UUID(sup["id"])}),
                                (f"cus-{TAG}@portal.test", "customer", {"linked_customer_id": uuid.UUID(cust["id"])})):
            s.add(User(email=email.lower(), full_name=f"Portal {role}", role=role,
                       password_hash=hash_password("test-pass-123"), is_active=True, **kw))
        await s.commit()
    sp = await login(f"sup-{TAG}@portal.test".lower())
    cp = await login(f"cus-{TAG}@portal.test".lower())

    def groups(body):
        return {g["label"]: g["items"] for g in body.get("groups", [])}

    print("\n── the search bar ──")
    g = groups(J(await c.get("/search", headers=pur, params={"q": "PT"})))
    check("purchasing: no customers, quotations or customer POs in search",
          not ({"Customers", "Quotations", "Customer POs"} & set(g)), str(list(g)))
    g = groups(J(await c.get("/search", headers=pur, params={"q": TAG})))
    prs = g.get("Price requests", [])
    check("purchasing: a price request is found by its line...", any(x["label"] == pr["number"] for x in prs),
          str(prs)[:200])
    check("...without the customer's name", all("TEMBOK" not in (x.get("sublabel") or "").replace(
          f"TEMBOK BOLT {TAG}", "") for x in prs) and f"PT TEMBOK {TAG}" not in str(prs), str(prs)[:200])
    g = groups(J(await c.get("/search", headers=hr, params={"q": "PT"})))
    check("HR: no customers, quotations, customer POs, price requests or projects",
          not ({"Customers", "Quotations", "Customer POs", "Price requests", "Projects"} & set(g)),
          str(list(g)))
    g = groups(J(await c.get("/search", headers=adm, params={"q": "PT"})))
    check("admin: no suppliers or supplier price requests (kept off the vendor side)",
          not ({"Suppliers", "Supplier price requests"} & set(g)), str(list(g)))
    g = groups(J(await c.get("/search", headers=s1, params={"q": f"PT TEMBOK {TAG}"})))
    check("sales still finds their own customer", any(f"PT TEMBOK {TAG}" == x["label"] for x in g.get("Customers", [])),
          str(list(g)))
    for who, h in (("supplier portal", sp), ("customer portal", cp)):
        r = await c.get("/search", headers=h, params={"q": "PT"})
        check(f"{who}: search is closed", r.status_code == 403, str(r.status_code))

    print("\n── purchasing is customer-blind ──")
    for path in ("/customers", f"/customers/{cust['id']}", "/quotations", "/customer-pos",
                 "/dashboard/ai-command", "/ai/deal-risk"):
        r = await c.get(path, headers=pur)
        check(f"purchasing: {path.split('/')[1]}{'/…' if path.count('/') > 1 else ''} refused",
              r.status_code == 403, str(r.status_code))
    r = await c.get(f"/price-requests/{pr['id']}", headers=pur)
    check("...but still costs price requests", r.status_code == 200, str(r.status_code))
    r = await c.get("/operation/projects", headers=pur)
    check("...and still sees jobs", r.status_code == 200, str(r.status_code))

    print("\n── HR works people ──")
    for path in ("/customers", "/quotations", "/customer-pos", "/price-requests",
                 "/operation/projects", "/operation/work-orders"):
        r = await c.get(path, headers=hr)
        check(f"HR: {path} refused", r.status_code == 403, str(r.status_code))
    r = await c.get("/attendance/me/today", headers=hr)
    check("...attendance still works", r.status_code in (200, 404), str(r.status_code))

    print("\n── portal logins ──")
    for who, h in (("supplier portal", sp), ("customer portal", cp)):
        for path in ("/ai/deal-risk", "/ai/loss-analysis/patterns", "/ai/supply-risk",
                     f"/ai/lead-score/{cust['id']}", "/commissions", "/commissions/summary",
                     "/nav/badges", "/notifications"):
            r = await c.get(path, headers=h)
            check(f"{who}: {path.split('/')[1]}/{path.split('/')[2] if path.count('/') > 1 else ''} refused",
                  # 404 would also be unreachable; 401/403 is what these answer.
                  r.status_code in (401, 403, 404), str(r.status_code))
    r = await c.get("/portal/supplier/me", headers=sp)
    check("the supplier portal itself still works", r.status_code == 200, str(r.status_code))
    r = await c.get("/portal/customer/me", headers=cp)
    check("the customer portal itself still works", r.status_code == 200, str(r.status_code))

    print("\n── the AI tools, by role ──")
    r = await c.get("/ai/deal-risk", headers=s1)
    check("every rep's at-risk deals: not for a single rep", r.status_code == 403, str(r.status_code))
    r = await c.get("/ai/deal-risk", headers=d)
    check("...the director's", r.status_code == 200, str(r.status_code))
    me = J(await c.get("/auth/me", headers=s1))
    dme = J(await c.get("/auth/me", headers=d))
    r = await c.get(f"/ai/coach/{me['id']}", headers=s1)
    check("a rep reads their own coaching", r.status_code == 200, str(r.status_code))
    r = await c.get(f"/ai/coach/{dme['id']}", headers=s1)
    check("...not someone else's", r.status_code == 403, str(r.status_code))
    r = await c.get(f"/ai/lead-score/{cust['id']}", headers=s1)
    check("a rep scores their own customer", r.status_code == 200, str(r.status_code))
    s2 = await login("sales2@demo.local")
    r = await c.get(f"/ai/lead-score/{cust['id']}", headers=s2)
    check("...not another rep's", r.status_code == 403, str(r.status_code))
    r = await c.get("/ai/supply-risk", headers=pur)
    check("supply risk is purchasing's", r.status_code == 200, str(r.status_code))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

"""Sales may ask to skip the drawing stage; the director decides.

The rep is often first to know a customer is buying a standard part with
nothing to draw. They ask, with a reason; nothing is skipped until the
director says so — from the Approvals inbox or right on the drawings card —
and the rep hears back either way.

* Only the customer's own rep may ask.
* While it waits, the project says so (who asked, why), and asking again
  doesn't file a second request.
* Declined: the stage stays; the rep is told why.
* Approved: the stage is skipped and the project moves to drawing approved.
* The director skipping it directly answers a waiting request too, instead
  of leaving it in the queue.
"""
import asyncio, os, sys, uuid
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123",
    STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import httpx, logging; logging.disable(logging.INFO)
PASS, FAIL = [], []
def check(n, c, d=""):
    (PASS if c else FAIL).append(n); print(("  PASS " if c else "  FAIL ")+n+(f"  [{d}]" if d and not c else ""))
def J(r):
    try: return r.json()
    except Exception: return {"_": r.text[:200]}


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)
    tag = uuid.uuid4().hex[:5]

    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    s1 = await login("sales1@demo.local")
    s2 = await login("sales2@demo.local")
    pur = await login("purchasing@demo.local")

    async def a_project(label):
        cust = J(await c.post("/customers", headers=s1, json={
            "company_name": f"PT Lewati {label} {tag}", "industry": "mining"}))["id"]
        pr = J(await c.post("/price-requests", headers=s1, json={
            "customer_id": cust, "items": [{"description": f"BEARING 6205 {label} {tag}",
                                            "qty": 10, "uom": "pcs"}]}))["id"]
        await c.post(f"/price-requests/{pr}/submit", headers=s1)
        await c.post(f"/price-requests/{pr}/price", headers=pur, json={
            "items": [{"line_no": 1, "cost_price": 50_000, "basis": "unit"}]})
        await c.post(f"/price-requests/{pr}/approve", headers=d, json={
            "items": [{"line_no": 1, "sell_price": 80_000, "basis": "unit"}]})
        q = J(await c.post(f"/quotations/from-price-request/{pr}", headers=s1))["id"]
        await c.post(f"/quotations/{q}/submit", headers=s1)
        await c.post(f"/quotations/{q}/approve", headers=d, json={"notes": ""})
        cpo = J(await c.post("/customer-pos", headers=s1, json={
            "customer_id": cust, "quotation_id": q, "number": f"PO-{label}-{tag}",
            "items": [{"description": f"BEARING 6205 {label} {tag}", "qty": 10, "unit_price": 80_000}],
            "is_downpayment": False}))["id"]
        await c.post(f"/quotations/{q}/won", headers=d)
        return J(await c.post(f"/customer-pos/{cpo}/approve", headers=d, json={"notes": ""}))["project_id"]

    async def project(pid, who=None):
        return J(await c.get(f"/operation/projects/{pid}/full", headers=who or s1))["project"]

    async def waiting(pid):
        rows = J(await c.get("/approvals", headers=d))
        rows = rows if isinstance(rows, list) else rows.get("items", [])
        return [r for r in rows if r.get("target_type") == "project_skip_drawing"
                and r.get("target_id") == pid]           # the inbox lists only what waits

    async def bell(who, pid):
        items = J(await c.get("/notifications", headers=who)).get("items", [])
        return [i for i in items if i.get("kind") == "approval_decided"
                and i.get("link") == f"/projects/{pid}"]

    proj = await a_project("A")
    why = f"Standard bearing from the catalogue — nothing to draw {tag}"

    print("\n── sales asks ──")
    r = await c.post(f"/operation/projects/{proj}/skip-drawing", headers=s2, json={"reason": why})
    check("another rep can't ask on this customer's job", r.status_code == 403, str(r.status_code))
    r = await c.post(f"/operation/projects/{proj}/skip-drawing", headers=s1, json={"reason": why})
    check("the customer's rep asks, and it goes to the director", r.status_code == 202
          and J(r).get("status") == "pending_approval", f"{r.status_code} {J(r)}"[:200])
    p = await project(proj)
    check("...nothing is skipped yet", p.get("drawing_skipped") is False, str(p.get("drawing_skipped")))
    pend = p.get("drawing_skip_pending") or {}
    check("...the project says it's waiting, who asked and why",
          pend.get("reason") == why and pend.get("requested_by") == "Sales One", str(pend)[:200])
    await c.post(f"/operation/projects/{proj}/skip-drawing", headers=s1, json={"reason": why})
    check("asking twice doesn't file a second request", len(await waiting(proj)) == 1,
          str(len(await waiting(proj))))

    print("\n── the director declines ──")
    req = (await waiting(proj))[0]["id"]
    r = await c.post(f"/approvals/{req}/reject", headers=d,
                     params={"notes": "Customer wants a drawing for their records"})
    p = await project(proj)
    check("declined: the stage stays", r.status_code == 200 and p.get("drawing_skipped") is False
          and p.get("drawing_skip_pending") is None, f"{r.status_code} {p.get('drawing_skip_pending')}")
    told = await bell(s1, proj)
    check("...and the rep is told, with the reason, linked to the project",
          told and "rejected" in told[0]["title"] and "skip-the-drawing" in told[0]["title"]
          and "records" in told[0]["body"], str(told)[:250])

    print("\n── asked again, approved ──")
    await c.post(f"/operation/projects/{proj}/skip-drawing", headers=s1, json={"reason": why})
    req = (await waiting(proj))[0]["id"]
    r = await c.post(f"/approvals/{req}/approve", headers=d)
    p = await project(proj, d)
    check("approved: the drawing stage is skipped", r.status_code == 200
          and p.get("drawing_skipped") is True and p.get("drawing_skip_reason") == why,
          f"{r.status_code} {p.get('drawing_skipped')} {p.get('drawing_skip_reason')!r}")
    check("...and the project moves to drawing approved", p.get("status") == "drawing_approved",
          p.get("status"))
    told = await bell(s1, proj)
    check("...and the rep is told it was approved", any("approved" in i["title"] for i in told),
          str(told)[:250])

    print("\n── the director skips it directly while a request waits ──")
    proj2 = await a_project("B")
    await c.post(f"/operation/projects/{proj2}/skip-drawing", headers=s1, json={"reason": why})
    check("a request is waiting", len(await waiting(proj2)) == 1)
    r = await c.post(f"/operation/projects/{proj2}/skip-drawing", headers=d, json={"reason": why})
    check("the director skips it on the project page", r.status_code == 200
          and J(r).get("drawing_skipped") is True, f"{r.status_code} {J(r)}"[:200])
    check("...which answers the waiting request too", len(await waiting(proj2)) == 0,
          str(len(await waiting(proj2))))
    check("...and the rep hears it was approved",
          any("approved" in i["title"] for i in await bell(s1, proj2)))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

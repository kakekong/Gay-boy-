"""Customer POs waiting for approval are in finance's inbox too.

A customer PO was the director's alone to approve. Finance now sees each one
in their Approvals inbox (and the bell) as well, and may approve or reject
it — from the inbox or the PO's own page. Whoever acts first decides it, and
it leaves both inboxes. A manager still may not.
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
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d, fin, s1, pur, mgr = [await login(f"{x}@demo.local")
                            for x in ("director", "finance", "sales1", "purchasing", "manager")]

    async def customer_po(label):
        cust = J(await c.post("/customers", headers=s1, json={
            "company_name": f"PT Inbox {label} {TAG}", "industry": "mining"}))["id"]
        pr = J(await c.post("/price-requests", headers=s1, json={
            "customer_id": cust, "items": [{"description": f"CHAIN {TAG}", "qty": 1, "uom": "pcs"}]}))
        await c.post(f"/price-requests/{pr['id']}/submit", headers=s1)
        await c.post(f"/price-requests/{pr['id']}/price", headers=pur, json={
            "items": [{"line_no": 1, "cost_price": 500_000, "basis": "unit"}]})
        await c.post(f"/price-requests/{pr['id']}/approve", headers=d, json={
            "items": [{"line_no": 1, "sell_price": 1_000_000, "basis": "unit"}]})
        q = J(await c.post(f"/quotations/from-price-request/{pr['id']}", headers=s1))
        await c.post(f"/quotations/{q['id']}/submit", headers=s1)
        await c.post(f"/quotations/{q['id']}/approve", headers=d, json={"notes": ""})
        return J(await c.post("/customer-pos", headers=s1, json={
            "customer_id": cust, "quotation_id": q["id"], "number": f"PO-{label}-{TAG}",
            "items": [{"description": f"CHAIN {TAG}", "qty": 1, "unit_price": 1_000_000}],
            "is_downpayment": False}))

    async def inbox(who, po):
        rows = J(await c.get("/approvals", headers=who))
        rows = rows if isinstance(rows, list) else rows.get("items", [])
        return [r for r in rows if r.get("target_id") == po["id"]]

    async def status_of(po):
        return J(await c.get(f"/customer-pos/{po['id']}", headers=d)).get("status")

    print("\n── finance sees it ──")
    po = await customer_po("A")
    check("filed by sales, it waits for approval", po.get("status") == "pending_approval",
          str(po.get("status")))
    check("it's in the director's inbox", len(await inbox(d, po)) == 1)
    check("...and in finance's", len(await inbox(fin, po)) == 1)
    bell = J(await c.get("/notifications", headers=fin)).get("items", [])
    check("...and finance's bell", any(po["id"] in str(i) or po["number"] in str(i) for i in bell)
          or any(i.get("kind") == "approval" for i in bell))
    check("a manager's inbox doesn't have it", not await inbox(mgr, po))

    print("\n── finance approves from the inbox ──")
    r = await c.post(f"/approvals/{(await inbox(fin, po))[0]['id']}/approve", headers=fin)
    check("finance approves it", r.status_code == 200, f"{r.status_code} {J(r)}"[:200])
    check("...the PO is approved", await status_of(po) == "approved", await status_of(po))
    check("...and it has left both inboxes", not await inbox(fin, po) and not await inbox(d, po))

    print("\n── finance rejects from the PO page ──")
    po = await customer_po("B")
    r = await c.post(f"/customer-pos/{po['id']}/reject", headers=fin,
                     json={"notes": "Nomor PO tidak sesuai dokumen"})
    check("finance rejects it on the PO's page", r.status_code == 200, f"{r.status_code} {J(r)}"[:200])
    check("...it's rejected and out of the director's inbox",
          await status_of(po) == "rejected" and not await inbox(d, po))

    print("\n── the director still can ──")
    po = await customer_po("C")
    r = await c.post(f"/customer-pos/{po['id']}/approve", headers=d, json={"notes": ""})
    check("the director approves one", r.status_code == 200, f"{r.status_code} {J(r)}"[:200])
    check("...and it leaves finance's inbox too", not await inbox(fin, po))

    po = await customer_po("D")
    r = await c.post(f"/customer-pos/{po['id']}/approve", headers=mgr, json={"notes": ""})
    check("a manager still can't", r.status_code == 403, str(r.status_code))
    req = (await inbox(d, po))[0]["id"]
    r = await c.post(f"/approvals/{req}/approve", headers=mgr)
    check("...not from the inbox either", r.status_code in (400, 403), str(r.status_code))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

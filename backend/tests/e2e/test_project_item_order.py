"""A project's Order card lists its lines in an order people set.

Drag line 3 to the top and it stays there, for everybody. Only the listing
moves: every line keeps its price-request number, which supplier requests
and POs refer to. A line the order doesn't name, or one named twice, is
refused; clearing the order puts the request's own back. Sales, who don't
see the card, can't reorder it.
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
    d, s1, pur = [await login(f"{x}@demo.local") for x in ("director", "sales1", "purchasing")]

    names = [f"Roller Chain RS 60 {TAG}", f"Sprocket B 60 1R 25T {TAG}", f"Connecting Link {TAG}"]
    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Urutan {TAG}", "industry": "mining"}))["id"]
    pr = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust, "items": [{"description": n, "qty": 1, "uom": "pcs"} for n in names]}))
    await c.post(f"/price-requests/{pr['id']}/submit", headers=s1)
    await c.post(f"/price-requests/{pr['id']}/price", headers=pur, json={
        "items": [{"line_no": i + 1, "cost_price": 100_000, "basis": "unit"} for i in range(3)]})
    await c.post(f"/price-requests/{pr['id']}/approve", headers=d, json={
        "items": [{"line_no": i + 1, "sell_price": 150_000, "basis": "unit"} for i in range(3)]})
    q = J(await c.post(f"/quotations/from-price-request/{pr['id']}", headers=s1))
    await c.post(f"/quotations/{q['id']}/submit", headers=s1)
    await c.post(f"/quotations/{q['id']}/approve", headers=d, json={"notes": ""})
    po = J(await c.post("/customer-pos", headers=s1, json={
        "customer_id": cust, "quotation_id": q["id"], "number": f"PO-{TAG}",
        "items": [{"description": n, "qty": 1, "unit_price": 150_000} for n in names],
        "is_downpayment": False}))
    pid = J(await c.post(f"/customer-pos/{po['id']}/approve", headers=d, json={"notes": ""}))["project_id"]

    async def card(who=pur):
        return J(await c.get(f"/operation/projects/{pid}/full", headers=who))["price_request"]

    C = await card()
    check("the card starts in the request's order",
          [i["line_no"] for i in C["items"]] == [1, 2, 3] and not C["custom_order"])

    r = await c.put(f"/operation/projects/{pid}/item-order", headers=pur, json={"order": [3, 1, 2]})
    check("purchasing moves line 3 to the top", r.status_code == 200, f"{r.status_code} {J(r)}"[:200])
    C = await card()
    check("...it's listed first now", [i["line_no"] for i in C["items"]] == [3, 1, 2]
          and C["items"][0]["description"] == names[2], str([i["line_no"] for i in C["items"]]))
    check("...each line keeps its own number", sorted(i["line_no"] for i in C["items"]) == [1, 2, 3])
    C = await card(d)
    check("...and the director sees the same order", [i["line_no"] for i in C["items"]] == [3, 1, 2]
          and C["custom_order"])

    r = await c.put(f"/operation/projects/{pid}/item-order", headers=pur, json={"order": [3, 1]})
    check("an order that leaves a line out is refused", r.status_code == 400, str(r.status_code))
    r = await c.put(f"/operation/projects/{pid}/item-order", headers=pur, json={"order": [3, 3, 1]})
    check("...so is one that names a line twice", r.status_code == 400, str(r.status_code))
    r = await c.put(f"/operation/projects/{pid}/item-order", headers=s1, json={"order": [1, 2, 3]})
    check("sales can't reorder it", r.status_code == 403, str(r.status_code))

    r = await c.put(f"/operation/projects/{pid}/item-order", headers=d, json={"order": None})
    C = await card()
    check("clearing it puts the request's order back",
          r.status_code == 200 and [i["line_no"] for i in C["items"]] == [1, 2, 3]
          and not C["custom_order"], str([i["line_no"] for i in C["items"]]))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

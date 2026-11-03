"""The deal check includes the supplier POs.

The Order card's check compared the price request, quotation and customer PO,
and the supplier POs only when each line pointed back at the request — a PO
typed on the PO page for the job was left out. Now:

* A supplier PO raised on the job counts, its lines matched by wording.
* All in order, the card says the supplier PO matches too.
* Ordering a different quantity, or in a different unit, is pointed out.
* An item no supplier PO carries is named.
"""
import asyncio, os, sys, uuid
from datetime import date
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
    d = await login("director@demo.local")
    s1 = await login("sales1@demo.local")
    pur = await login("purchasing@demo.local")

    async def rep(**where):
        return J(await c.get("/consistency", headers=d, params=where))
    def spo_check(r):
        return next((x for x in r.get("checks", []) if x["key"] == "supplier_po_qty"), None)

    chain_name, belt = f"CHAIN 32A-2 {TAG}", f"V-BELT B52 {TAG}"
    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT CEK PO {TAG}", "industry": "mining"}))["id"]
    pr = J(await c.post("/price-requests", headers=s1, json={"customer_id": cust, "items": [
        {"description": chain_name, "qty": 6, "uom": "meter"},
        {"description": belt, "qty": 4, "uom": "pcs"}]}))["id"]
    await c.post(f"/price-requests/{pr}/submit", headers=s1)
    await c.post(f"/price-requests/{pr}/price", headers=pur, json={"items": [
        {"line_no": 1, "cost_price": 1_000_000, "basis": "unit"},
        {"line_no": 2, "cost_price": 100_000, "basis": "unit"}]})
    await c.post(f"/price-requests/{pr}/approve", headers=d, json={"items": [
        {"line_no": 1, "sell_price": 2_900_000, "basis": "unit"},
        {"line_no": 2, "sell_price": 300_000, "basis": "unit"}]})
    q = J(await c.post(f"/quotations/from-price-request/{pr}", headers=s1))
    await c.post(f"/quotations/{q['id']}/submit", headers=s1)
    await c.post(f"/quotations/{q['id']}/approve", headers=d, json={"notes": ""})
    cpo = J(await c.post("/customer-pos", headers=s1, json={
        "customer_id": cust, "quotation_id": q["id"], "number": f"CPO-{TAG}",
        "items": [{"description": chain_name, "qty": 6, "uom": "meter", "unit_price": 2_900_000, "line_no": 1},
                  {"description": belt, "qty": 4, "uom": "pcs", "unit_price": 300_000, "line_no": 2}],
        "is_downpayment": False}))
    await c.post(f"/quotations/{q['id']}/won", headers=d)
    pid = J(await c.post(f"/customer-pos/{cpo['id']}/approve", headers=d, json={"notes": ""})).get("project_id")
    check("the deal becomes a project", bool(pid), str(pid))

    print("\n── a supplier PO typed on the job, no link back to the request ──")
    sup = J(await c.post("/purchasing/suppliers", headers=pur, json={"name": f"PT RANTAI {TAG}"}))["id"]
    po1 = J(await c.post("/purchasing/po", headers=d, json={
        "supplier_id": sup, "project_id": pid, "po_date": date.today().isoformat(),
        "items": [{"description": chain_name, "qty": 6, "uom": "meter",
                   "unit_price": 1_000_000, "amount": 6_000_000},
                  {"description": belt, "qty": 4, "uom": "pcs",
                   "unit_price": 100_000, "amount": 400_000}],
        "total": 6_400_000}))
    r = await rep(project_id=pid)
    so = spo_check(r)
    check("it is part of the check", so is not None
          and any(x["number"] == po1.get("number") for x in (r["documents"].get("supplier_pos") or [])),
          str(r.get("documents", {}).get("supplier_pos"))[:200])
    check("...and with everything ordered as needed, nothing is flagged",
          so is not None and so["lines"] == [], str(so)[:300])
    for where in ({"price_request_id": pr}, {"quotation_id": q["id"]}, {"customer_po_id": cpo["id"]}):
        rr = await rep(**where)
        check(f"from the {list(where)[0].replace('_id', '').replace('_', ' ')} too",
              any(x["number"] == po1.get("number") for x in (rr["documents"].get("supplier_pos") or [])))

    print("\n── ordered short, in another unit, and an item left off ──")
    await c.patch(f"/purchasing/po/{po1['id']}", headers=d, json={"items": [
        {"description": chain_name, "qty": 5, "uom": "pcs", "unit_price": 1_000_000, "amount": 5_000_000}],
        "total": 5_000_000})
    so = spo_check(await rep(project_id=pid))
    by_desc = {ln["description"]: ln for ln in (so or {}).get("lines", [])}
    ch = by_desc.get(chain_name, {})
    fields = {f["field"]: f for f in ch.get("fields", [])}
    check("5 ordered where the job needs 6 is pointed out",
          fields.get("qty") == {"field": "qty", "left": 6.0, "right": 5.0}, str(ch))
    check("...ordered in pcs where the job is in meter, too",
          fields.get("uom") == {"field": "uom", "left": "meter", "right": "pcs"}, str(ch))
    check("...and the belt no supplier PO carries is named",
          by_desc.get(belt, {}).get("change") == "only_left", str(by_desc.get(belt)))

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

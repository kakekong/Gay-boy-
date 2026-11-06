"""Two things about a supplier PO and the job it belongs to.

**Clear test data deletes suppliers.** A supplier could not be picked there,
and the database keeps none of its POs, quotes or RFQs without it. Now it can,
and takes those with it — named in the preview first — with the books put
back the way they were. The job the PO was for stays.

**"No project" lets go of the job.** A PO raised from a job's price request
kept naming that request after the project was taken off it — the job's page
and deal check went on counting it. Taking it off the job (to keep as stock
when another supplier fills the job) now leaves the job alone.
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

STOCK, UNBILLED = "110401", "2102-03"


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    from app.api.v1.endpoints.maintenance import CONFIRM_PHRASE
    from app.core.db import SessionLocal
    from app.models.account import Account
    from sqlalchemy import select
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    s1 = await login("sales1@demo.local")
    pur = await login("purchasing@demo.local")

    async def bal():
        async with SessionLocal() as s:
            rows = (await s.scalars(select(Account).where(Account.account_no.in_([STOCK, UNBILLED])))).all()
            return {a.account_no: float(a.balance or 0) for a in rows}

    # A won job with a price request.
    item = f"BEARING {TAG}"
    cust = J(await c.post("/customers", headers=s1, json={"company_name": f"PT DUA {TAG}", "industry": "mining"}))["id"]
    pr = J(await c.post("/price-requests", headers=s1, json={"customer_id": cust, "items": [
        {"description": item, "qty": 10, "uom": "pcs"}]}))["id"]
    await c.post(f"/price-requests/{pr}/submit", headers=s1)
    await c.post(f"/price-requests/{pr}/price", headers=pur, json={"items": [
        {"line_no": 1, "cost_price": 100_000, "basis": "unit"}]})
    await c.post(f"/price-requests/{pr}/approve", headers=d, json={"items": [
        {"line_no": 1, "sell_price": 200_000, "basis": "unit"}]})
    q = J(await c.post(f"/quotations/from-price-request/{pr}", headers=s1))
    await c.post(f"/quotations/{q['id']}/submit", headers=s1)
    await c.post(f"/quotations/{q['id']}/approve", headers=d, json={"notes": ""})
    cpo = J(await c.post("/customer-pos", headers=s1, json={
        "customer_id": cust, "quotation_id": q["id"], "number": f"CPO-{TAG}",
        "items": [{"description": item, "qty": 10, "unit_price": 200_000, "line_no": 1}],
        "is_downpayment": False}))
    await c.post(f"/quotations/{q['id']}/won", headers=d)
    pid = J(await c.post(f"/customer-pos/{cpo['id']}/approve", headers=d, json={"notes": ""})).get("project_id")

    async def job_pos():
        page = J(await c.get(f"/operation/projects/{pid}/full", headers=d))
        return [x["number"] for x in (page.get("data", page).get("supplier_pos") or [])]
    async def deal_pos():
        r = J(await c.get("/consistency", headers=d, params={"project_id": pid}))
        return [x["number"] for x in (r.get("documents") or {}).get("supplier_pos") or []]

    print("\n── one job, two suppliers: the first PO kept as stock ──")
    sup_a = J(await c.post("/purchasing/suppliers", headers=pur, json={"name": f"PT PERTAMA {TAG}"}))["id"]
    sup_b = J(await c.post("/purchasing/suppliers", headers=pur, json={"name": f"PT KEDUA {TAG}"}))["id"]
    line = {"description": item, "qty": 10, "uom": "pcs", "unit_price": 100_000, "amount": 1_000_000,
            "source_pr_id": pr, "source_line_no": 1}
    po_a = J(await c.post("/purchasing/po", headers=d, json={
        "supplier_id": sup_a, "project_id": pid, "price_request_id": pr,
        "po_date": date.today().isoformat(), "items": [line], "total": 1_000_000}))
    po_b = J(await c.post("/purchasing/po", headers=d, json={
        "supplier_id": sup_b, "project_id": pid, "price_request_id": pr,
        "po_date": date.today().isoformat(), "items": [line], "total": 1_000_000}))
    check("both POs are on the job", {po_a["number"], po_b["number"]} <= set(await job_pos()),
          str(await job_pos()))
    r = await c.patch(f"/purchasing/po/{po_a['id']}", headers=d, json={"project_id": None})
    check("the first is taken off the job (No project)", r.status_code == 200, f"{r.status_code} {J(r)}"[:160])
    check("...and the job's page no longer counts it",
          po_a["number"] not in await job_pos() and po_b["number"] in await job_pos(), str(await job_pos()))
    check("...nor its deal check", po_a["number"] not in await deal_pos(), str(await deal_pos()))
    detail = J(await c.get(f"/purchasing/po/{po_a['id']}", headers=d))
    check("...it is a stock order now: no project, no price request",
          not detail.get("project_id") and not detail.get("price_request_id")
          and not any(i.get("source_pr_id") for i in detail.get("items", [])), str(detail)[:200])

    print("\n── one raised from the request with no project: Not assigned yet, yet counted ──")
    po_c = J(await c.post("/purchasing/po", headers=d, json={
        "supplier_id": sup_b, "price_request_id": pr,
        "po_date": date.today().isoformat(), "items": [line], "total": 1_000_000}))
    detail = J(await c.get(f"/purchasing/po/{po_c['id']}", headers=d))
    check("it has no project, but the job counts it through its price request",
          not detail.get("project_id") and po_c["number"] in await job_pos()
          and (detail.get("implied_project") or {}).get("id") == pid, str(detail.get("implied_project")))
    r = await c.patch(f"/purchasing/po/{po_c['id']}", headers=pur, json={"project_id": None})
    check("purchasing taking it off goes to the director, the job still counts it",
          r.status_code in (200, 202) and po_c["number"] in await job_pos(), f"{r.status_code} {J(r)}"[:160])
    r = await c.patch(f"/purchasing/po/{po_c['id']}", headers=d, json={"project_id": None})
    detail = J(await c.get(f"/purchasing/po/{po_c['id']}", headers=d))
    check("the director takes it off: the job's page no longer counts it",
          r.status_code == 200 and po_c["number"] not in await job_pos()
          and not detail.get("implied_project") and not detail.get("price_request_id"),
          f"{r.status_code} {await job_pos()} {detail.get('implied_project')}")
    check("...nor its deal check", po_c["number"] not in await deal_pos(), str(await deal_pos()))

    print("\n── Clear test data deletes a supplier ──")
    await c.post(f"/purchasing/suppliers/{sup_a}/contacts", headers=pur, json={"name": f"Pak {TAG}"})
    b0 = await bal()
    await c.post(f"/purchasing/po/{po_a['id']}/gr", headers=pur, json={"items": [{"description": item, "qty": 10}]})
    b1 = await bal()
    check("the first supplier's goods were received onto the books",
          round(b1[STOCK] - b0[STOCK], 2) == 1_000_000, str(round(b1[STOCK] - b0[STOCK], 2)))
    r = await c.get("/maintenance/records", headers=d, params={"type": "supplier", "q": f"PERTAMA {TAG}"})
    rows = J(r)
    check("suppliers can be found to pick", r.status_code == 200 and any(x["id"] == sup_a for x in rows),
          f"{r.status_code} {str(rows)[:160]}")
    r = await c.post("/maintenance/records/preview", headers=d, json={"targets": [{"type": "supplier", "id": sup_a}]})
    pv = J(r)
    named = {x["number"] for x in pv.get("documents", [])}
    check("the preview names the supplier and the PO going with it",
          r.status_code == 200 and f"PT PERTAMA {TAG}" in named and po_a["number"] in named
          and pv["counts"].get("suppliers") == 1, f"{r.status_code} {named} {pv.get('counts')}"[:300])
    check("...but not the other supplier's PO, nor the job",
          po_b["number"] not in named and pv["counts"].get("projects", 0) == 0, str(named))
    r = await c.post("/maintenance/records/delete", headers=d, json={
        "targets": [{"type": "supplier", "id": sup_a}], "confirm": CONFIRM_PHRASE, "allow_financial": True})
    check("deleted", r.status_code == 200, f"{r.status_code} {J(r)}"[:200])
    b2 = await bal()
    r = await c.get(f"/purchasing/suppliers/{sup_a}", headers=pur)
    check("...the supplier is gone", r.status_code == 404, str(r.status_code))
    r = await c.get(f"/purchasing/po/{po_a['id']}", headers=pur)
    check("...with its PO", r.status_code == 404, str(r.status_code))
    check("...and the books are put back the way they were", round(b2[STOCK] - b0[STOCK], 2) == 0
          and round(b2[UNBILLED] - b0[UNBILLED], 2) == 0, f"{b2[STOCK] - b0[STOCK]} {b2[UNBILLED] - b0[UNBILLED]}")
    check("...while the job and the other supplier's PO stay", po_b["number"] in await job_pos(),
          str(await job_pos()))

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

"""Quotations waiting for the director show up in the approval inbox, named.

Two ways they used to go missing, both from one variable in the inbox: the
row label was set in some branches and not others. A quotation row either
showed the previous row's number (a supplier PO's — so the director read it as
a purchasing request, and saw no quotation waiting), or, when a quotation was
the oldest request in the queue, the label was read before anything set it
and the whole inbox failed — which the page showed as "inbox zero".
"""
import asyncio, os, sys, uuid
from datetime import datetime, timedelta, UTC
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123",
    STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import httpx, logging; logging.disable(logging.INFO)
TAG = uuid.uuid4().hex[:6].upper()
PASS, FAIL = [], []
def check(n, c, d=""):
    (PASS if c else FAIL).append(n); print(("  PASS " if c else "  FAIL ")+n+(f"  [{d}]" if d and not c else ""))
def J(r):
    try: return r.json()
    except Exception: return {"_": r.text[:200]}


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                          base_url="http://t/api/v1", timeout=180)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    s1 = await login("sales1@demo.local")
    pur = await login("purchasing@demo.local")

    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Kotak {TAG}", "industry": "mining"}))["id"]
    pr = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust, "items": [{"description": f"BOLT {TAG}", "qty": 5, "uom": "pcs"}]}))["id"]
    await c.post(f"/price-requests/{pr}/submit", headers=s1)
    await c.post(f"/price-requests/{pr}/price", headers=pur, json={
        "items": [{"line_no": 1, "cost_price": 1000, "basis": "unit"}]})
    await c.post(f"/price-requests/{pr}/approve", headers=d, json={
        "items": [{"line_no": 1, "sell_price": 2000, "basis": "unit"}]})
    q = J(await c.post(f"/quotations/from-price-request/{pr}", headers=s1))
    r = await c.post(f"/quotations/{q['id']}/submit", headers=s1)
    check("sales submits a quotation", r.status_code == 200 and J(r)["status"] == "pending_approval",
          f"{r.status_code} {str(J(r))[:150]}")

    # Make it the oldest request in the queue — the case that broke the page.
    from app.core.db import SessionLocal
    from app.models.approval import ApprovalRequest
    from sqlalchemy import select
    async with SessionLocal() as s:
        req = await s.scalar(select(ApprovalRequest).where(
            ApprovalRequest.target_id == uuid.UUID(q["id"]), ApprovalRequest.status == "pending"))
        req.created_at = datetime(2000, 1, 1, tzinfo=UTC)
        await s.commit()

    r = await c.get("/approvals", headers=d)
    rows = J(r) if r.status_code == 200 else []
    check("the inbox loads with a quotation as the oldest request", r.status_code == 200,
          f"{r.status_code} {r.text[:200]}")
    check("...and it is first", rows and rows[0]["target_id"] == q["id"], str(rows[:1])[:200])
    mine = next((x for x in rows if x["target_id"] == q["id"]), {})
    check("...named by its own number and customer",
          mine.get("target_label") == f"{q['number']} · PT KOTAK {TAG}", str(mine.get("target_label")))
    quotes = [x for x in rows if x["target_type"] in ("quotation", "quotation_edit", "discount")]
    check("no quotation row carries another document's number",
          all((x["target_label"] or "").startswith("QT") for x in quotes),
          str([x["target_label"] for x in quotes])[:300])
    others = [x for x in rows if x["target_type"] == "customer_po"]
    check("customer PO rows are named by their own number",
          all(x["target_label"] and not x["target_label"].startswith("QT") for x in others),
          str([x["target_label"] for x in others])[:300])

    async with SessionLocal() as s:
        req = await s.scalar(select(ApprovalRequest).where(
            ApprovalRequest.target_id == uuid.UUID(q["id"]), ApprovalRequest.status == "pending"))
        req.created_at = datetime.now(UTC) - timedelta(minutes=1)
        await s.commit()

    print("\n── a proposed edit shows what it changes ──")
    await c.post(f"/quotations/{q['id']}/approve", headers=d, json={"notes": ""})
    got = J(await c.get(f"/quotations/{q['id']}", headers=s1))
    items = [{k: v for k, v in i.items() if k not in ("id", "line_total")} for i in got["items"]]
    items[0]["qty"] = 9
    r = await c.patch(f"/quotations/{q['id']}", headers=s1, json={"items": items})
    check("the rep's edit to the approved quotation is filed", r.status_code == 202,
          f"{r.status_code} {r.text[:150]}")
    rows = J(await c.get("/approvals", headers=d))
    edit = next((x for x in rows if x["target_type"] == "quotation_edit"
                 and x["target_id"] == q["id"]), None)
    check("...and is in the inbox, named", edit is not None
          and (edit["target_label"] or "").startswith(q["number"]), str(edit)[:200])
    pv = J(await c.get(f"/approvals/{edit['id']}/preview", headers=d)) if edit else {}
    line = (pv.get("items") or [{}])[0]
    check("...its preview shows the line as it would be, beside what it replaces",
          line.get("qty") == 9 and line.get("was_qty") == 5, str(pv.get("items"))[:200])
    check("...and the total it would come to", abs((pv.get("total") or 0) - 9 * 2000 * 1.11) < 1,
          str(pv.get("total")))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

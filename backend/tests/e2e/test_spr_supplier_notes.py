"""A price request to a supplier carries notes for the supplier.

Separate from the request's own notes, which are purchasing's and which the
system writes its log into ([quote], [closed]). These are what the vendor
should read with the list — written when the request is raised or later,
editable until the vendor answers, and audited.
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
    from app.models.audit import AuditLog
    from sqlalchemy import select
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    pur = await login("purchasing@demo.local")
    s1 = await login("sales1@demo.local")
    sup = J(await c.post("/purchasing/suppliers", headers=pur, json={"name": f"PT Catatan RFQ {TAG}"}))["id"]

    first = f"Quote CIF Jakarta & include your drawing — {TAG}"
    print("\n── asking a supplier, with notes for them ──")
    r = await c.post("/purchasing/price-requests", headers=pur, json={
        "supplier_ids": [sup],
        "items": [{"line_no": 1, "description": f"ROLLER CHAIN RS80 {TAG}", "qty": 40, "uom": "link"}],
        "notes": "need the price before Friday",
        "supplier_notes": f"  {first}\n"})
    rows = J(r) if isinstance(J(r), list) else []
    spr = rows[0]["id"] if rows else None
    check("purchasing asks a supplier with notes for them", r.status_code == 201 and spr,
          f"{r.status_code} {str(J(r))[:200]}")
    got = J(await c.get(f"/purchasing/price-requests/{spr}", headers=pur))
    check("...the supplier's notes are kept, trimmed", got.get("supplier_notes") == first,
          repr(got.get("supplier_notes")))
    check("...and kept apart from purchasing's own note", got.get("notes") == "need the price before Friday",
          repr(got.get("notes")))

    print("\n── changing them ──")
    second = f"Quote CIF Jakarta, material SS304, send your drawing — {TAG}"
    r = await c.patch(f"/purchasing/price-requests/{spr}", headers=pur, json={"supplier_notes": second})
    got = J(await c.get(f"/purchasing/price-requests/{spr}", headers=pur))
    check("purchasing edits them on a draft", r.status_code == 200 and got.get("supplier_notes") == second,
          f"{r.status_code} {got.get('supplier_notes')!r}")
    async with SessionLocal() as s:
        audits = (await s.scalars(select(AuditLog).where(
            AuditLog.entity == "supplier_price_request", AuditLog.entity_id == uuid.UUID(spr)))).all()
    check("...and the change is audited, old and new",
          any(a.before.get("supplier_notes") == first and a.after.get("supplier_notes") == second
              for a in audits), str([(a.before, a.after) for a in audits])[-200:])

    await c.post(f"/purchasing/price-requests/{spr}/send", headers=pur)
    third = second + "\nAlso quote 10 spare links."
    r = await c.patch(f"/purchasing/price-requests/{spr}", headers=pur, json={"supplier_notes": third})
    got = J(await c.get(f"/purchasing/price-requests/{spr}", headers=pur))
    check("still editable after it was sent (a follow-up to the vendor)",
          r.status_code == 200 and got.get("supplier_notes") == third, f"{r.status_code} {J(r)}"[:200])

    r = await c.patch(f"/purchasing/price-requests/{spr}", headers=s1, json={"supplier_notes": "x"})
    check("sales can't write them", r.status_code == 403, str(r.status_code))

    print("\n── once the supplier answers ──")
    r = await c.post(f"/purchasing/price-requests/{spr}/quote", headers=pur, json={
        "items": [{"line_no": 1, "quoted_price": 50_000}], "quoted_lead_days": 30,
        "notes": "answered on WhatsApp"})
    check("the supplier's quote is recorded", r.status_code in (200, 201), f"{r.status_code} {J(r)}"[:200])
    got = J(await c.get(f"/purchasing/price-requests/{spr}", headers=pur))
    check("...the quote note goes to purchasing's notes, not the supplier's",
          got.get("supplier_notes") == third and "[quote] answered on WhatsApp" in (got.get("notes") or ""),
          f"{got.get('supplier_notes')!r} / {got.get('notes')!r}")
    r = await c.patch(f"/purchasing/price-requests/{spr}", headers=pur, json={"supplier_notes": "too late"})
    check("...and the notes are fixed once there's an answer", r.status_code == 409, str(r.status_code))

    print("\n── clearing ──")
    r = await c.post("/purchasing/price-requests", headers=pur, json={
        "supplier_ids": [sup],
        "items": [{"line_no": 1, "description": f"SPROCKET {TAG}", "qty": 2, "uom": "pcs"}],
        "supplier_notes": "temporary"})
    other = J(r)[0]["id"]
    r = await c.patch(f"/purchasing/price-requests/{other}", headers=pur, json={"supplier_notes": "   "})
    got = J(await c.get(f"/purchasing/price-requests/{other}", headers=pur))
    check("blank notes clear them", r.status_code == 200 and got.get("supplier_notes") is None,
          repr(got.get("supplier_notes")))

    print("\n── where the director decides ──")
    d = await login("director@demo.local")
    cust = J(await c.post("/customers", headers=s1, json={"company_name": f"PT Direktur {TAG}", "industry": "mining"}))["id"]
    pr = J(await c.post("/price-requests", headers=s1, json={"customer_id": cust, "items": [
        {"description": f"CHAIN P600 {TAG}", "qty": 2, "uom": "set"}]}))["id"]
    await c.post(f"/price-requests/{pr}/submit", headers=s1)
    asked = f"Quote CIF Jakarta, inspection report included — {TAG}"
    linked = J(await c.post("/purchasing/price-requests", headers=pur, json={
        "supplier_ids": [sup], "price_request_ids": [pr], "supplier_notes": asked}))[0]["id"]
    await c.post(f"/purchasing/price-requests/{linked}/send", headers=pur)
    await c.post(f"/purchasing/price-requests/{linked}/quote", headers=pur, json={
        "items": [{"line_no": 1, "quoted_price": 1_000_000}], "quoted_lead_days": 40})
    r = await c.post(f"/purchasing/price-requests/{linked}/apply", headers=pur)
    check("the quote is applied as the cost", r.status_code == 200, f"{r.status_code} {J(r)}"[:200])
    page = J(await c.get(f"/price-requests/{pr}", headers=d))
    mine = [x for x in page.get("supplier_requests", []) if x["id"] == linked]
    check("the director's price request page shows what the supplier was asked",
          mine and mine[0].get("supplier_notes") == asked, str(mine)[:200])
    inbox = J(await c.get("/approvals/pending-documents", headers=d))
    rows = inbox if isinstance(inbox, list) else inbox.get("items", [])
    quotes = [q for i in rows if i.get("kind") == "price_request"
              for q in (i.get("supplier_quotes") or []) if q["id"] == linked]
    check("...and so does the approvals inbox", quotes and quotes[0].get("supplier_notes") == asked,
          str(quotes)[:200])

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

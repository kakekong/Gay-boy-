"""Why a quotation was lost shows on the quotation itself.

The reason used to be appended to the notes as "[lost @ <UTC time>] reason":
buried among the customer's terms on the quotation page, readable in one
report only the director has, and printed on the PDF if anyone exported the
quotation again.

* Marking it lost keeps the reason, when and who in their own fields, and
  the quotation page shows them at the top.
* The notes stay as they were — the reason never reaches the PDF.
* Reasons written the old way are lifted out of the notes on boot.
* The lost-deals report still groups by reason.
"""
import asyncio, io, os, sys, uuid
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
    from app.models.quotation import Quotation
    from sqlalchemy import update
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    s1 = await login("sales1@demo.local")
    pur = await login("purchasing@demo.local")

    async def a_quote(label):
        cust = J(await c.post("/customers", headers=s1, json={
            "company_name": f"PT Kalah {label} {TAG}", "industry": "mining"}))["id"]
        pr = J(await c.post("/price-requests", headers=s1, json={
            "customer_id": cust, "items": [{"description": f"CHAIN {TAG}", "qty": 2, "uom": "pcs"}]}))
        await c.post(f"/price-requests/{pr['id']}/submit", headers=s1)
        await c.post(f"/price-requests/{pr['id']}/price", headers=pur, json={
            "items": [{"line_no": 1, "cost_price": 100_000, "basis": "unit"}]})
        await c.post(f"/price-requests/{pr['id']}/approve", headers=d, json={
            "items": [{"line_no": 1, "sell_price": 150_000, "basis": "unit"}]})
        q = J(await c.post(f"/quotations/from-price-request/{pr['id']}", headers=s1))
        await c.patch(f"/quotations/{q['id']}", headers=s1,
                      json={"notes": f"Franco gudang pembeli {TAG}"})
        return q["id"]

    print("\n── marked lost now ──")
    qid = await a_quote("A")
    why = f"Harga kompetitor lebih murah 12% {TAG}"
    r = await c.post(f"/quotations/{qid}/lost", headers=s1, params={"reason": why})
    check("the rep marks it lost with a reason", r.status_code == 200, f"{r.status_code} {J(r)}"[:200])
    q = J(await c.get(f"/quotations/{qid}", headers=s1))
    check("the quotation carries the reason itself", q.get("lost_reason") == why, str(q.get("lost_reason")))
    check("...who marked it, and when", q.get("lost_by_name") == "Sales One" and q.get("lost_at"),
          f"{q.get('lost_by_name')} {q.get('lost_at')}")
    check("...and the notes are left as they were",
          "[lost" not in (q.get("notes") or "") and TAG in (q.get("notes") or ""), str(q.get("notes")))
    r = await c.get(f"/quotations/{qid}/export.pdf", headers=s1)
    text = ""
    if r.status_code == 200:
        from pypdf import PdfReader
        text = " ".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(r.content)).pages)
    check("the reason never prints on the customer's PDF",
          r.status_code == 200 and "kompetitor" not in text and "Franco" in text,
          f"{r.status_code} {text[:120]!r}")

    print("\n── written the old way ──")
    qid2 = await a_quote("B")
    async with SessionLocal() as s:
        await s.execute(update(Quotation).where(Quotation.id == uuid.UUID(qid2)).values(
            status="lost", lost_reason=None, lost_at=None, lost_by=None,
            notes=f"Franco gudang pembeli {TAG}\n[lost @ 2026-10-01T03:00:00+00:00] Proyek ditunda {TAG}"))
        await s.commit()
    await ensure_schema()       # the boot migration
    q = J(await c.get(f"/quotations/{qid2}", headers=s1))
    check("an old reason is lifted out of the notes into its place",
          q.get("lost_reason") == f"Proyek ditunda {TAG}"
          and (q.get("lost_at") or "").startswith("2026-10-01"), f"{q.get('lost_reason')} {q.get('lost_at')}")
    check("...and the line is gone from the notes",
          q.get("notes") == f"Franco gudang pembeli {TAG}", repr(q.get("notes")))

    print("\n── the lost-deals report ──")
    rep = J(await c.get("/reports/lost-deals", headers=d))
    items = rep.get("items", [])
    mine = {i["id"]: i["reason"] for i in items if i["id"] in (qid, qid2)}
    check("still lists each with its reason",
          mine.get(qid) == why[:80] and mine.get(qid2) == f"Proyek ditunda {TAG}", str(mine))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

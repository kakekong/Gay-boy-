"""One customer PO per deal, and deleting a PO keeps its project.

The case that prompted it: one PO typed twice with a digit wrong (911805889 /
9118005889). The only guard was the exact number, so both went in, both were
approved, and both hung off PRJ-…-0018. Nothing could remove the wrong one:
the delete tool treated the project as the PO's child and would have taken
the job with it.

Pinned here:
* a second PO against the same quotation, or a revision of it, is refused and
  names the one on file (a rejected one says to fix and resubmit it);
* the director can delete a PO; sales cannot;
* the project survives, and its printed PO number/date/value move to the PO
  that is left — or clear (value kept) when none is;
* invoices issued against the deleted PO move to the survivor, and with no
  survivor the delete is refused rather than orphaning them;
* after the delete a PO can be filed on the deal again;
* the data-maintenance "delete records" preview for a PO no longer pulls in
  its project;
* delivered now comes before invoiced in the project stage order.
"""
import asyncio, os, sys, uuid
from datetime import date
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
def why(r):
    b = J(r)
    if not isinstance(b, dict):
        return str(b)[:200]
    return str(b.get("detail") or (b.get("errors") or [{}])[0].get("message", ""))


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    from app.core.db import SessionLocal
    from app.models.customer_po import CustomerPO
    from app.models.finance import Invoice
    from app.models.operation import Project, PROJECT_STATUS_ORDER
    from sqlalchemy import select
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)

    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    s1 = await login("sales1@demo.local")

    async def a_quote(tag):
        cust = J(await c.post("/customers", headers=s1, json={
            "company_name": f"PT Satu PO {tag}", "industry": "mining"}))["id"]
        pr = J(await c.post("/price-requests", headers=s1, json={
            "customer_id": cust,
            "items": [{"description": f"CHAIN {tag}", "qty": 5, "uom": "pcs"}]}))["id"]
        await c.post(f"/price-requests/{pr}/submit", headers=s1)
        await c.post(f"/price-requests/{pr}/price", headers=d, json={
            "items": [{"line_no": 1, "cost_price": 5_000_000, "basis": "unit"}]})
        await c.post(f"/price-requests/{pr}/approve", headers=d, json={
            "items": [{"line_no": 1, "sell_price": 7_500_000, "basis": "unit"}]})
        q = J(await c.post(f"/quotations/from-price-request/{pr}", headers=s1))
        await c.post(f"/quotations/{q['id']}/submit", headers=s1)
        await c.post(f"/quotations/{q['id']}/approve", headers=d, json={"notes": ""})
        return cust, q

    async def file_po(cust, qid, number):
        return await c.post("/customer-pos", headers=s1, json={
            "customer_id": cust, "quotation_id": qid, "number": number,
            "po_date": "2026-09-24",
            "items": [{"description": "CHAIN", "qty": 5, "unit_price": 7_500_000}],
            "is_downpayment": False})

    # ══ one PO per deal ═════════════════════════════════════════════════════
    print("\n── a deal takes one PO ──")
    cust, q = await a_quote(TAG)
    real = f"91180{TAG}"
    typo = f"911800{TAG}"
    r = await file_po(cust, q["id"], real)
    check("the first PO is filed", r.status_code == 201, f"{r.status_code} {why(r)}")
    po_a = J(r)
    await c.post(f"/customer-pos/{po_a['id']}/approve", headers=d, json={"notes": ""})
    r = await c.post(f"/quotations/{q['id']}/won", headers=d)
    check("the deal is won and the project opens", r.status_code == 200, f"{r.status_code} {why(r)}")

    r = await file_po(cust, q["id"], typo)
    check("a second PO on the same quotation is refused — the 911805889 / 9118005889 case",
          r.status_code == 409, f"{r.status_code} {why(r)}")
    check("...and the refusal names the PO already on file",
          real in why(r), why(r)[:160])

    # A revision is the same deal.
    cust2, q2 = await a_quote(f"R{TAG}")
    await file_po(cust2, q2["id"], f"REV-{TAG}")
    rev = J(await c.post(f"/quotations/{q2['id']}/revise", headers=s1))
    if rev.get("id"):
        await c.post(f"/quotations/{rev['id']}/submit", headers=s1)
        await c.post(f"/quotations/{rev['id']}/approve", headers=d, json={"notes": ""})
        r = await file_po(cust2, rev["id"], f"REV2-{TAG}")
        check("a revision of the quotation is the same deal — a second PO there is refused too",
              r.status_code == 409 and f"REV-{TAG}" in why(r), f"{r.status_code} {why(r)}")
    else:
        check("the quotation could be revised for the revision case", False, str(rev)[:160])

    # A rejected PO is fixed, not joined by another.
    cust3, q3 = await a_quote(f"X{TAG}")
    po_x = J(await file_po(cust3, q3["id"], f"REJ-{TAG}"))
    await c.post(f"/customer-pos/{po_x['id']}/reject", headers=d, json={"notes": "wrong qty"})
    r = await file_po(cust3, q3["id"], f"REJ2-{TAG}")
    check("with a rejected PO on file, it says to fix and resubmit that one",
          r.status_code == 409 and "resubmit" in why(r), f"{r.status_code} {why(r)}")

    # ══ the duplicate that already exists ═══════════════════════════════════
    # Production already holds a pair like this, filed before the rule. Make
    # one the way it was made: a second approved PO on the same project, and
    # the project's paperwork naming the wrong (newer) one.
    print("\n── deleting the duplicate keeps the project ──")
    async with SessionLocal() as db:
        a = await db.get(CustomerPO, uuid.UUID(po_a["id"]))
        proj_id = a.project_id
        dup = CustomerPO(number=typo, po_date=date(2026, 9, 24), customer_id=a.customer_id,
                         quotation_id=a.quotation_id, project_id=proj_id,
                         total=37_500_000, items=a.items, status="approved")
        db.add(dup)
        await db.flush()
        proj = await db.get(Project, proj_id)
        proj.po_number = typo
        inv = Invoice(number=f"INV-DUP-{TAG}", project_id=proj_id,
                      customer_po_id=dup.id, customer_id=a.customer_id,
                      amount=1_000, total=1_000, status="draft")
        db.add(inv)
        await db.commit()
        dup_id, inv_id = str(dup.id), inv.id
    check("the legacy pair exists: two POs, one project", proj_id is not None)

    r = await c.delete(f"/customer-pos/{dup_id}", headers=s1)
    check("sales cannot delete a customer PO", r.status_code == 403, f"{r.status_code}")

    r = await c.delete(f"/customer-pos/{dup_id}", headers=d)
    check("the director deletes the mistyped PO", r.status_code == 200, f"{r.status_code} {why(r)}")
    res = J(r)
    check("...and is told the project was kept", bool(res.get("project_code")), str(res)[:200])
    r = await c.get(f"/customer-pos/{dup_id}", headers=d)
    check("the PO is gone", r.status_code == 404, str(r.status_code))
    async with SessionLocal() as db:
        proj = await db.get(Project, proj_id)
        inv = await db.get(Invoice, inv_id)
        check("the project is still there", proj is not None and not proj.is_deleted)
        check("...and its PO number switched back to the real PO",
              proj is not None and proj.po_number == real, str(proj and proj.po_number))
        check("the invoice issued against the deleted PO moved to the one that is left",
              inv is not None and str(inv.customer_po_id) == po_a["id"],
              str(inv and inv.customer_po_id))
        await db.delete(inv)
        await db.commit()

    # ══ the only PO ═════════════════════════════════════════════════════════
    print("\n── deleting the only PO ──")
    async with SessionLocal() as db:
        inv2 = Invoice(number=f"INV-ONLY-{TAG}", project_id=proj_id,
                       customer_po_id=uuid.UUID(po_a["id"]), customer_id=uuid.UUID(cust),
                       amount=1_000, total=1_000, status="draft")
        db.add(inv2)
        await db.commit()
        inv2_id = inv2.id
    r = await c.delete(f"/customer-pos/{po_a['id']}", headers=d)
    check("an invoice with no other PO to move to refuses the delete",
          r.status_code == 409 and f"INV-ONLY-{TAG}" in why(r), f"{r.status_code} {why(r)}")
    async with SessionLocal() as db:
        await db.delete(await db.get(Invoice, inv2_id))
        await db.commit()

    async with SessionLocal() as db:
        value_before = float((await db.get(Project, proj_id)).po_value or 0)
    r = await c.delete(f"/customer-pos/{po_a['id']}", headers=d)
    check("with the invoice gone, the only PO can be deleted", r.status_code == 200,
          f"{r.status_code} {why(r)}")
    async with SessionLocal() as db:
        proj = await db.get(Project, proj_id)
        check("the project survives losing its only PO", proj is not None)
        check("...its PO number and date clear, since nothing is left to name",
              proj.po_number is None and proj.po_date is None,
              f"{proj.po_number} {proj.po_date}")
        check("...and its value stays — it is what the job is invoiced against",
              float(proj.po_value or 0) == value_before, f"{proj.po_value} vs {value_before}")

    r = await file_po(cust, q["id"], f"NEW-{TAG}")
    check("with the PO deleted, the deal can take a PO again", r.status_code == 201,
          f"{r.status_code} {why(r)}")

    # ══ data maintenance no longer takes the project ════════════════════════
    print("\n── the director's delete-records tool ──")
    new_po = J(r)
    r = await c.post("/maintenance/records/preview", headers=d, json={
        "targets": [{"type": "customer_po", "id": new_po["id"]}]})
    docs = J(r).get("documents") or []
    check("previewing a PO delete no longer pulls in its project",
          not any(x["type"] == "project" for x in docs),
          str([(x["type"], x["number"]) for x in docs])[:200])

    # ══ stage order ═════════════════════════════════════════════════════════
    print("\n── project stages: delivered before invoiced ──")
    check("delivered comes before invoiced in the order",
          PROJECT_STATUS_ORDER.index("delivered") < PROJECT_STATUS_ORDER.index("invoiced"),
          str(PROJECT_STATUS_ORDER))
    from app.services.project_stage import settle_delivery_and_invoice
    from sqlalchemy import text
    async with SessionLocal() as db:
        proj = await db.get(Project, proj_id)
        proj.status = "packaging"
        proj.customer_received_at = None
        inv = Invoice(number=f"INV-STG-{TAG}", project_id=proj_id,
                      customer_id=proj.customer_id, type="final",
                      amount=1_000, total=1_000, status="approved")
        db.add(inv)
        await db.flush()
        await settle_delivery_and_invoice(db, proj)
        check("an invoice approved before delivery does not skip the job past delivered",
              proj.status == "packaging", proj.status)
        from datetime import datetime, UTC
        proj.customer_received_at = datetime.now(UTC)
        await settle_delivery_and_invoice(db, proj)
        check("...and when delivery is confirmed the job lands at invoiced",
              proj.status == "invoiced", proj.status)
        inv.status = "draft"
        proj.status = "packaging"
        await db.flush()
        await settle_delivery_and_invoice(db, proj)
        check("delivered with no approved invoice sits at delivered",
              proj.status == "delivered", proj.status)

        # The one-off re-sort of projects that predate the new order.
        proj.status = "invoiced"            # old meaning: invoiced, not delivered
        proj.customer_received_at = None
        inv.status = "approved"
        await db.commit()
    async with SessionLocal() as db:
        await db.execute(text("DELETE FROM data_fixes "
                              "WHERE key = 'project_stage_delivered_before_invoiced'"))
        await db.commit()
    await ensure_schema()
    async with SessionLocal() as db:
        proj = await db.get(Project, proj_id)
        check("existing jobs are re-sorted: invoiced-but-not-delivered goes back to "
              "waiting for delivery", proj.status == "packaging", proj.status)
        proj.status = "delivered"           # old meaning: invoiced and delivered
        await db.commit()
    async with SessionLocal() as db:
        await db.execute(text("DELETE FROM data_fixes "
                              "WHERE key = 'project_stage_delivered_before_invoiced'"))
        await db.commit()
    await ensure_schema()
    async with SessionLocal() as db:
        proj = await db.get(Project, proj_id)
        check("...and delivered-and-invoiced moves on to invoiced",
              proj.status == "invoiced", proj.status)
        proj.status = "packaging"
        await db.commit()
    await ensure_schema()
    async with SessionLocal() as db:
        proj = await db.get(Project, proj_id)
        check("the re-sort runs once — a second deploy leaves projects alone",
              proj.status == "packaging", proj.status)
        await db.delete(await db.scalar(select(Invoice).where(
            Invoice.number == f"INV-STG-{TAG}")))
        await db.commit()

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        sys.exit(1)

asyncio.run(main())

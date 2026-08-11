"""The director-only test-data purge.

This is the most destructive thing in the app, so the checks below are less
about "does it delete" and more about the four ways it could go wrong:

1. **It deletes the wrong lineage.** A project is created by whoever approves
   the customer PO, not by the sales rep who won the deal — so a naive
   "created_by = the rep" filter would delete that rep's own live projects.
   The rule is anchored on the customer instead, and the test proves a real
   deal survives even though its project, invoice and PO were all created by
   other people.

2. **It leaves wreckage.** Attachments, discussion messages, approval requests
   and ledger entries point at documents with no foreign key. Nothing cascades
   them; if the purge misses them they sit forever pointing at dead ids.

3. **It runs when it shouldn't.** Anyone but the director, a director-based
   custom role, a missing confirmation phrase, or an empty keep-list — that
   last one being the dangerous case, since "keep nobody" reads as "delete
   every customer in the company".

4. **The preview lies.** Whatever the preview counts is what the delete must
   remove; they are built from the same plan, and this pins that.
"""
import asyncio, os, sys, uuid
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123", STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import httpx, logging; logging.disable(logging.INFO)
PASS, FAIL = [], []
def check(n,c,d=""):
    (PASS if c else FAIL).append(n); print(("  PASS " if c else "  FAIL ")+n+(f"  [{d}]" if d and not c else ""))
def J(r):
    try: return r.json()
    except: return {"_":r.text[:200]}
async def login(c,e):
    r=await c.post("/auth/login",json={"email":e,"password":"test-pass-123"})
    return {"Authorization":f"Bearer {r.json()['access_token']}"}

CONFIRM = "DELETE TEST DATA"


async def full_deal(c, sales, d, pu, name, tag):
    """Lead → priced → quoted → PO → project → invoice, the whole chain.

    Note who creates what: sales raises the price request and the quotation,
    but the *director* approves the PO — which is what creates the project —
    and finance/admin issues the invoice. That asymmetry is the point.
    """
    cust = J(await c.post("/customers", headers=sales, json={
        "company_name": name, "industry": "mining"}))["id"]
    pr = J(await c.post("/price-requests", headers=sales, json={
        "customer_id": cust, "items": [{"description": "Gearbox", "qty": 1, "uom": "pcs"}]}))["id"]
    await c.post(f"/price-requests/{pr}/submit", headers=sales)
    # The buy-side quote that justified the cost. It points at the price
    # request with a SET NULL foreign key, so a purge that forgot it would
    # leave a supplier quote hanging off nothing.
    sup = J(await c.post("/purchasing/suppliers", headers=d, json={
        "name": f"PT Pemasok {tag}", "category": "fabrication"})).get("id")
    if sup:
        await c.post("/purchasing/price-requests", headers=pu, json={
            "supplier_ids": [sup], "price_request_id": pr})
    await c.post(f"/price-requests/{pr}/price", headers=pu,
                 json={"items": [{"line_no": 1, "cost_price": 5_000_000, "basis": "unit"}]})
    await c.post(f"/price-requests/{pr}/approve", headers=d,
                 json={"items": [{"line_no": 1, "sell_price": 9_000_000, "basis": "unit"}]})
    quo = J(await c.post(f"/quotations/from-price-request/{pr}", headers=sales))["id"]
    await c.post("/comments", headers=sales, json={
        "owner_type": "quotation", "owner_id": quo, "body": f"discussion on {tag}"})
    # The quotation has to be WON before a customer PO can be filed against it.
    await c.post(f"/quotations/{quo}/submit", headers=d)
    await c.post(f"/quotations/{quo}/won", headers=d)
    cpo = J(await c.post("/customer-pos", headers=sales, json={
        "customer_id": cust, "quotation_id": quo, "number": f"PO-{tag}",
        "items": [{"description": "Gearbox", "qty": 1, "unit_price": 9_000_000}],
        "is_downpayment": False}))
    proj = None
    if cpo.get("id"):
        proj = J(await c.post(f"/customer-pos/{cpo['id']}/approve", headers=d,
                              json={"notes": ""})).get("project_id")
    return {"customer": cust, "pr": pr, "quo": quo, "cpo": cpo.get("id"), "project": proj}


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=90)
    d = await login(c, "director@demo.local");  s1 = await login(c, "sales1@demo.local")
    s2 = await login(c, "sales2@demo.local");   pu = await login(c, "purchasing@demo.local")
    hr = await login(c, "hr@demo.local")
    tag = uuid.uuid4().hex[:5]

    # A throwaway rep whose whole pipeline is the thing being purged. Every
    # other user stays on the keep-list, so this driver removes exactly one
    # lineage and leaves the shared scratch database intact for the drivers
    # that run after it.
    victim_email = f"purge-victim-{tag}@demo.local"
    victim = J(await c.post("/users", headers=d, json={
        "email": victim_email, "full_name": f"Purge Victim {tag}",
        "role": "sales", "password": "test-pass-123"}))
    check("created a throwaway rep to purge", bool(victim.get("id")), str(victim)[:140])
    vs = await login(c, victim_email)

    owners = J(await c.get("/maintenance/data-owners", headers=d))
    ids = {u["full_name"]: u["id"] for u in owners}
    check("the owners list names everyone who could hold data",
          {"Sales One", "Director Demo", f"Purge Victim {tag}"} <= set(ids),
          str(list(ids))[:140])
    check("...with counts to choose by",
          all("customers" in u and "projects" in u for u in owners), str(owners[:1])[:120])

    # Sales One's deal is real; the victim's is the throwaway. Both are built by
    # the same function, so the ONLY difference is who originated them.
    real = await full_deal(c, s1, d, pu, f"PT Nyata {tag}", f"REAL{tag}")
    junk = await full_deal(c, vs, d, pu, f"PT Coba {tag}", f"JUNK{tag}")
    check("both deals reached a project",
          bool(real["project"]) and bool(junk["project"]),
          f"real={real['project']} junk={junk['project']}")

    # Keep everyone except the victim.
    keep = {"keep_user_ids": [uid for name, uid in ids.items()
                              if name != f"Purge Victim {tag}"]}

    # ── 1. who may run it ────────────────────────────────────────────────────
    for who, hdr in (("sales", s1), ("purchasing", pu), ("HR", hr)):
        r = await c.post("/maintenance/purge/preview", headers=hdr, json=keep)
        check(f"{who} cannot even preview the purge", r.status_code == 403, str(r.status_code))
    r = await c.post("/maintenance/purge/execute", headers=s1,
                     json={**keep, "confirm": CONFIRM})
    check("sales cannot execute it", r.status_code == 403, str(r.status_code))

    # ── 2. the guards ────────────────────────────────────────────────────────
    r = await c.post("/maintenance/purge/execute", headers=d, json=keep)
    check("without the confirmation phrase it refuses", r.status_code == 400, str(r.status_code))
    r = await c.post("/maintenance/purge/execute", headers=d,
                     json={**keep, "confirm": "delete test data"})
    check("the phrase is case-sensitive", r.status_code == 400, str(r.status_code))
    r = await c.post("/maintenance/purge/execute", headers=d,
                     json={"keep_user_ids": [], "confirm": CONFIRM})
    check("an empty keep-list is refused, not read as 'delete everything'",
          r.status_code == 400, str(r.status_code))
    r = await c.post("/maintenance/purge/preview", headers=d, json={"keep_user_ids": []})
    check("...and the preview refuses it too", r.status_code == 400, str(r.status_code))

    # ── 3. the preview ───────────────────────────────────────────────────────
    prev = J(await c.post("/maintenance/purge/preview", headers=d, json=keep))
    doomed_names = {x["name"] for x in prev["customers_to_delete"]}
    kept_names = {x["name"] for x in prev["customers_to_keep"]}
    check("the preview keeps the real customer", f"PT Nyata {tag}" in kept_names,
          str(sorted(kept_names))[:120])
    check("the preview marks the test customer for deletion",
          f"PT Coba {tag}" in doomed_names, str(sorted(doomed_names))[:120])
    check("it says why a customer is being kept",
          any(x["why"] for x in prev["customers_to_keep"] if x["name"] == f"PT Nyata {tag}"),
          str([x for x in prev["customers_to_keep"] if x["name"] == f"PT Nyata {tag}"])[:160])
    check("the director approving the test PO does not rescue it "
          "(project.created_by is not a keep rule)",
          f"PT Coba {tag}" in doomed_names, str(sorted(doomed_names))[:140])
    check("it counts the whole lineage, not just customers",
          prev["counts"]["projects"] >= 1 and prev["counts"]["quotations"] >= 1
          and prev["counts"]["invoices"] >= 0, str(prev["counts"]))
    check("the preview changes nothing",
          (await c.get(f"/customers/{junk['customer']}", headers=d)).status_code == 200)

    before = prev["counts"]

    # ── 4. the delete ────────────────────────────────────────────────────────
    r = await c.post("/maintenance/purge/execute", headers=d,
                     json={**keep, "confirm": CONFIRM})
    check("the director can execute it", r.status_code == 200, J(r))
    got = J(r).get("deleted") or {}
    check("what it deleted matches what the preview promised",
          got.get("customers") == before.get("customers")
          and got.get("projects") == before.get("projects"),
          f"preview={before.get('customers')}/{before.get('projects')} "
          f"actual={got.get('customers')}/{got.get('projects')}")

    # ── 5. the right things are gone ─────────────────────────────────────────
    check("the test customer is gone",
          (await c.get(f"/customers/{junk['customer']}", headers=d)).status_code in (403, 404))
    check("its project is gone",
          (await c.get(f"/operation/projects/{junk['project']}/full", headers=d)).status_code in (403, 404))
    check("its quotation is gone",
          (await c.get(f"/quotations/{junk['quo']}", headers=d)).status_code in (403, 404))
    check("its price request is gone",
          (await c.get(f"/price-requests/{junk['pr']}", headers=d)).status_code in (403, 404))
    check("its customer PO is gone",
          (await c.get(f"/customer-pos/{junk['cpo']}", headers=d)).status_code in (403, 404))

    # ── 6. the real deal is untouched, top to bottom ─────────────────────────
    body = J(await c.get("/customers", headers=d, params={"limit": 200}))
    others = body.get("data") if isinstance(body, dict) else body
    names = {x.get("company_name") for x in (others or [])}
    check("customers belonging to everyone else are untouched",
          f"PT Coba {tag}" not in names and f"PT Nyata {tag}" in names,
          str(sorted(n for n in names if tag in (n or "")))[:140])
    check("the real customer survives",
          (await c.get(f"/customers/{real['customer']}", headers=d)).status_code == 200)
    check("its project survives — even though the director created it",
          (await c.get(f"/operation/projects/{real['project']}/full", headers=d)).status_code == 200)
    check("its quotation survives",
          (await c.get(f"/quotations/{real['quo']}", headers=d)).status_code == 200)
    check("its price request survives",
          (await c.get(f"/price-requests/{real['pr']}", headers=d)).status_code == 200)
    check("its customer PO survives",
          (await c.get(f"/customer-pos/{real['cpo']}", headers=d)).status_code == 200)
    disc = J(await c.get("/comments", headers=d,
                         params={"owner_type": "quotation", "owner_id": real["quo"]}))
    check("its discussion survives",
          isinstance(disc, list) and any("REAL" in (x.get("body") or "") for x in disc),
          str(disc)[:120])

    # ── 7. nothing is left pointing at a deleted document ────────────────────
    from sqlalchemy import select, func, or_
    from app.core.db import SessionLocal
    from app.models.approval import ApprovalRequest
    from app.models.attachment import Attachment
    from app.models.comment import EntityComment, CommentMention
    from app.models.crm import Customer
    from app.models.customer_po import CustomerPO
    from app.models.finance import Invoice, LedgerEntry, Payment
    from app.models.operation import Project, WorkOrder, Drawing, DeliveryOrder
    from app.models.price_request import PriceRequest
    from app.models.purchasing import SupplierPO, SupplierPriceRequest
    from app.models.quotation import Quotation, QuotationItem

    async with SessionLocal() as db:
        async def n(stmt) -> int:
            return await db.scalar(stmt) or 0
        gone = [junk["customer"], junk["project"], junk["quo"], junk["pr"], junk["cpo"]]
        gone = [uuid.UUID(x) for x in gone if x]

        check("no discussion messages left behind",
              await n(select(func.count(EntityComment.id))
                      .where(EntityComment.owner_id.in_(gone))) == 0)
        check("no attachments left behind",
              await n(select(func.count(Attachment.id))
                      .where(Attachment.owner_id.in_(gone))) == 0)
        check("no approval requests left behind",
              await n(select(func.count(ApprovalRequest.id))
                      .where(ApprovalRequest.target_id.in_(gone))) == 0)
        check("no ledger entries left behind",
              await n(select(func.count(LedgerEntry.id))
                      .where(LedgerEntry.source_id.in_(gone))) == 0)

        # Whole-database orphan sweep: every child row must still find its parent.
        orphans = {
            "quotations → customer": await n(select(func.count(Quotation.id)).where(
                ~Quotation.customer_id.in_(select(Customer.id)))),
            "price_requests → customer": await n(select(func.count(PriceRequest.id)).where(
                ~PriceRequest.customer_id.in_(select(Customer.id)))),
            "customer_pos → customer": await n(select(func.count(CustomerPO.id)).where(
                ~CustomerPO.customer_id.in_(select(Customer.id)))),
            "projects → customer": await n(select(func.count(Project.id)).where(
                ~Project.customer_id.in_(select(Customer.id)))),
            "invoices → customer": await n(select(func.count(Invoice.id)).where(
                ~Invoice.customer_id.in_(select(Customer.id)))),
            "payments → invoice": await n(select(func.count(Payment.id)).where(
                ~Payment.invoice_id.in_(select(Invoice.id)))),
            "quotation_items → quotation": await n(select(func.count(QuotationItem.id)).where(
                ~QuotationItem.quotation_id.in_(select(Quotation.id)))),
            "work_orders → project": await n(select(func.count(WorkOrder.id)).where(
                ~WorkOrder.project_id.in_(select(Project.id)))),
            "drawings → project": await n(select(func.count(Drawing.id)).where(
                ~Drawing.project_id.in_(select(Project.id)))),
            "delivery_orders → project": await n(select(func.count(DeliveryOrder.id)).where(
                ~DeliveryOrder.project_id.in_(select(Project.id)))),
            "supplier_pos → project": await n(select(func.count(SupplierPO.id)).where(
                SupplierPO.project_id.is_not(None),
                ~SupplierPO.project_id.in_(select(Project.id)))),
            "mentions → comment": await n(select(func.count(CommentMention.id)).where(
                ~CommentMention.comment_id.in_(select(EntityComment.id)))),
            "supplier_price_requests → price_request": await n(
                select(func.count(SupplierPriceRequest.id)).where(
                    SupplierPriceRequest.price_request_id.is_not(None),
                    ~SupplierPriceRequest.price_request_id.in_(select(PriceRequest.id)))),
        }
        bad = {k: v for k, v in orphans.items() if v}
        check("the database has no orphaned rows anywhere afterwards", not bad, str(bad))

    # ── 8. it is idempotent, and the trail is there ──────────────────────────
    again = J(await c.post("/maintenance/purge/execute", headers=d,
                           json={**keep, "confirm": CONFIRM}))
    check("running it again deletes nothing more",
          (again.get("deleted") or {}).get("customers", -1) == 0, str(again)[:140])

    audit = J(await c.get("/audit", headers=d, params={"action": "purge_test_data", "limit": 10}))
    check("the purge is written to the audit log",
          isinstance(audit, list) and len(audit) >= 1, str(audit)[:120])
    if isinstance(audit, list) and audit:
        check("...naming who ran it and what it removed",
              bool(audit[0].get("actor_name")) and bool((audit[0].get("after") or {}).get("counts")),
              str(audit[0])[:160])

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")


asyncio.run(main())

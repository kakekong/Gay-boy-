"""What am I actually approving?

The approval inbox used to show a one-line reason and two buttons. For a
customer PO worth Rp 59 juta that is not enough to decide on — the director
wants the lines, the money, the keterangan and the files the requester
attached, without leaving the queue to go hunting for the document.

So each request gets a preview. The shape is deliberately uniform across
target types so the UI has one renderer, and the things worth pinning are:

* The **document's own** attachments come through, not just files stapled to
  the approval request. A scan uploaded against the customer PO is the whole
  reason the preview exists.
* Money is computed per line, so a wrong qty or unit price is visible rather
  than hidden behind a single total.
* A revision preview shows what *changed* — the old quantity beside the new
  one — because the decision is about the change, not the whole list.
* It is a director's view. Sales must not be able to read the queue's
  previews, which would leak documents belonging to other reps.
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


def find_req(queue, target_type, target_id=None):
    for a in queue if isinstance(queue, list) else []:
        if a.get("target_type") == target_type and (
                target_id is None or str(a.get("target_id")) == str(target_id)):
            return a
    return None


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=90)
    d = await login(c, "director@demo.local");  s1 = await login(c, "sales1@demo.local")
    pu = await login(c, "purchasing@demo.local")
    tag = uuid.uuid4().hex[:5]

    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Pratinjau {tag}", "industry": "mining",
        "company_address": "Jl. Sudirman 45", "delivery_address": "Site Satui KM 142"}))["id"]
    pr = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust, "items": [
            {"description": f"Gearbox SEW K87 [{tag}]", "qty": 2, "uom": "pcs"},
            {"description": f"Coupling [{tag}]", "qty": 4, "uom": "pcs"}]}))["id"]
    await c.post(f"/price-requests/{pr}/submit", headers=s1)
    await c.post(f"/price-requests/{pr}/price", headers=pu, json={"items": [
        {"line_no": 1, "cost_price": 18_000_000, "basis": "unit"},
        {"line_no": 2, "cost_price": 900_000, "basis": "unit"}]})
    await c.post(f"/price-requests/{pr}/approve", headers=d, json={"items": [
        {"line_no": 1, "sell_price": 26_500_000, "basis": "unit"},
        {"line_no": 2, "sell_price": 1_500_000, "basis": "unit"}]})
    quo = J(await c.post(f"/quotations/from-price-request/{pr}", headers=s1))["id"]
    await c.post(f"/quotations/{quo}/submit", headers=d)
    await c.post(f"/quotations/{quo}/approve", headers=d, json={"notes": ""})

    # The customer's PO first — Won rests on it now.
    po = J(await c.post("/customer-pos", headers=s1, json={
        "customer_id": cust, "quotation_id": quo, "number": f"PO-PREV-{tag}",
        "po_date": "2026-07-31", "items": [
            {"description": f"Gearbox SEW K87 [{tag}]", "qty": 2, "uom": "pcs",
             "unit_price": 26_500_000},
            {"description": f"Coupling [{tag}]", "qty": 4, "uom": "pcs",
             "unit_price": 1_500_000}],
        "is_downpayment": False}))
    po_id = po.get("id")
    await c.post(f"/quotations/{quo}/won", headers=d)
    KET = f"Kirim bertahap, konfirmasi H-2 [{tag}]"
    await c.patch(f"/customer-pos/{po_id}", headers=s1, json={"notes": KET})
    # A file on the *document*, not on the approval request — the case the
    # old queue could not show at all.
    await c.post("/attachments", headers=s1,
                 files={"file": ("po-scan.txt", b"scanned PO", "text/plain")},
                 data={"owner_type": "customer_po", "owner_id": po_id,
                       "description": "customer PO scan"})

    q = J(await c.get("/approvals", headers=d))
    row = find_req(q, "customer_po", po_id)
    check("the PO is waiting in the director's queue", bool(row), str(q)[:200])
    req_id = (row or {}).get("id")

    # ── 1. the customer PO preview ───────────────────────────────────────────
    p = J(await c.get(f"/approvals/{req_id}/preview", headers=d))
    check("the preview names the document", p.get("title") == f"PO-PREV-{tag}", str(p)[:200])
    check("...and the customer", p.get("subtitle") == f"PT Pratinjau {tag}", str(p.get("subtitle")))
    check("...and links through to it", (p.get("link") or "").endswith(str(po_id)), str(p.get("link")))
    items = p.get("items") or []
    check("both lines are there", len(items) == 2, str(len(items)))
    gearbox = next((i for i in items if "Gearbox" in (i.get("description") or "")), None)
    check("a line carries its quantity", (gearbox or {}).get("qty") == 2, str(gearbox))
    check("...its unit price", (gearbox or {}).get("unit_price") == 26_500_000, str(gearbox))
    check("...and its own line total, so a wrong qty is visible",
          (gearbox or {}).get("line_total") == 53_000_000, str(gearbox))
    check("the total is the sum of the lines", p.get("total") == 59_000_000, str(p.get("total")))
    check("the keterangan is shown", p.get("notes") == KET, str(p.get("notes")))
    fields = {f["label"]: f["value"] for f in (p.get("fields") or [])}
    check("the PO date is shown", fields.get("PO date") == "2026-07-31", str(fields))
    check("...and whether it is a down payment", fields.get("Down payment") == "no", str(fields))

    files = p.get("attachments") or []
    check("the file attached to the PO comes through", len(files) == 1, str(files)[:200])
    if files:
        check("...by name", files[0].get("filename") == "po-scan.txt", str(files[0]))
        check("...with its size, so an empty upload is obvious",
              files[0].get("size") == 10, str(files[0]))
        check("...and its description", files[0].get("description") == "customer PO scan",
              str(files[0]))

    # ── 2. it is a decision-maker's view ─────────────────────────────────────
    r = await c.get(f"/approvals/{req_id}/preview", headers=s1)
    check("sales cannot read previews out of the approval queue",
          r.status_code == 403, str(r.status_code))
    r = await c.get(f"/approvals/{uuid.uuid4()}/preview", headers=d)
    check("an unknown request is a 404, not a blank panel", r.status_code == 404,
          str(r.status_code))

    # ── 3. a revision preview shows the change, not just the proposal ────────
    rev = await c.post(f"/price-requests/{pr}/revise", headers=s1, json={
        "reason": f"customer negotiated volume [{tag}]",
        "items": [{"description": f"Gearbox SEW K87 [{tag}]", "qty": 5, "uom": "pcs"},
                  {"description": f"Filter [{tag}]", "qty": 1, "uom": "pcs"}]})
    check("a revision can be raised", rev.status_code in (200, 201), J(rev))
    q = J(await c.get("/approvals", headers=d))
    rrow = find_req(q, "price_request_revision", pr)
    check("the revision reaches the queue", bool(rrow), str(q)[:200])
    if rrow:
        p = J(await c.get(f"/approvals/{rrow['id']}/preview", headers=d))
        check("the revision preview names the price request and which revision",
              "revision 1" in (p.get("title") or ""), str(p.get("title")))
        check("...and carries the reason given", f"negotiated volume [{tag}]" in (p.get("notes") or ""),
              str(p.get("notes")))
        ri = {i.get("description"): i for i in (p.get("items") or [])}
        g = ri.get(f"Gearbox SEW K87 [{tag}]")
        check("a changed line shows the proposed quantity", (g or {}).get("qty") == 5, str(g))
        check("...beside the one it is replacing", (g or {}).get("was_qty") == 2, str(g))
        f = ri.get(f"Filter [{tag}]")
        check("a line that did not exist before is flagged as new",
              (f or {}).get("is_new") is True, str(f))
        check("...and has no old quantity to show", (f or {}).get("was_qty") is None, str(f))
        rf = {x["label"]: x["value"] for x in (p.get("fields") or [])}
        check("the preview says how many revisions are left",
              rf.get("Revisions used") == "0 of 3", str(rf))
        check("...and who asked for it", "Sales" in (rf.get("Requested by") or ""), str(rf))
        # Leave the queue clean for the drivers that assert on it.
        await c.post(f"/approvals/{rrow['id']}/reject", headers=d,
                     params={"notes": "test fixture"})

    # ── 4. a request with no document behind it still renders ────────────────
    # cross_dept_chat has no line items and no files; the panel must describe
    # the two people rather than coming back empty.
    ids = {u["full_name"]: u["id"] for u in J(await c.get("/chat/contacts", headers=d))}
    fin_id = ids.get("Finance Demo")
    if fin_id:
        r = J(await c.post("/chat/cross-dept-request", headers=s1,
                           json={"user_id": fin_id, "reason": f"payment status [{tag}]"}))
        cid = r.get("approval_request_id")
        if cid:
            p = J(await c.get(f"/approvals/{cid}/preview", headers=d))
            check("a request with no document still has a title",
                  p.get("title") == "Cross-department conversation", str(p)[:160])
            check("...naming both people", "Finance Demo" in (p.get("subtitle") or ""),
                  str(p.get("subtitle")))
            cf = {x["label"]: x["value"] for x in (p.get("fields") or [])}
            check("...and both departments", (cf.get("From"), cf.get("To")) == ("sales", "finance"),
                  str(cf))
            check("it carries the stated reason", f"payment status [{tag}]" in (p.get("notes") or ""),
                  str(p.get("notes")))
            await c.post(f"/approvals/{cid}/reject", headers=d, params={"notes": "test fixture"})

    # `e2e_dp_flow.py` runs last and asserts no customer_po request is left
    # pending, so this driver clears the one it filed.
    r = await c.post(f"/customer-pos/{po_id}/reject", headers=d,
                     json={"notes": "test fixture — not a real order"})
    check("the driver clears the PO it filed out of the approval queue",
          r.status_code == 200, f"{r.status_code} {str(J(r))[:120]}")

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")


asyncio.run(main())

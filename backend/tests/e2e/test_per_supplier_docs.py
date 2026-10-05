"""A job bought from two vendors files two sets of shipping documents.

Each vendor sends its own commercial invoice and packing list, and an imported
shipment brings its own Form E and bill of lading. The checklist used to be one
per project, so the second vendor's invoice could only be filed by overwriting
the first's. Now every supplier with a live PO on the job gets its own set and
its own delivery mode (one local, one imported is an ordinary job). Delivery is
confirmed only once every supplier's set is signed off.

Also here: the project page's supplier PO card carries each order's currency
and rate, so a yuan order no longer prints as rupiah.
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
PDF = b"%PDF-1.4 doc"


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=120)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    pur = await login("purchasing@demo.local")
    s1 = await login("sales1@demo.local")

    async def won_project(name):
        cust = J(await c.post("/customers", headers=s1, json={
            "company_name": f"PT {name} {TAG}", "industry": "mining"}))["id"]
        pr = J(await c.post("/price-requests", headers=s1, json={
            "customer_id": cust, "items": [{"description": f"CHAIN {TAG}", "qty": 10, "uom": "pcs"}]}))
        await c.post(f"/price-requests/{pr['id']}/submit", headers=s1)
        await c.post(f"/price-requests/{pr['id']}/price", headers=pur, json={
            "items": [{"line_no": 1, "cost_price": 1_000_000, "basis": "unit"}]})
        await c.post(f"/price-requests/{pr['id']}/approve", headers=d, json={
            "items": [{"line_no": 1, "sell_price": 2_000_000, "basis": "unit"}]})
        q = J(await c.post(f"/quotations/from-price-request/{pr['id']}", headers=s1))
        assert "id" in q, (pr, q)
        await c.post(f"/quotations/{q['id']}/submit", headers=s1)
        await c.post(f"/quotations/{q['id']}/approve", headers=d, json={"notes": ""})
        po = J(await c.post("/customer-pos", headers=s1, json={
            "customer_id": cust, "quotation_id": q["id"], "number": f"PO-{name}-{TAG}",
            "items": [{"description": f"CHAIN {TAG}", "qty": 10, "unit_price": 2_000_000}],
            "is_downpayment": False}))
        await c.post(f"/quotations/{q['id']}/won", headers=d)
        pid = J(await c.post(f"/customer-pos/{po['id']}/approve", headers=d,
                             json={"notes": ""})).get("project_id")
        r = await c.post(f"/operation/projects/{pid}/skip-drawing", headers=d,
                         json={"reason": "catalogue part"})
        assert r.status_code == 200, r.text
        return pid

    sup_gz = J(await c.post("/purchasing/suppliers", headers=pur, json={
        "name": f"Gui Zhou Chain {TAG}"}))["id"]
    sup_lokal = J(await c.post("/purchasing/suppliers", headers=pur, json={
        "name": f"PT Baut Lokal {TAG}"}))["id"]

    async def full(pid, who=d):
        return J(await c.get(f"/operation/projects/{pid}/full", headers=who))

    async def lg(pid, who=pur):
        return (await full(pid, who)).get("logistics") or {}

    def upload(pid, key, sid=None, who=pur, name=None):
        data = {"note": "test"}
        if sid:
            data["supplier_id"] = sid
        return c.post(f"/operation/projects/{pid}/import-docs/{key}/upload", headers=who,
                      files={"file": (name or f"{key}.pdf", PDF, "application/pdf")}, data=data)

    def decide(pid, key, sid=None, decision="approve", who=d):
        body = {"decision": decision}
        if sid:
            body["supplier_id"] = sid
        return c.post(f"/operation/projects/{pid}/import-docs/{key}/decide", headers=who, json=body)

    # ══ a job filed before it had any supplier PO keeps its documents ══════
    print("\n── documents filed before any order go to the first supplier ──")
    pid = await won_project("Dua")
    one = await lg(pid)
    check("no supplier yet: one checklist, as before",
          len(one.get("suppliers", [])) == 1 and one["suppliers"][0]["supplier_id"] is None
          and one.get("per_supplier") is False, str(one)[:200])
    r = await upload(pid, "invoice", name="early-invoice.pdf")
    check("an invoice can be filed with no supplier named", r.status_code == 200,
          f"{r.status_code} {J(r)}")

    # ══ two vendors on the job ══════════════════════════════════════════
    print("\n── two vendors, two sets ──")
    po_gz = J(await c.post("/purchasing/po", headers=d, json={
        "supplier_id": sup_gz, "project_id": pid, "po_date": "2026-08-19",
        "currency": "CNY", "fx_rate": 3000,
        "items": [{"description": f"CHAIN {TAG}", "qty": 10, "unit_price": 12727.33,
                   "amount": 127273.3}], "total": 127273.3}))
    po_lokal = J(await c.post("/purchasing/po", headers=d, json={
        "supplier_id": sup_lokal, "project_id": pid, "po_date": "2026-08-20",
        "items": [{"description": f"BOLT {TAG}", "qty": 100, "unit_price": 10_000,
                   "amount": 1_000_000}], "total": 1_000_000}))
    check("both orders are raised", bool(po_gz.get("id")) and bool(po_lokal.get("id")),
          f"{str(po_gz)[:120]} / {str(po_lokal)[:120]}")

    f = await full(pid)
    spos = {x["id"]: x for x in f.get("supplier_pos", [])}
    gz = spos.get(po_gz["id"], {})
    check("the project's yuan order carries its currency and rate",
          gz.get("currency") == "CNY" and gz.get("fx_rate") == 3000.0
          and abs((gz.get("total") or 0) - 127273.3) < 0.01, str(gz)[:200])
    check("...and the rupiah order says it is rupiah",
          spos.get(po_lokal["id"], {}).get("currency") == "IDR")

    L = await lg(pid)
    groups = L.get("suppliers", [])
    check("the checklist is split per supplier", L.get("per_supplier") is True
          and [g["supplier_id"] for g in groups] == [sup_gz, sup_lokal],
          str([(g["supplier_id"], g["supplier_name"]) for g in groups]))
    check("...each named, with its PO number",
          groups[0]["supplier_name"] == f"GUI ZHOU CHAIN {TAG}"
          and groups[0]["po_numbers"] == [po_gz["number"]], str(groups[0])[:200])
    early = groups[0]["required_docs"][0]
    check("the invoice filed before any order now sits with the first supplier",
          early["key"] == "invoice" and early["filename"] == "early-invoice.pdf"
          and early["status"] == "pending", str(early))
    check("...and not with the second", groups[1]["required_docs"][0]["attachment_id"] is None,
          str(groups[1]["required_docs"][0]))

    print("\n── each supplier its own delivery mode ──")
    r = await c.patch(f"/operation/projects/{pid}/logistics", headers=pur,
                      json={"delivery_mode": "direct_import", "supplier_id": sup_gz})
    L = J(r)
    g = {x["supplier_id"]: x for x in L.get("suppliers", [])}
    check("the Chinese vendor is a direct import",
          r.status_code == 200 and g[sup_gz]["delivery_mode"] == "direct_import"
          and [x["key"] for x in g[sup_gz]["required_docs"]]
          == ["invoice", "packing_list", "form_e", "bill_of_lading"],
          f"{r.status_code} {str(L)[:200]}")
    check("...the local one still needs only invoice and packing list",
          g[sup_lokal]["delivery_mode"] == "local"
          and [x["key"] for x in g[sup_lokal]["required_docs"]] == ["invoice", "packing_list"])
    check("six documents in all", len(L["required_docs"]) == 6, str(len(L["required_docs"])))
    r = await c.patch(f"/operation/projects/{pid}/logistics", headers=pur,
                      json={"delivery_mode": "agent", "supplier_id": str(uuid.uuid4())})
    check("a supplier not on the job is refused", r.status_code == 400, str(r.status_code))

    print("\n── two invoices, side by side ──")
    r = await upload(pid, "invoice", sup_lokal, name="lokal-invoice.pdf")
    g = {x["supplier_id"]: x for x in J(r).get("suppliers", [])}
    check("the local vendor's invoice is filed",
          r.status_code == 200 and g[sup_lokal]["required_docs"][0]["filename"] == "lokal-invoice.pdf",
          f"{r.status_code} {str(J(r))[:200]}")
    check("...without touching the Chinese vendor's",
          g[sup_gz]["required_docs"][0]["filename"] == "early-invoice.pdf",
          str(g[sup_gz]["required_docs"][0]))
    check("...two different files", g[sup_gz]["required_docs"][0]["attachment_id"]
          != g[sup_lokal]["required_docs"][0]["attachment_id"])
    r = await upload(pid, "invoice", str(uuid.uuid4()))
    check("filing for a supplier not on the job is refused", r.status_code == 400, str(r.status_code))

    for key in ("packing_list", "form_e", "bill_of_lading"):
        await upload(pid, key, sup_gz)
    await upload(pid, "packing_list", sup_lokal)

    inbox = J(await c.get("/approvals/pending-documents", headers=d))
    rows = inbox if isinstance(inbox, list) else (inbox.get("items") or inbox.get("data") or [])
    mine = [x for x in rows if x.get("kind") == "import_doc" and pid in str(x.get("link") or "")]
    body = mine[0]["body"] if mine else ""
    check("the director's inbox says whose documents are waiting",
          f"GUI ZHOU CHAIN {TAG}" in body and f"PT BAUT LOKAL {TAG}" in body
          and "Form E" in body, body[:300] or str(rows)[:200])

    print("\n── signing off, supplier by supplier ──")
    r = await decide(pid, "invoice", sup_gz, who=pur)
    check("purchasing cannot approve", r.status_code == 403, str(r.status_code))
    for key in ("invoice", "packing_list", "form_e", "bill_of_lading"):
        await decide(pid, key, sup_gz)
    L = await lg(pid)
    g = {x["supplier_id"]: x for x in L["suppliers"]}
    check("the Chinese vendor's set is approved", g[sup_gz]["docs_approved"] is True,
          str(g[sup_gz]["required_docs"])[:200])
    check("...the local one's is not, so the job is not", g[sup_lokal]["docs_approved"] is False
          and L["docs_approved"] is False)

    await c.patch(f"/operation/projects/{pid}/logistics", headers=pur,
                  json={"est_delivery_date": "2026-11-30"})
    r = await c.post(f"/operation/projects/{pid}/confirm-delivery", headers=pur)
    msg = str(J(r))
    check("delivery cannot be confirmed while one supplier's papers are open",
          r.status_code == 409 and f"PT BAUT LOKAL {TAG}" in msg, f"{r.status_code} {msg[:200]}")

    r = await upload(pid, "invoice", sup_gz, name="swap.pdf")
    check("an approved document can't be swapped by purchasing", r.status_code == 409,
          f"{r.status_code} {J(r)}")
    r = await upload(pid, "invoice", sup_lokal, name="lokal-invoice-v2.pdf")
    check("...while the other supplier's pending one still can",
          r.status_code == 200, f"{r.status_code} {J(r)}")

    await decide(pid, "invoice", sup_lokal)
    await decide(pid, "packing_list", sup_lokal)
    r = await c.post(f"/operation/projects/{pid}/confirm-delivery", headers=pur)
    check("with both sets signed off, delivery is confirmed",
          r.status_code == 200 and J(r).get("ok") is True, f"{r.status_code} {str(J(r))[:200]}")

    # ══ a cancelled order drops out ══════════════════════════════════════
    print("\n── an order that will not ship needs no papers ──")
    pid2 = await won_project("Batal")
    a = J(await c.post("/purchasing/po", headers=d, json={
        "supplier_id": sup_gz, "project_id": pid2, "po_date": "2026-08-19",
        "items": [{"description": "X", "qty": 1, "unit_price": 1, "amount": 1}], "total": 1}))
    b = J(await c.post("/purchasing/po", headers=d, json={
        "supplier_id": sup_lokal, "project_id": pid2, "po_date": "2026-08-19",
        "items": [{"description": "Y", "qty": 1, "unit_price": 1, "amount": 1}], "total": 1}))
    check("two suppliers, two sets", len((await lg(pid2))["suppliers"]) == 2)
    from app.core.db import SessionLocal
    from app.models.purchasing import SupplierPO
    async with SessionLocal() as s:
        (await s.get(SupplierPO, uuid.UUID(b["id"]))).status = "cancelled"
        await s.commit()
    L = await lg(pid2)
    check("cancel one and only the other's set is asked for",
          [x["supplier_id"] for x in L["suppliers"]] == [sup_gz]
          and L["per_supplier"] is False, str([x["supplier_id"] for x in L["suppliers"]]))

    print("\n── a single-supplier job works as it always did ──")
    pid3 = await won_project("Satu")
    await c.post("/purchasing/po", headers=d, json={
        "supplier_id": sup_lokal, "project_id": pid3, "po_date": "2026-08-19",
        "items": [{"description": "Z", "qty": 1, "unit_price": 1, "amount": 1}], "total": 1})
    for key in ("invoice", "packing_list"):
        await upload(pid3, key)
        await decide(pid3, key)
    await c.patch(f"/operation/projects/{pid3}/logistics", headers=pur,
                  json={"delivery_mode": "local", "est_delivery_date": "2026-11-30"})
    r = await c.post(f"/operation/projects/{pid3}/confirm-delivery", headers=pur)
    check("no supplier named anywhere, and it still goes through",
          r.status_code == 200, f"{r.status_code} {str(J(r))[:200]}")

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

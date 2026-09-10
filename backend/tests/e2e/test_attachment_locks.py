"""Who may unfile a document, and when it stops being unfilable.

Two rules, and they answer different questions.

**Whose file is it.** The director may remove anything. Everybody else — admin
included — may remove only what they attached themselves. Admin used to sit
with the director, which made the desk that files most of the paperwork also
the desk that could quietly unfile anybody else's. "I uploaded it" is a claim
only one person can make about a given file, so it is the cleanest boundary
available, and it leaves exactly one account able to override it.

**When it stops being a working copy.** A file on a live quotation is a draft
of something — the wrong revision, a blank scan, a duplicate — and removing it
is tidying. Once the deal is Won, the price request approved or the customer's
order signed off, that same file is part of what those decisions were made on,
and removing it edits the record behind a signature. Same for an approved
import document, which is what the director signed to let a delivery be
confirmed.

The import documents had a second hole worth its own section: uploading again
REPLACED the entry and reset it to pending, and the button offering that was
still there after approval. Nothing was deleted, so no delete rule caught it —
the approved file was simply swapped for another one underneath a signature
already given.

What must NOT be locked is checked too. This is a rule about the handful of
documents that carry a sign-off, not a freeze on the filing cabinet: a
customer's record, a supplier's paperwork, a project's ordinary shelf.
"""
import asyncio, os, sys, uuid
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123",
    STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import httpx, logging; logging.disable(logging.INFO)
TAG = uuid.uuid4().hex[:6]
PASS, FAIL = [], []
def check(n, c, d=""):
    (PASS if c else FAIL).append(n); print(("  PASS " if c else "  FAIL ")+n+(f"  [{d}]" if d and not c else ""))
def J(r):
    try: return r.json()
    except Exception: return {"_": r.text[:200]}
def why(r):
    b = J(r)
    return str(b.get("detail") or (b.get("errors") or [{}])[0].get("message", "")).lower()


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
    adm = await login("admin@demo.local")

    async def attach(owner_type, owner_id, name, headers):
        r = await c.post("/attachments", headers=headers,
                         files={"file": (name, b"scan", "text/plain")},
                         data={"owner_type": owner_type, "owner_id": str(owner_id)})
        return (J(r).get("id"), r.status_code)

    async def rm(att_id, headers):
        return await c.delete(f"/attachments/{att_id}", headers=headers)

    # ══ whose file is it ═════════════════════════════════════════════════
    print("\n── a file belongs to whoever attached it ──")
    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Berkas {TAG}", "industry": "mining"}))["id"]

    mine, code = await attach("customer", cust, "sales-note.pdf", s1)
    check("sales attaches a file", code == 201, str(code))
    r = await rm(mine, adm)
    check("admin cannot remove somebody else's", r.status_code == 403,
          f"{r.status_code} {why(r)}")
    check("...and is told whose it is", "somebody else" in why(r), why(r)[:140])
    r = await rm(mine, s1)
    check("the person who attached it can", r.status_code == 204,
          f"{r.status_code} {why(r)}")

    theirs, _ = await attach("customer", cust, "admin-note.pdf", adm)
    r = await rm(theirs, s1)
    check("and it cuts both ways — sales cannot remove admin's",
          r.status_code == 403, str(r.status_code))
    r = await rm(theirs, d)
    check("the director can remove anybody's", r.status_code == 204,
          f"{r.status_code} {why(r)}")

    # ══ a live quotation, then a won one ═════════════════════════════════
    print("\n── while a deal is live, its files are still working copies ──")
    pr = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [{"description": f"Chain {TAG}", "qty": 5, "uom": "pcs",
                   "category": "roller_chain"}]}))
    pr_file, _ = await attach("price_request", pr["id"], "spec.pdf", s1)
    r = await rm(pr_file, s1)
    check("a draft price request's file can be removed", r.status_code == 204,
          f"{r.status_code} {why(r)}")

    await c.post(f"/price-requests/{pr['id']}/submit", headers=s1)
    await c.post(f"/price-requests/{pr['id']}/price", headers=pur,
                 json={"items": [{"line_no": 1, "cost_price": 100, "basis": "unit"}]})
    await c.post(f"/price-requests/{pr['id']}/approve", headers=d,
                 json={"items": [{"line_no": 1, "sell_price": 200, "basis": "unit"}]})
    pr_file2, _ = await attach("price_request", pr["id"], "spec-rev.pdf", s1)
    r = await rm(pr_file2, s1)
    check("once the price request is approved, sales cannot",
          r.status_code == 409, f"{r.status_code} {why(r)}")
    check("...and the refusal names the document", pr["number"].lower() in why(r),
          why(r)[:160])
    r = await rm(pr_file2, d)
    check("...but the director still can", r.status_code == 204,
          f"{r.status_code} {why(r)}")

    q = J(await c.post(f"/quotations/from-price-request/{pr['id']}", headers=s1))
    q_file, _ = await attach("quotation", q["id"], "quote-draft.pdf", s1)
    r = await rm(q_file, s1)
    check("a quotation not yet won is still tidy-able", r.status_code == 204,
          f"{r.status_code} {why(r)}")

    await c.post(f"/quotations/{q['id']}/submit", headers=s1)
    await c.post(f"/quotations/{q['id']}/approve", headers=d, json={"decision": "approve"})
    cpo = J(await c.post("/customer-pos", headers=s1, json={
        "customer_id": cust, "quotation_id": q["id"], "number": f"CPO-{TAG}",
        "po_date": "2026-09-08",
        "items": [{"description": f"Chain {TAG}", "qty": 5, "unit_price": 200}]}))

    po_file, _ = await attach("customer_po", cpo["id"], "po-scan.pdf", s1)
    r = await rm(po_file, s1)
    check("a customer PO still pending is tidy-able", r.status_code == 204,
          f"{r.status_code} {why(r)}")

    await c.post(f"/customer-pos/{cpo['id']}/approve", headers=d, json={"decision": "approve"})
    po_file2, _ = await attach("customer_po", cpo["id"], "po-scan-2.pdf", s1)
    r = await rm(po_file2, s1)
    check("once the order is approved, sales cannot", r.status_code == 409,
          f"{r.status_code} {why(r)}")

    print("\n── and a won deal closes its own file ──")
    q_file2, _ = await attach("quotation", q["id"], "won-evidence.pdf", s1)
    r = await rm(q_file2, s1)
    check("the quotation is approved, not won — still removable",
          r.status_code == 204, f"{r.status_code} {why(r)}")
    await c.post(f"/quotations/{q['id']}/won", headers=d)
    q_file3, _ = await attach("quotation", q["id"], "after-won.pdf", s1)
    r = await rm(q_file3, s1)
    check("once it is Won, sales cannot", r.status_code == 409,
          f"{r.status_code} {why(r)}")
    check("...and the refusal says why", "won" in why(r), why(r)[:160])
    r = await rm(q_file3, d)
    check("...the director still can", r.status_code == 204,
          f"{r.status_code} {why(r)}")

    # ══ import documents ═════════════════════════════════════════════════
    print("\n── an approved import document is what a delivery was confirmed on ──")
    proj = J(await c.get(f"/customer-pos/{cpo['id']}", headers=d))["project_id"]
    await c.post(f"/operation/projects/{proj}/skip-drawing", headers=d,
                 json={"reason": "catalogue part"})
    await c.patch(f"/operation/projects/{proj}/logistics", headers=pur,
                  json={"delivery_mode": "local", "est_delivery_date": "2026-10-01"})

    r = await c.post(f"/operation/projects/{proj}/import-docs/invoice/upload",
                     headers=pur,
                     files={"file": ("inv.pdf", b"%PDF-1.4 a", "application/pdf")},
                     data={"note": "first"})
    check("purchasing files the commercial invoice", r.status_code == 200,
          f"{r.status_code} {why(r)}")

    r = await c.post(f"/operation/projects/{proj}/import-docs/invoice/upload",
                     headers=pur,
                     files={"file": ("inv2.pdf", b"%PDF-1.4 b", "application/pdf")},
                     data={"note": "corrected"})
    check("...and may replace it while it is still pending", r.status_code == 200,
          f"{r.status_code} {why(r)}")

    docs = J(await c.get(f"/operation/projects/{proj}/full", headers=pur))["logistics"]
    inv = next(x for x in docs["required_docs"] if x["key"] == "invoice")
    att_id = inv.get("attachment_id")
    r = await rm(att_id, pur)
    check("...and may remove it while it is still pending", r.status_code == 204,
          f"{r.status_code} {why(r)}")

    await c.post(f"/operation/projects/{proj}/import-docs/invoice/upload",
                 headers=pur,
                 files={"file": ("inv3.pdf", b"%PDF-1.4 c", "application/pdf")},
                 data={"note": "final"})
    r = await c.post(f"/operation/projects/{proj}/import-docs/invoice/decide",
                     headers=d, json={"decision": "approve"})
    check("the director approves it", r.status_code == 200, f"{r.status_code} {why(r)}")

    print("\n── so it cannot be swapped underneath that signature ──")
    r = await c.post(f"/operation/projects/{proj}/import-docs/invoice/upload",
                     headers=pur,
                     files={"file": ("swap.pdf", b"%PDF-1.4 z", "application/pdf")},
                     data={"note": "swapped"})
    check("purchasing can no longer replace an approved document",
          r.status_code == 409, f"{r.status_code} {why(r)}")
    check("...and is told the delivery was confirmed against it",
          "approved" in why(r), why(r)[:180])
    r = await c.post(f"/operation/projects/{proj}/import-docs/invoice/upload",
                     headers=d,
                     files={"file": ("swap.pdf", b"%PDF-1.4 z", "application/pdf")},
                     data={"note": "director replaces it"})
    check("...but the director may, having been the one who approved it",
          r.status_code == 200, f"{r.status_code} {why(r)}")

    print("\n── nor removed ──")
    await c.post(f"/operation/projects/{proj}/import-docs/invoice/decide",
                 headers=d, json={"decision": "approve"})
    docs = J(await c.get(f"/operation/projects/{proj}/full", headers=pur))["logistics"]
    inv = next(x for x in docs["required_docs"] if x["key"] == "invoice")
    r = await rm(inv.get("attachment_id"), pur)
    check("purchasing cannot remove an approved import document",
          r.status_code in (403, 409), f"{r.status_code} {why(r)}")

    # ══ what must NOT be locked ══════════════════════════════════════════
    print("\n── but this is not a freeze on the whole filing cabinet ──")
    later, _ = await attach("customer", cust, "still-fine.pdf", s1)
    r = await rm(later, s1)
    check("a customer's own record has no such moment", r.status_code == 204,
          f"{r.status_code} {why(r)}")

    shelf, code2 = await attach("project", proj, "site-photo.jpg", pur)
    check("a project's ordinary shelf takes a file", code2 == 201, str(code2))
    r = await rm(shelf, pur)
    check("...and it is not an import document, so it stays removable",
          r.status_code == 204, f"{r.status_code} {why(r)}")

    sup = J(await c.post("/purchasing/suppliers", headers=pur, json={
        "name": f"PT Vendor {TAG}", "country": "ID"}))["id"]
    sfile, _ = await attach("supplier", sup, "npwp.pdf", pur)
    r = await rm(sfile, pur)
    check("a supplier's paperwork is not locked either", r.status_code == 204,
          f"{r.status_code} {why(r)}")

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)


asyncio.run(main())

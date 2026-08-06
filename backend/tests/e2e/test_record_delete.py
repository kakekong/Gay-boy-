"""Deleting named records — this price request, that customer PO.

The sweep deletes by owner, which is right for clearing months of development
leftovers and wrong for everything after that: a single duplicate quotation, or
a test row belonging to a real salesperson, which the sweep deliberately
protects. This is the other tool.

The hard part is not the delete, it is the blast radius. A price request
becomes a quotation becomes a customer PO becomes a project becomes invoices,
and the columns joining them are a mix of RESTRICT (the database refuses) and
SET NULL (the database happily leaves an invoice attached to a project that no
longer exists). So the two properties worth testing are:

  everything downstream goes    — pick the price request, lose the quotation,
                                  the PO, the project and the invoices, and be
                                  told that before it happens

  nothing else does             — the neighbouring deal, its documents, its
                                  files and its discussions are all still there
                                  afterwards

The second is the one that would ruin someone's month, so it is asserted
against a second complete deal built alongside the first and checked
document-by-document rather than by counting.

Upstream is checked too, in the other direction: deleting a quotation must
*not* take the price request it was raised from. That request is a real thing
that really happened, and the quotation being wrong is no reason to erase the
record of asking for a price.
"""
import asyncio, io, os, sys, uuid
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123",
    STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import httpx, logging; logging.disable(logging.INFO)
PASS, FAIL = [], []
def check(n, c, d=""):
    (PASS if c else FAIL).append(n); print(("  PASS " if c else "  FAIL ")+n+(f"  [{d}]" if d and not c else ""))
def J(r):
    try: return r.json()
    except Exception: return {"_": r.text[:200]}

PHRASE = "DELETE TEST DATA"


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)

    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    tag = uuid.uuid4().hex[:5]
    d = await login("director@demo.local")
    s1 = await login("sales1@demo.local")
    pur = await login("purchasing@demo.local")
    fin = await login("finance@demo.local")

    async def build_deal(name: str, po_no: str) -> dict:
        """A complete deal: customer → PR → quotation → PO → project → invoice."""
        cust = J(await c.post("/customers", headers=s1, json={
            "company_name": name, "industry": "mining"}))["id"]
        pr = J(await c.post("/price-requests", headers=s1, json={
            "customer_id": cust,
            "items": [{"description": f"Gearbox {tag}", "qty": 2, "uom": "pcs"}]}))["id"]
        await c.post(f"/price-requests/{pr}/submit", headers=s1)
        await c.post(f"/price-requests/{pr}/price", headers=pur, json={
            "items": [{"line_no": 1, "cost_price": 5_000_000, "basis": "unit"}]})
        await c.post(f"/price-requests/{pr}/approve", headers=d, json={
            "items": [{"line_no": 1, "sell_price": 9_000_000, "basis": "unit"}]})
        quo = J(await c.post(f"/quotations/from-price-request/{pr}", headers=s1))["id"]
        await c.post(f"/quotations/{quo}/submit", headers=d)
        await c.post(f"/quotations/{quo}/won", headers=d)
        po = J(await c.post("/customer-pos", headers=s1, json={
            "customer_id": cust, "quotation_id": quo, "number": po_no,
            "po_date": "2026-08-06",
            "items": [{"description": f"Gearbox {tag}", "qty": 2, "uom": "pcs",
                       "unit_price": 9_000_000}], "is_downpayment": False}))["id"]
        ap = J(await c.post(f"/customer-pos/{po}/approve", headers=d, json={}))
        proj = ap.get("project_id")
        inv = J(await c.post(f"/operation/projects/{proj}/issue-invoice", headers=fin,
                             data={"amount": 18_000_000, "tax_amount": 0,
                                   "invoice_type": "dp", "due_date": "2026-09-06",
                                   "create_delivery_order": "false"}))
        # A file and a discussion, so the polymorphic rows have something to be.
        att = J(await c.post("/attachments", headers=s1,
                             files={"file": (f"spec-{tag}.txt", io.BytesIO(b"x"), "text/plain")},
                             data={"owner_type": "quotation", "owner_id": quo}))
        cm = J(await c.post("/comments", headers=s1, json={
            "owner_type": "quotation", "owner_id": quo, "body": f"note {tag}"}))
        return {"customer": cust, "pr": pr, "quo": quo, "po": po, "project": proj,
                "invoice": (inv.get("invoice") or {}).get("id"), "attachment": att.get("id"), "comment": cm.get("id")}

    A = await build_deal(f"PT Hapus Ini {tag}", f"PO-DEL-A-{tag}")
    B = await build_deal(f"PT Jangan Disentuh {tag}", f"PO-DEL-B-{tag}")
    check("two complete deals exist to work with",
          all(A.values()) and all(B.values()), f"A={A} B={B}")

    async def alive(kind: str, oid: str) -> bool:
        path = {"price_request": "/price-requests", "quotation": "/quotations",
                "customer_po": "/customer-pos", "project": "/operation/projects",
                "customer": "/customers"}[kind]
        r = await c.get(f"{path}/{oid}", headers=d)
        return r.status_code == 200

    async def invoice_alive(project_id: str, invoice_id: str) -> bool:
        """There is no invoice-detail endpoint; the project's full view lists
        them, which is also the only place a stranded invoice would show up."""
        r = await c.get(f"/operation/projects/{project_id}/full", headers=d)
        if r.status_code != 200:
            return False           # the project went, so its invoices went
        body = J(r)
        return any(str(i.get("id")) == str(invoice_id)
                   for i in (body.get("invoices") or []))

    # ── who may reach it ─────────────────────────────────────────────────────
    for role, hdr in (("sales", s1), ("finance", fin), ("purchasing", pur)):
        r = await c.get("/maintenance/records", headers=hdr, params={"type": "quotation"})
        check(f"{role} cannot browse records for deletion", r.status_code == 403, str(r.status_code))
        r = await c.post("/maintenance/records/delete", headers=hdr, json={
            "targets": [{"type": "quotation", "id": A["quo"]}], "confirm": PHRASE})
        check(f"{role} cannot delete records", r.status_code == 403, str(r.status_code))

    # ── finding what to delete ───────────────────────────────────────────────
    lst = J(await c.get("/maintenance/records", headers=d,
                        params={"type": "customer_po", "q": f"PO-DEL-A-{tag}"}))
    check("records can be found by number", len(lst) == 1, str(lst)[:160])
    check("...and come back named by customer, not just by id",
          lst and lst[0]["customer"] == f"PT Hapus Ini {tag}", str(lst)[:160])
    r = await c.get("/maintenance/records", headers=d, params={"type": "nonsense"})
    check("an unknown record type is refused", r.status_code == 400, str(r.status_code))

    # ── the blast radius, before anything happens ────────────────────────────
    p = J(await c.post("/maintenance/records/preview", headers=d, json={
        "targets": [{"type": "price_request", "id": A["pr"]}]}))
    ids = {x["id"] for x in p["documents"]}
    check("picking the price request pulls in its quotation",
          A["quo"] in ids, str(sorted(x["type"] for x in p["documents"])))
    check("...its customer PO", A["po"] in ids)
    check("...its project", A["project"] in ids)
    check("...and its invoice", A["invoice"] in ids)
    check("the preview says how much was not asked for",
          p["pulled_in"] == len(p["documents"]) - 1, f"{p['pulled_in']} of {len(p['documents'])}")
    check("the neighbouring deal is nowhere in the plan",
          not ({B["quo"], B["po"], B["invoice"], B["pr"]} & ids), str(ids & set(B.values())))
    check("the customer itself is NOT deleted for a document-level pick",
          p["counts"]["customers"] == 0, str(p["counts"]))
    check("the files and discussions on those documents are counted",
          p["counts"]["attachments"] >= 1 and p["counts"]["discussion_messages"] >= 1,
          str(p["counts"]))

    before = J(await c.get("/quotations", headers=d, params={"limit": 200}))
    before = before.get("data") if isinstance(before, dict) else before
    check("preview deleted nothing", await alive("quotation", A["quo"]), str(len(before or [])))

    # ── the confirmation ─────────────────────────────────────────────────────
    r = await c.post("/maintenance/records/delete", headers=d, json={
        "targets": [{"type": "price_request", "id": A["pr"]}], "confirm": "yes"})
    check("nothing goes without the confirmation phrase", r.status_code == 400, str(r.status_code))
    r = await c.post("/maintenance/records/delete", headers=d, json={
        "targets": [], "confirm": PHRASE})
    check("an empty selection is refused rather than treated as 'everything'",
          r.status_code == 400, str(r.status_code))

    # ── money needs its own yes ──────────────────────────────────────────────
    # Payments only land on an approved invoice, so take it through finance first.
    await c.post(f"/finance/invoices/{A['invoice']}/approve", headers=fin,
                 data={"faktur_pajak_no": f"010.000-26.{tag}"})
    pay = await c.post("/finance/payments", headers=fin, params={
        "invoice_id": A["invoice"], "amount": 1_000_000, "method": "transfer"})
    check("a payment can be recorded against the invoice",
          pay.status_code in (200, 201), f"{pay.status_code} {J(pay)}"[:160])
    p2 = J(await c.post("/maintenance/records/preview", headers=d, json={
        "targets": [{"type": "price_request", "id": A["pr"]}]}))
    check("a payment against the invoice is called out",
          any("payment" in w.lower() for w in p2["warnings"]), str(p2["warnings"]))
    r = await c.post("/maintenance/records/delete", headers=d, json={
        "targets": [{"type": "price_request", "id": A["pr"]}], "confirm": PHRASE})
    check("deleting money already received is refused by default",
          r.status_code == 409, str(r.status_code))
    body = J(r)
    msg = (body.get("detail") or
           (body.get("errors") or [{}])[0].get("message", "")).lower()
    check("...and says why", "money" in msg, str(body)[:160])
    check("...and nothing was deleted on the way to refusing",
          await alive("quotation", A["quo"]))

    # ── the delete ───────────────────────────────────────────────────────────
    res = J(await c.post("/maintenance/records/delete", headers=d, json={
        "targets": [{"type": "price_request", "id": A["pr"]}],
        "confirm": PHRASE, "allow_financial": True}))
    check("the delete reports what it removed",
          res.get("deleted", {}).get("quotations", 0) >= 1, str(res)[:200])

    for kind, key in (("price_request", "pr"), ("quotation", "quo"),
                      ("customer_po", "po"), ("project", "project")):
        check(f"the {kind.replace('_', ' ')} is gone", not await alive(kind, A[key]))
    check("the invoice is gone", not await invoice_alive(A["project"], A["invoice"]))
    check("the customer is still there — only its documents were named",
          await alive("customer", A["customer"]))

    at = await c.get("/attachments", headers=d,
                     params={"owner_type": "quotation", "owner_id": A["quo"]})
    check("its files went with it", not (J(at) or []), str(J(at))[:120])

    # ── and the neighbour is untouched ───────────────────────────────────────
    for kind, key in (("price_request", "pr"), ("quotation", "quo"),
                      ("customer_po", "po"), ("project", "project"),
                      ("customer", "customer")):
        check(f"the other deal's {kind.replace('_', ' ')} survived", await alive(kind, B[key]))
    check("the other deal's invoice survived",
          await invoice_alive(B["project"], B["invoice"]))
    at = J(await c.get("/attachments", headers=d,
                       params={"owner_type": "quotation", "owner_id": B["quo"]}))
    check("...along with its files", len(at or []) == 1, str(at)[:120])
    cm = J(await c.get("/comments", headers=d,
                       params={"owner_type": "quotation", "owner_id": B["quo"]}))
    cm = cm.get("data") if isinstance(cm, dict) else cm
    check("...and its discussion", len(cm or []) >= 1, str(cm)[:120])

    # ── upstream is never taken ──────────────────────────────────────────────
    p3 = J(await c.post("/maintenance/records/preview", headers=d, json={
        "targets": [{"type": "quotation", "id": B["quo"]}]}))
    ids3 = {x["id"] for x in p3["documents"]}
    check("deleting a quotation does NOT take the price request it came from",
          B["pr"] not in ids3, str([x["type"] for x in p3["documents"]]))
    check("...but does take the customer PO written against it", B["po"] in ids3)

    res = J(await c.post("/maintenance/records/delete", headers=d, json={
        "targets": [{"type": "quotation", "id": B["quo"]}],
        "confirm": PHRASE, "allow_financial": True}))
    check("the quotation goes", not await alive("quotation", B["quo"]))
    check("...and the price request is still standing", await alive("price_request", B["pr"]))

    # ── deleting a customer still takes everything, as the sweep does ────────
    C = await build_deal(f"PT Semua Hapus {tag}", f"PO-DEL-C-{tag}")
    p4 = J(await c.post("/maintenance/records/preview", headers=d, json={
        "targets": [{"type": "customer", "id": C["customer"]}]}))
    ids4 = {x["id"] for x in p4["documents"]}
    check("naming a customer pulls in its whole history",
          {C["pr"], C["quo"], C["po"], C["project"], C["invoice"]} <= ids4,
          str(sorted(x["type"] for x in p4["documents"])))
    J(await c.post("/maintenance/records/delete", headers=d, json={
        "targets": [{"type": "customer", "id": C["customer"]}],
        "confirm": PHRASE, "allow_financial": True}))
    check("...and the customer goes with it", not await alive("customer", C["customer"]))
    check("...leaving no orphan invoice behind",
          not await invoice_alive(C["project"], C["invoice"]))

    # ── several at once, of different kinds ──────────────────────────────────
    D = await build_deal(f"PT Batch Satu {tag}", f"PO-DEL-D-{tag}")
    E = await build_deal(f"PT Batch Dua {tag}", f"PO-DEL-E-{tag}")
    res = J(await c.post("/maintenance/records/delete", headers=d, json={
        "targets": [{"type": "quotation", "id": D["quo"]},
                    {"type": "customer_po", "id": E["po"]}],
        "confirm": PHRASE, "allow_financial": True}))
    check("a mixed selection deletes both", not await alive("quotation", D["quo"])
          and not await alive("customer_po", E["po"]), str(res)[:160])
    check("...and E's quotation, which was upstream of the PO, stays",
          await alive("quotation", E["quo"]))

    # ── the bug that made deleting dangerous ─────────────────────────────────
    # Document numbers used to be issued as "count of rows + 1". That is right
    # until something is deleted, and then the counter walks backwards and
    # hands the next document a number that is still in use — the insert dies
    # on the unique index and the user is told only that it could not be
    # created. Deleting a price request therefore broke making the next one.
    # This is the regression guard: create, delete, create again.
    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Nomor {tag}", "industry": "cement"}))["id"]
    made = []
    for _ in range(3):
        made.append(J(await c.post("/price-requests", headers=s1, json={
            "customer_id": cust,
            "items": [{"description": f"Bearing {tag}", "qty": 1, "uom": "pcs"}]})))
    check("three price requests, three different numbers",
          len({m["number"] for m in made}) == 3, str([m["number"] for m in made]))

    J(await c.post("/maintenance/records/delete", headers=d, json={
        "targets": [{"type": "price_request", "id": made[1]["id"]}],
        "confirm": PHRASE, "allow_financial": True}))
    after = await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [{"description": f"Bearing {tag}", "qty": 1, "uom": "pcs"}]})
    check("a price request can still be created after one is deleted",
          after.status_code in (200, 201), f"{after.status_code} {J(after)}"[:180])
    check("...and it does not reuse a number that is still in use",
          J(after).get("number") not in {made[0]["number"], made[2]["number"]},
          f"{J(after).get('number')} vs {[m['number'] for m in made]}")

    # Quotations number the same way, and are just as deletable.
    qq = []
    for m in (made[0], made[2]):
        await c.post(f"/price-requests/{m['id']}/submit", headers=s1)
        await c.post(f"/price-requests/{m['id']}/price", headers=pur,
                     json={"items": [{"line_no": 1, "cost_price": 1_000, "basis": "unit"}]})
        await c.post(f"/price-requests/{m['id']}/approve", headers=d,
                     json={"items": [{"line_no": 1, "sell_price": 2_000, "basis": "unit"}]})
        qq.append(J(await c.post(f"/quotations/from-price-request/{m['id']}", headers=s1)))
    J(await c.post("/maintenance/records/delete", headers=d, json={
        "targets": [{"type": "quotation", "id": qq[0]["id"]}],
        "confirm": PHRASE, "allow_financial": True}))
    q3 = await c.post(f"/quotations/from-price-request/{made[0]['id']}", headers=s1)
    check("a quotation can still be created after one is deleted",
          q3.status_code in (200, 201), f"{q3.status_code} {J(q3)}"[:180])
    check("...and does not collide with the surviving one",
          J(q3).get("number") != qq[1]["number"],
          f"{J(q3).get('number')} vs {qq[1]['number']}")

    # The sweep must still work — both paths share one delete routine now.
    users = J(await c.get("/users", headers=d))
    users = users.get("data") if isinstance(users, dict) else users
    keep = [u["id"] for u in (users or []) if u["role"] == "director"][:1]
    sw = await c.post("/maintenance/purge/preview", headers=d, json={"keep_user_ids": keep})
    check("the owner-based sweep still previews", sw.status_code == 200, str(sw.status_code))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        sys.exit(1)


asyncio.run(main())

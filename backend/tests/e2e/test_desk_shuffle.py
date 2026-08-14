"""Six rules moving work to the desk that actually does it.

Asked for as a list, and they mostly come down to one thing: several cards
were sitting in front of roles that never act on them, and the roles that do
act were locked out.

* **Import documents belong to procurement.** Purchasing collect the pack,
  the director signs it off. Admin and manager could both open the card and
  neither has ever chased a bill of lading, so it is gone from their page —
  and the director alone decides on one, because the other two approvers
  cannot read it any more.
* **Local and by-agent deliveries need an invoice and a packing list, and
  nothing else.** The customs paperwork is the agent's problem in the one
  case and doesn't exist in the other, so requiring it only stalled a
  delivery on a document nobody was going to produce.
* **Purchasing files the supplier's drawing again** — it briefly sat with
  the director — and both a drawing and an import document may now be filed
  as a *link* rather than an upload. The vendor mails a Drive folder; a link
  is the better record anyway, since a Space rebuild wipes uploaded files.
* **Admin issues the invoice + delivery order and puts the faktur pajak
  number on it.** They could already issue; the sign-off was finance-only,
  which left admin's own invoice waiting on someone else to type a number
  admin had in front of them. This reverses that separation of duties
  deliberately.
* **A PO line carries its unit price**, and the PO total is the sum of the
  lines. Only the header total was editable, so a renegotiated rate had to
  be back-solved by hand and the lines kept saying the old price.
* **A foreign-currency PO carries its exchange rate**, and finance may
  correct it once the bank settles — they read supplier POs for that reason
  and may change nothing else on one.
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


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=120)
    tag = uuid.uuid4().hex[:5]

    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    adm = await login("admin@demo.local")
    pur = await login("purchasing@demo.local")
    s1 = await login("sales1@demo.local")
    mgr = await login("manager@demo.local")
    fin = await login("finance@demo.local")

    # ── a live project ───────────────────────────────────────────────────────
    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Meja {tag}", "industry": "mining"}))["id"]
    pr = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [{"description": f"CHAIN {tag}", "qty": 10, "uom": "meter"}]}))
    await c.post(f"/price-requests/{pr['id']}/submit", headers=s1)
    await c.post(f"/price-requests/{pr['id']}/price", headers=pur, json={
        "items": [{"line_no": 1, "cost_price": 1_000_000, "basis": "unit"}]})
    await c.post(f"/price-requests/{pr['id']}/approve", headers=d, json={
        "items": [{"line_no": 1, "sell_price": 2_000_000, "basis": "unit"}]})
    q = J(await c.post(f"/quotations/from-price-request/{pr['id']}", headers=s1))
    await c.post(f"/quotations/{q['id']}/submit", headers=s1)
    await c.post(f"/quotations/{q['id']}/approve", headers=d, json={"notes": ""})
    cpo = J(await c.post("/customer-pos", headers=s1, json={
        "customer_id": cust, "quotation_id": q["id"], "number": f"CPO-D{tag}",
        "items": [{"description": f"CHAIN {tag}", "qty": 10, "unit_price": 2_000_000}],
        "is_downpayment": False}))
    await c.post(f"/quotations/{q['id']}/won", headers=d)
    proj = J(await c.post(f"/customer-pos/{cpo['id']}/approve", headers=d,
                          json={"notes": ""}))["project_id"]
    check("the job became a project", bool(proj), str(proj))

    async def full(headers):
        return J(await c.get(f"/operation/projects/{proj}/full", headers=headers))

    # Logistics only opens once the customer has a signed-off drawing, so get
    # one on the record before touching that card.
    cust_drw = J(await c.post(f"/operation/projects/{proj}/drawings", headers=adm,
                              data={"kind": "customer", "notes": f"for the customer {tag}"},
                              files={"file": ("customer.pdf", io.BytesIO(b"%PDF-1.4\n"),
                                              "application/pdf")}))
    await c.post(f"/operation/drawings/{cust_drw['id']}/decide", headers=d,
                 json={"decision": "approve"})

    # ══ 1. the customs pack is procurement's card ════════════════════════════
    print("\n── who opens the import documents ──")
    for who, label, allowed in ((pur, "purchasing", True), (d, "the director", True),
                                (adm, "admin", False), (mgr, "the manager", False),
                                (s1, "sales", False)):
        got = (await full(who)).get("logistics")
        check(f"{label} {'sees' if allowed else 'does not see'} the card",
              (got is not None) == allowed, str(got)[:80])

    r = await c.patch(f"/operation/projects/{proj}/logistics", headers=adm,
                      json={"delivery_mode": "agent"})
    check("admin cannot set the delivery mode either", r.status_code == 403,
          str(r.status_code))
    r = await c.patch(f"/operation/projects/{proj}/logistics", headers=pur,
                      json={"delivery_mode": "agent"})
    check("purchasing can", r.status_code == 200, f"{r.status_code} {J(r)}"[:120])

    # ══ 2. local and by-agent need two documents ═════════════════════════════
    print("\n── what a by-agent delivery has to collect ──")
    keys = [x["key"] for x in J(r)["required_docs"]]
    check("by agent: the invoice and the packing list", keys == ["invoice", "packing_list"],
          str(keys))
    r2 = await c.patch(f"/operation/projects/{proj}/logistics", headers=pur,
                       json={"delivery_mode": "local"})
    check("local: the same two", [x["key"] for x in J(r2)["required_docs"]]
          == ["invoice", "packing_list"], str([x["key"] for x in J(r2)["required_docs"]]))
    r3 = await c.patch(f"/operation/projects/{proj}/logistics", headers=pur,
                       json={"delivery_mode": "direct_import"})
    check("...while importing ourselves still needs the customs pack",
          [x["key"] for x in J(r3)["required_docs"]]
          == ["invoice", "packing_list", "form_e", "bill_of_lading"],
          str([x["key"] for x in J(r3)["required_docs"]]))
    await c.patch(f"/operation/projects/{proj}/logistics", headers=pur,
                  json={"delivery_mode": "agent"})

    # ══ 3a. purchasing files the supplier's drawing ══════════════════════════
    print("\n── who files the vendor's sheet ──")

    async def up(headers, kind, note, *, link=None):
        data = {"kind": kind, "notes": note}
        files = None
        if link:
            data["link_url"] = link
        else:
            files = {"file": (f"{kind}.pdf", io.BytesIO(b"%PDF-1.4\n"), "application/pdf")}
        return await c.post(f"/operation/projects/{proj}/drawings", headers=headers,
                            data=data, files=files)

    r = await up(pur, "supplier", f"vendor sheet {tag}")
    check("purchasing files the supplier's drawing", r.status_code == 201,
          f"{r.status_code} {J(r)}"[:140])
    sup_drw = J(r).get("id")
    r = await up(adm, "supplier", f"admin tries {tag}")
    check("...and admin still cannot", r.status_code == 403, str(r.status_code))
    r = await up(s1, "supplier", f"sales tries {tag}")
    check("...nor sales", r.status_code == 403, str(r.status_code))

    # ══ 3b. a link instead of a file ═════════════════════════════════════════
    print("\n── filing a link where the drawing already lives ──")
    url = f"https://drive.google.com/drive/folders/{tag}"
    r = await up(pur, "supplier", f"drive folder {tag}", link=url)
    check("purchasing can file a link instead of a file", r.status_code == 201,
          f"{r.status_code} {J(r)}"[:140])
    linked_id = J(r).get("id")

    rows = (await full(pur)).get("supplier_drawings") or []
    linked = next((x for x in rows if x["id"] == linked_id), None)
    check("the row comes back as a link", linked and linked.get("is_link") is True,
          str(linked)[:160])
    check("...carrying the URL to open", linked and linked.get("external_url") == url,
          str(linked.get("external_url")) if linked else "")
    uploaded = next((x for x in rows if x["id"] == sup_drw), None)
    check("...while an uploaded one is not a link",
          uploaded and not uploaded.get("is_link"), str(uploaded)[:120])

    r = await c.post(f"/operation/projects/{proj}/drawings", headers=pur,
                     data={"kind": "supplier", "notes": "nothing at all"})
    check("filing neither a file nor a link is refused", r.status_code == 400,
          f"{r.status_code} {J(r)}"[:120])

    # The link redirects rather than serving bytes, which is what tells the
    # page to link out instead of trying to preview it.
    if linked and linked.get("attachment_id"):
        rr = await c.get(f"/attachments/{linked['attachment_id']}/download",
                         headers=pur, follow_redirects=False)
        check("opening a linked drawing sends you to the vendor's folder",
              rr.status_code in (302, 307) and url in rr.headers.get("location", ""),
              f"{rr.status_code} {rr.headers.get('location')}")

    print("\n── and the same for an import document ──")
    r = await c.post(f"/operation/projects/{proj}/import-docs/invoice/upload",
                     headers=pur, data={"link_url": url, "note": "agent's folder"})
    check("an import document can be a link too", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:140])
    doc = next((x for x in J(r)["required_docs"] if x["key"] == "invoice"), None)
    check("...and the row says where it lives",
          doc and doc.get("external_url") == url, str(doc)[:160])
    r = await c.post(f"/operation/projects/{proj}/import-docs/packing_list/upload",
                     headers=pur, data={"note": "neither"})
    check("...with neither, refused", r.status_code == 400, str(r.status_code))
    r = await c.post(f"/operation/projects/{proj}/import-docs/invoice/decide",
                     headers=adm, json={"decision": "approve"})
    check("admin cannot sign off a document they cannot see", r.status_code == 403,
          str(r.status_code))
    r = await c.post(f"/operation/projects/{proj}/import-docs/invoice/decide",
                     headers=d, json={"decision": "approve"})
    check("the director can", r.status_code == 200, f"{r.status_code} {J(r)}"[:120])

    # ══ 4. admin runs the close-out ══════════════════════════════════════════
    print("\n── admin issues the invoice and signs the faktur pajak ──")
    r = await c.post(f"/operation/projects/{proj}/issue-invoice", headers=adm,
                     data={"invoice_type": "dp", "amount": "5000000",
                           "create_delivery_order": "false"})
    check("admin issues the invoice", r.status_code == 201,
          f"{r.status_code} {J(r)}"[:140])
    invs = (await full(adm)).get("invoices") or []
    check("...and it lands on the project", bool(invs), str(invs)[:120])
    iv = invs[0]["id"] if invs else None

    if iv:
        fp = f"010.000-26.{tag}"
        r = await c.post(f"/finance/invoices/{iv}/approve", headers=adm,
                         data={"faktur_pajak_no": fp})
        check("...and admin puts the faktur pajak number on it",
              r.status_code == 200, f"{r.status_code} {J(r)}"[:140])
        after = next((x for x in (await full(adm)).get("invoices") or []
                      if x["id"] == iv), None)
        check("...which sticks", after and after.get("faktur_pajak_no") == fp,
              str(after)[:160])

    # Widening the invoice desk must not open the rest of finance to admin.
    for path in ("/finance/ar/aging", "/finance/tax/report",
                 "/finance/invoices/pending", "/payments/claims"):
        r = await c.get(path, headers=adm)
        check(f"admin still refused {path}", r.status_code == 403,
              f"{path} → {r.status_code}")

    # ══ 5. a PO line carries its own price ═══════════════════════════════════
    print("\n── the price is on the line, not just the header ──")
    sup = J(await c.post("/purchasing/suppliers", headers=pur,
                         json={"name": f"PT Jiangsu {tag}"}))["id"]
    po = J(await c.post("/purchasing/po", headers=d, json={
        "supplier_id": sup, "project_id": proj, "currency": "USD",
        "items": [{"description": f"CHAIN {tag}", "qty": 10, "uom": "meter",
                   "unit_price": 100, "amount": 1000}],
        "total": 1000}))
    check("a PO in dollars was raised", po.get("id"), str(po)[:140])

    r = await c.patch(f"/purchasing/po/{po['id']}", headers=d, json={
        "items": [{"description": f"CHAIN {tag}", "qty": 10, "uom": "meter",
                   "unit_price": 120, "amount": 1200}],
        "total": 1200})
    check("the director re-prices a line", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:120])
    got = J(await c.get(f"/purchasing/po/{po['id']}", headers=pur))
    check("...the line says the new price",
          (got["items"][0].get("unit_price")) == 120, str(got["items"])[:140])
    check("...and the header agrees with it", float(got["total"]) == 1200.0,
          str(got["total"]))

    # ══ 6. what a dollar order is worth in rupiah ════════════════════════════
    print("\n── the rate that turns a dollar order into rupiah ──")
    check("a foreign order starts with no rate", got.get("fx_rate") is None,
          str(got.get("fx_rate")))
    check("...so its rupiah value is unknown, not zero",
          got.get("total_idr") is None, str(got.get("total_idr")))

    r = await c.get(f"/purchasing/po/{po['id']}", headers=fin)
    check("finance can open a supplier PO", r.status_code == 200, str(r.status_code))
    r = await c.get(f"/purchasing/po/{po['id']}", headers=adm)
    check("...and admin still cannot", r.status_code == 403, str(r.status_code))

    r = await c.patch(f"/purchasing/po/{po['id']}", headers=fin,
                      json={"fx_rate": 16250})
    check("finance sets the rate", r.status_code == 200, f"{r.status_code} {J(r)}"[:140])
    got = J(await c.get(f"/purchasing/po/{po['id']}", headers=fin))
    check("...applied straight away, not queued behind the director",
          float(got.get("fx_rate") or 0) == 16250.0, str(got.get("fx_rate")))
    check("...and the order reads as rupiah",
          float(got.get("total_idr") or 0) == 1200 * 16250.0, str(got.get("total_idr")))

    r = await c.patch(f"/purchasing/po/{po['id']}", headers=fin,
                      json={"fx_rate": 16400, "total": 1})
    check("finance cannot rewrite what we agreed with the vendor",
          r.status_code == 403, f"{r.status_code} {J(r)}"[:140])
    got = J(await c.get(f"/purchasing/po/{po['id']}", headers=fin))
    check("...and the refused edit changed nothing",
          float(got["total"]) == 1200.0 and float(got["fx_rate"]) == 16250.0,
          f"{got['total']} / {got['fx_rate']}")

    r = await c.patch(f"/purchasing/po/{po['id']}", headers=fin, json={"fx_rate": 0})
    check("a rate of zero is refused — it would zero the order",
          r.status_code == 400, str(r.status_code))

    # Switching currency must not carry the old rate across.
    await c.patch(f"/purchasing/po/{po['id']}", headers=d, json={"currency": "IDR"})
    got = J(await c.get(f"/purchasing/po/{po['id']}", headers=d))
    check("a rupiah order converts at 1", float(got.get("fx_rate") or 0) == 1.0,
          str(got.get("fx_rate")))
    check("...and needs no rate typed in",
          float(got.get("total_idr") or 0) == 1200.0, str(got.get("total_idr")))
    await c.patch(f"/purchasing/po/{po['id']}", headers=d, json={"currency": "CNY"})
    got = J(await c.get(f"/purchasing/po/{po['id']}", headers=d))
    check("switching currency drops the rate that belonged to the old one",
          got.get("fx_rate") is None, str(got.get("fx_rate")))

    idr_po = J(await c.post("/purchasing/po", headers=d, json={
        "supplier_id": sup, "project_id": proj,
        "items": [{"description": f"BOLT {tag}", "qty": 1, "uom": "pcs",
                   "unit_price": 500, "amount": 500}],
        "total": 500}))
    got = J(await c.get(f"/purchasing/po/{idr_po['id']}", headers=d))
    check("a new rupiah PO is born converting at 1",
          float(got.get("fx_rate") or 0) == 1.0, str(got.get("fx_rate")))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        sys.exit(1)


asyncio.run(main())

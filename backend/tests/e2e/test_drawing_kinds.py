"""Two drawings, two audiences — and admin moved to the customer side.

Asked for as one list of rules, which turn out to be one idea: the wall that
already runs between the customer side and the vendor side now runs through the
drawings too, and admin ends up on the customer side of it.

**A drawing is either the customer's or the supplier's.** The supplier's is
what the vendor sent us to make the part from; the customer's is what we put in
front of the customer to approve, drawn up *from* the supplier's rather than
being the same sheet forwarded on. They were one undifferentiated pile.

Who may do what, and the reason each rule exists:

* **Sales file neither and see only the customer's.** They were filing the
  customer's; they are its reader, not its author. The supplier's is the
  vendor relationship, which sales is kept out of everywhere else.
* **Purchasing file the supplier's and see only that** — the customer drawing
  carries the customer, and purchasing stays blind to that side.
* **Admin file the customer's and see only that.**
* **Manager and director see both**, which is what makes the handoff work:
  they take the supplier's drawing and produce the customer's from it, and the
  new drawing keeps a link back to the one it came off.

And approving the *supplier's* drawing must not advance the project — the
customer has not seen anything yet. Only the customer's sign-off does that.

The rest is admin losing the procurement side: no cost, no margin (which is
cost by subtraction), no supplier PO, and a shipment list that gives them the
dates without naming the vendor.
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


def pdf(tag: str) -> bytes:
    return b"%PDF-1.4\n% " + tag.encode() + b"\n"


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

    async def up(headers, project, kind, note, source=None):
        data = {"kind": kind, "notes": note}
        if source:
            data["source_drawing_id"] = source
        return await c.post(f"/operation/projects/{project}/drawings", headers=headers,
                            data=data,
                            files={"file": (f"{kind}.pdf", io.BytesIO(pdf(note)),
                                            "application/pdf")})

    # ── a live project with a costed, approved price request behind it ───────
    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Gambar {tag}", "industry": "mining"}))["id"]
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
        "customer_id": cust, "quotation_id": q["id"], "number": f"CPO-{tag}",
        "items": [{"description": f"CHAIN {tag}", "qty": 10, "unit_price": 2_000_000}],
        "is_downpayment": False}))
    await c.post(f"/quotations/{q['id']}/won", headers=d)
    proj = J(await c.post(f"/customer-pos/{cpo['id']}/approve", headers=d,
                          json={"notes": ""}))["project_id"]
    check("the job became a project", bool(proj), str(proj))

    # ══ who may file which ═══════════════════════════════════════════════════
    print("\n── who files what ──")
    r = await up(s1, proj, "customer", f"sales try {tag}")
    check("sales cannot file the customer's drawing", r.status_code == 403,
          f"{r.status_code} {J(r)}"[:140])
    r = await up(s1, proj, "supplier", f"sales try {tag}")
    check("...nor the supplier's", r.status_code == 403, str(r.status_code))

    # The vendor's sheet is filed by the people who deal with the vendor. It
    # briefly sat with the director instead — "for right now" — and has been
    # handed back to purchasing.
    r = await up(pur, proj, "customer", f"vendor tries {tag}")
    check("purchasing cannot file the customer's", r.status_code == 403,
          str(r.status_code))

    r = await up(pur, proj, "supplier", f"vendor sheet {tag}")
    check("purchasing files the supplier's", r.status_code == 201,
          f"{r.status_code} {J(r)}"[:140])
    sup_drw = J(r).get("id")
    check("...and it is recorded as one", J(r).get("kind") == "supplier",
          str(J(r).get("kind")))
    r = await up(d, proj, "supplier", f"director can too {tag}")
    check("...and management can still step in", r.status_code == 201,
          f"{r.status_code} {J(r)}"[:140])

    r = await up(adm, proj, "supplier", f"admin tries {tag}")
    check("admin cannot file a supplier drawing", r.status_code == 403,
          str(r.status_code))
    r = await up(adm, proj, "customer", f"for the customer {tag}")
    check("admin files the customer's", r.status_code == 201,
          f"{r.status_code} {J(r)}"[:140])
    cus_drw = J(r).get("id")

    r = await up(mgr, proj, "customer", f"redrawn {tag}", source=sup_drw)
    check("management can draw the customer's up from the supplier's",
          r.status_code == 201, f"{r.status_code} {J(r)}"[:140])
    redrawn = J(r)
    check("...keeping a link back to the sheet it came off",
          redrawn.get("source_drawing_id") == sup_drw,
          f"{redrawn.get('source_drawing_id')} vs {sup_drw}")
    check("...and numbering it in the customer series, not the supplier's",
          redrawn.get("revision") == 2, str(redrawn.get("revision")))

    r = await up(s1, proj, "customer", "x", source=sup_drw)
    check("nobody can work from a drawing they may not open",
          r.status_code == 403, str(r.status_code))
    r = await up(adm, proj, "customer", "x", source=sup_drw)
    check("...admin included", r.status_code == 403, str(r.status_code))

    r = await up(pur, proj, "sideways", f"bad kind {tag}")
    check("an unknown kind is refused", r.status_code == 400, str(r.status_code))

    # ══ who may see which ════════════════════════════════════════════════════
    print("\n── who sees what ──")

    async def seen(headers):
        got = J(await c.get(f"/operation/projects/{proj}/full", headers=headers))
        return ([x["id"] for x in (got.get("drawings") or [])],
                [x["id"] for x in (got.get("supplier_drawings") or [])])

    cus_seen, sup_seen = await seen(s1)
    check("sales see the customer's drawings", cus_drw in cus_seen, str(cus_seen))
    check("...and no supplier drawing at all", sup_seen == [], str(sup_seen))

    cus_seen, sup_seen = await seen(adm)
    check("admin see the customer's", cus_drw in cus_seen, str(cus_seen))
    check("...and not the supplier's", sup_seen == [], str(sup_seen))

    cus_seen, sup_seen = await seen(pur)
    check("purchasing see the supplier's", sup_drw in sup_seen, str(sup_seen))
    check("...and not the customer's", cus_seen == [], str(cus_seen))

    cus_seen, sup_seen = await seen(d)
    check("the director sees both", cus_drw in cus_seen and sup_drw in sup_seen,
          f"{cus_seen} / {sup_seen}")

    got = J(await c.get(f"/operation/projects/{proj}/full", headers=adm))
    check("the page is told what this role may file",
          got["may_upload_drawing"] == {"customer": True, "supplier": False},
          str(got.get("may_upload_drawing")))
    got = J(await c.get(f"/operation/projects/{proj}/full", headers=s1))
    check("...and sales are offered neither",
          got["may_upload_drawing"] == {"customer": False, "supplier": False},
          str(got.get("may_upload_drawing")))

    # ══ a row you can actually open ══════════════════════════════════════════
    # "View" renders the file in a modal rather than opening a window, because
    # a popup fired from the download's async callback is no longer a
    # user-initiated one and browsers block it. The modal is addressed by
    # attachment id and picks its renderer off the filename, so a row that
    # carries only a URL is a row whose View button can't do anything.
    print("\n── the row carries what the preview needs ──")
    got = J(await c.get(f"/operation/projects/{proj}/full", headers=d))
    rows = (got.get("drawings") or []) + (got.get("supplier_drawings") or [])
    check("the director sees rows on both cards", len(rows) >= 3, str(len(rows)))
    check("every drawing row names its attachment",
          all(r.get("attachment_id") for r in rows),
          str([(r.get("kind"), r.get("attachment_id")) for r in rows]))
    check("...and the file behind it",
          all((r.get("file_name") or "").endswith(".pdf") for r in rows),
          str([r.get("file_name") for r in rows]))
    check("...with the content type it was stored under",
          all(r.get("file_content_type") == "application/pdf" for r in rows),
          str([r.get("file_content_type") for r in rows]))
    check("...and the id is the one in the download URL",
          all(r["attachment_id"] in (r.get("file_url") or "") for r in rows),
          str([(r.get("attachment_id"), r.get("file_url")) for r in rows]))
    if rows:
        r = await c.get(f"/attachments/{rows[0]['attachment_id']}/download",
                        headers=d, params={"inline": 1})
        check("...so the preview's own request succeeds", r.status_code == 200,
              str(r.status_code))

    # ══ the file behind the drawing ══════════════════════════════════════════
    # The card can hide a row and still leave the file reachable: a drawing's
    # PDF is stored as an ordinary project attachment, which every internal
    # role could list and download. Hiding the row while leaving the file is
    # not hiding anything.
    print("\n── the file itself, not just the row ──")
    sup_att = J(await c.get("/attachments", headers=pur,
                            params={"owner_type": "project", "owner_id": proj}))
    sup_file = next((a for a in sup_att if (a.get("filename") or "").startswith("supplier")), None)
    check("purchasing can list the supplier drawing's file", sup_file is not None,
          str([a.get("filename") for a in sup_att]))

    for who, label in ((adm, "admin"), (s1, "sales")):
        listed = J(await c.get("/attachments", headers=who,
                               params={"owner_type": "project", "owner_id": proj}))
        names = [a.get("filename") for a in listed]
        check(f"{label} cannot list it", "supplier.pdf" not in names, str(names))
        if sup_file:
            r = await c.get(f"/attachments/{sup_file['id']}/download", headers=who)
            check(f"...nor download it directly", r.status_code == 403,
                  str(r.status_code))
        cus = next((a for a in listed if a.get("filename") == "customer.pdf"), None)
        check(f"...while the customer's file is still theirs to open",
              cus is not None, str(names))
        if cus:
            r = await c.get(f"/attachments/{cus['id']}/download", headers=who)
            check("...and downloads", r.status_code == 200, str(r.status_code))

    if sup_file:
        r = await c.get(f"/attachments/{sup_file['id']}/download", headers=d)
        check("the director can still open it", r.status_code == 200, str(r.status_code))

    # ══ the sign-off, and what it moves ══════════════════════════════════════
    print("\n── approving one is not approving the other ──")
    before = J(await c.get(f"/operation/projects/{proj}/full", headers=d))["project"]["status"]
    r = await c.post(f"/operation/drawings/{sup_drw}/decide", headers=adm,
                     json={"decision": "approve"})
    check("admin cannot sign off a drawing they cannot see", r.status_code == 403,
          str(r.status_code))
    r = await c.post(f"/operation/drawings/{sup_drw}/decide", headers=d,
                     json={"decision": "approve"})
    check("the director signs off the supplier's", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:140])
    after = J(await c.get(f"/operation/projects/{proj}/full", headers=d))["project"]["status"]
    check("...and the job does not move — the customer has seen nothing yet",
          after == before, f"{before} → {after}")

    r = await c.post(f"/operation/drawings/{cus_drw}/decide", headers=d,
                     json={"decision": "approve"})
    check("the director signs off the customer's", r.status_code == 200,
          str(r.status_code))
    after = J(await c.get(f"/operation/projects/{proj}/full", headers=d))["project"]["status"]
    check("...and that is what advances the job", after == "drawing_approved",
          f"{before} → {after}")

    # ══ admin is on the customer side of the wall now ════════════════════════
    print("\n── what admin may no longer see ──")
    got = J(await c.get(f"/operation/projects/{proj}/full", headers=adm))
    line = (got.get("price_request") or {}).get("items", [{}])[0]
    check("no buying cost on the price request behind the job",
          "cost_price" not in line, str(line))
    check("...but the customer's own order value is still theirs",
          got["project"]["po_value"] is not None, str(got["project"]["po_value"]))
    check("...and no margin, which is the cost by subtraction",
          got["project"]["margin_estimate"] is None
          and got["project"]["margin_actual"] is None,
          f"{got['project']['margin_estimate']} {got['project']['margin_actual']}")

    dgot = J(await c.get(f"/operation/projects/{proj}/full", headers=d))
    check("the director still sees both figures",
          dgot["project"]["margin_estimate"] is not None
          and (dgot.get("price_request") or {}).get("items", [{}])[0].get("cost_price")
          is not None, str(dgot["project"]["margin_estimate"]))

    pr_seen = J(await c.get(f"/price-requests/{pr['id']}", headers=adm))
    check("nor a cost on the price request itself",
          all("cost_price" not in i for i in pr_seen.get("items", [])),
          str(pr_seen.get("items"))[:200])
    r = await c.post(f"/price-requests/{pr['id']}/price", headers=adm, json={
        "items": [{"line_no": 1, "cost_price": 5, "basis": "unit"}]})
    check("...and admin cannot type one in either", r.status_code == 403,
          str(r.status_code))

    print("\n── and the supplier side is closed to them ──")
    sup = J(await c.post("/purchasing/suppliers", headers=pur, json={
        "name": f"PT Rahasia {tag}"}))["id"]
    po = J(await c.post("/purchasing/po", headers=d, json={
        "supplier_id": sup, "project_id": proj, "eta": "2026-11-01",
        "items": [{"description": f"CHAIN {tag}", "qty": 10, "uom": "meter",
                   "unit_price": 1_000_000, "amount": 10_000_000}],
        "total": 10_000_000}))
    for path, label in ((f"/purchasing/po", "the supplier PO list"),
                        (f"/purchasing/po/{po['id']}", "a supplier PO"),
                        (f"/purchasing/po/{po['id']}/export.pdf", "its printed copy"),
                        ("/purchasing/price-requests", "the buy-side price requests")):
        r = await c.get(path, headers=adm)
        check(f"admin is refused {label}", r.status_code == 403,
              f"{path} → {r.status_code}")

    ship = J(await c.get(f"/purchasing/po/for-project/{proj}", headers=adm))
    check("admin still get the shipments — the dates are their job",
          len(ship.get("shipments", [])) == 1, str(ship)[:160])
    one = ship["shipments"][0]
    check("...with the arrival date on it", one["eta"] == "2026-11-01", str(one["eta"]))
    check("...and the vendor stripped out",
          one["supplier_name"] is None and one["supplier_id"] is None
          and one["po_id"] is None and one["number"] is None, str(one)[:220])
    check("...including off every line", all(i["supplier_name"] is None
                                             for i in one["items"]), str(one["items"]))
    check("...and what we paid them", one["total_for_project"] is None,
          str(one["total_for_project"]))
    check("...while still saying how many are coming and from how many places",
          ship["supplier_count"] == 1, str(ship["supplier_count"]))
    check("no vendor name survives anywhere in that payload",
          f"PT Rahasia {tag}" not in str(ship), str(ship)[:250])

    # The project page carries its own list of supplier orders. Scrubbing the
    # shipments card while that one still names the vendor would be theatre.
    full_adm = J(await c.get(f"/operation/projects/{proj}/full", headers=adm))
    check("the project page hands admin no supplier orders at all",
          full_adm.get("supplier_pos") == [], str(full_adm.get("supplier_pos"))[:200])
    check("...and no vendor name anywhere in the whole payload",
          f"PT Rahasia {tag}" not in str(full_adm),
          [k for k in full_adm if f"PT Rahasia {tag}" in str(full_adm[k])])
    full_dir = J(await c.get(f"/operation/projects/{proj}/full", headers=d))
    check("the director still gets them", len(full_dir.get("supplier_pos") or []) == 1,
          str(len(full_dir.get("supplier_pos") or [])))

    pship = J(await c.get(f"/purchasing/po/for-project/{proj}", headers=pur))
    check("purchasing still see the vendor on theirs",
          pship["shipments"][0]["supplier_name"] == f"PT Rahasia {tag}",
          str(pship["shipments"][0]["supplier_name"]))

    # ══ the neighbours that could undo all of it ═════════════════════════════
    # Hiding a drawing in one place and leaving it reachable in another is not
    # hiding it. These are the other doors onto the same document.
    print("\n── the other doors ──")

    # The customer portal. A vendor's sheet reaching the customer would hand
    # them the supplier relationship, and approving one advances the job.
    pemail = f"pu{tag}@demo.local"
    await c.post("/users", headers=d, json={
        "email": pemail, "full_name": f"Portal {tag}", "role": "customer",
        "password": "test-pass-123", "linked_customer_id": cust})
    cu = await login(pemail)
    seen_port = J(await c.get("/portal/customer/projects", headers=cu))
    rows = seen_port if isinstance(seen_port, list) else seen_port.get("items", [])
    mine_p = next((x for x in rows if x["id"] == proj), None)
    check("the customer's portal shows their project", mine_p is not None,
          str([x.get("code") for x in rows])[:150])
    if mine_p:
        ids = [x["id"] for x in (mine_p.get("drawings") or [])]
        check("...listing only the drawings meant for them",
              cus_drw in ids and sup_drw not in ids, str(ids))
        check("...each one openable in the portal's preview",
              all(x.get("attachment_id") for x in (mine_p.get("drawings") or [])),
              str([x.get("attachment_id") for x in (mine_p.get("drawings") or [])]))
    r = await c.post(f"/portal/customer/drawings/{sup_drw}/decide", headers=cu,
                     params={"decision": "approve"})
    check("a customer cannot approve the vendor's sheet", r.status_code == 403,
          f"{r.status_code} {J(r)}"[:130])

    # The portal links straight at the attachment, so the file has to open for
    # the customer — and only the one that is theirs.
    cus_att = next((a for a in J(await c.get("/attachments", headers=d,
                                             params={"owner_type": "project",
                                                     "owner_id": proj}))
                    if (a.get("filename") or "").startswith("customer")), None)
    if cus_att:
        r = await c.get(f"/attachments/{cus_att['id']}/download", headers=cu)
        check("the customer can still open their own drawing", r.status_code == 200,
              str(r.status_code))
    if sup_file:
        r = await c.get(f"/attachments/{sup_file['id']}/download", headers=cu)
        check("...and never the vendor's", r.status_code == 403, str(r.status_code))

    # A customer's summary carries a margin per project — and a margin beside
    # the PO value is the buying cost by subtraction. Reachable by any internal
    # role over the API, whatever the sidebar shows.
    summ = J(await c.get(f"/customers/{cust}/summary", headers=adm))
    proj_rows = summ.get("projects") or []
    check("the customer summary opens for admin", bool(proj_rows), str(summ)[:120])
    check("...with no margin on it",
          all(r.get("margin_estimate") is None and r.get("margin_actual") is None
              for r in proj_rows), str(proj_rows)[:200])
    dsumm = J(await c.get(f"/customers/{cust}/summary", headers=d))
    check("...while the director still gets one",
          any(r.get("margin_estimate") is not None
              for r in (dsumm.get("projects") or [])),
          str(dsumm.get("projects"))[:200])

    # Deleting, and revising, are the same wall.
    r = await c.delete(f"/operation/drawings/{sup_drw}", headers=adm)
    check("admin cannot delete a drawing they cannot see", r.status_code == 403,
          str(r.status_code))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        sys.exit(1)


asyncio.run(main())

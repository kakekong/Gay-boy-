"""The delivery order goes to the director's inbox, and has a screen of its own.

Asked for, on a row of the project's Deliveries table: *"Make approval to
director inbox and make it approve and make it so that its more visible and
make it so that there's a preview and also make it so that when clicking the
DO make it so that like the quo or PO screen where it shows the same menu with
the same edit ui."*

Five things, and they are all the same complaint. A delivery order was raised
on the project page, and then it sat there. Nothing told the director it
existed — no card in the inbox, no count on the bell — so it waited until
somebody happened to open that project and notice a grey chip. When they did
notice, the only thing to decide on was the chip: five columns of a table,
none of which were the goods. And the sheet the customer signs, generated from
that row, could not be looked at until after it had been released.

So:

**It is filed like every other decision.** Raising a delivery order files a
director approval request. It shows in the inbox with the rest, and approving
it there is the release — the same act as the button on the project page, and
either one closes the other.

**The decision is made on the document.** The preview carries the lines, the
destination and the customer's own PO number; and the sheet itself, rendered
exactly as it would print, stamped DRAFT across every page. Unstamped, it is
still refused until release — nobody hands a customer a document nobody
signed.

**Rejecting is not a dead end.** It changes nothing on the delivery order,
which is the point: the sheet stays editable, the reason is on the row, and
correcting it files the request again.

**And it has its own screen.** `/deliveries/:id` — the number, the customer,
the lines, the remarks, the files, the discussion, and the same edit that a
quotation or a purchase order has had all along.
"""
import asyncio, os, sys, uuid
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


def pdf_text(blob: bytes) -> str:
    try:
        import fitz
        with fitz.open(stream=blob, filetype="pdf") as doc:
            return "\n".join(p.get_text() for p in doc)
    except Exception as e:  # noqa: BLE001
        return f"__unreadable__ {e}"


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)
    tag = uuid.uuid4().hex[:5]

    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    adm = await login("admin@demo.local")
    fin = await login("finance@demo.local")
    s1 = await login("sales1@demo.local")
    mgr = await login("manager@demo.local")
    pur = await login("purchasing@demo.local")

    # ── a job that has passed QC, so a delivery order may be raised ─────────
    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Kirim {tag}", "industry": "mining",
        "delivery_address": f"SITE TABALONG {tag}"}))["id"]
    pr = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [{"description": f"CHAIN {tag}", "qty": 4, "uom": "EA"}]}))["id"]
    await c.post(f"/price-requests/{pr}/submit", headers=s1)
    await c.post(f"/price-requests/{pr}/price", headers=d,
                 json={"items": [{"line_no": 1, "cost_price": 500000, "basis": "unit"}]})
    await c.post(f"/price-requests/{pr}/approve", headers=d,
                 json={"items": [{"line_no": 1, "sell_price": 1000000, "basis": "unit"}]})
    q = J(await c.post(f"/quotations/from-price-request/{pr}", headers=s1))
    await c.post(f"/quotations/{q['id']}/submit", headers=s1)
    await c.post(f"/quotations/{q['id']}/approve", headers=d, json={"notes": ""})
    po_no = f"PO-DOI-{tag}"
    cpo = J(await c.post("/customer-pos", headers=s1, json={
        "customer_id": cust, "quotation_id": q["id"], "number": po_no,
        "items": [{"description": f"CHAIN {tag}", "qty": 4, "uom": "EA",
                   "unit_price": 1000000}],
        "is_downpayment": False}))["id"]
    await c.post(f"/quotations/{q['id']}/won", headers=d)
    proj = J(await c.post(f"/customer-pos/{cpo}/approve", headers=d,
                          json={"notes": ""}))["project_id"]
    await c.post(f"/operation/projects/{proj}/qc", headers=adm, json={"decision": "pass"})

    async def full(hdr=None):
        return J(await c.get(f"/operation/projects/{proj}/full", headers=hdr or d))

    async def inbox(hdr=None):
        return J(await c.get("/approvals", headers=hdr or d))

    # ══ raising one files it with the director ═══════════════════════════════
    print("\n── the admin desk raises a delivery order ──")
    r = await c.post(f"/operation/projects/{proj}/delivery-order", headers=adm,
                     json={"items": [{"description": f"CHAIN {tag}", "qty": 2,
                                      "uom": "EA"}]})
    check("the delivery order is raised", r.status_code == 201,
          f"{r.status_code} {J(r)}"[:170])
    do = J(r)["delivery_order"]
    do_id, do_no = do["id"], do["number"]

    rows = await inbox()
    mine = [x for x in rows if x["target_type"] == "delivery_order"
            and x["target_id"] == do_id]
    check("...and lands in the director's approval inbox", len(mine) == 1,
          str([x["target_type"] for x in rows])[:200])
    req = mine[0] if mine else {}
    check("...labelled with its number", req.get("target_label") == do_no,
          str(req.get("target_label")))
    check("...addressed to the director", req.get("required_role") == "director",
          str(req.get("required_role")))
    check("...naming who raised it", (req.get("requester_name") or "").strip() != "",
          str(req.get("requester_name")))

    # It is on the bell, which is what "more visible" means when nobody is
    # looking at the approvals page.
    notif = J(await c.get("/notifications", headers=d))
    blob = str(notif)
    check("...and the notification bell counts it", do_no in blob or
          any("approval" in str(k).lower() for k in (notif or {})), blob[:220])

    # The manager's queue is manager-level work; this one is the director's.
    check("a manager's inbox does not carry the director's release",
          not [x for x in J(await c.get("/approvals", headers=mgr))
               if x.get("target_id") == do_id],
          "shown to the manager")

    # ══ what the director is actually deciding ═══════════════════════════════
    print("\n── the preview ──")
    pv = J(await c.get(f"/approvals/{req['id']}/preview", headers=d))
    check("the preview is the document, not the request",
          pv.get("title") == do_no, str(pv.get("title")))
    check("...naming the customer", f"PT Kirim {tag}" == (pv.get("subtitle") or ""),
          str(pv.get("subtitle")))
    check("...with the goods on it",
          len(pv.get("items") or []) == 1
          and str(pv["items"][0]["description"]).startswith("CHAIN"),
          str(pv.get("items"))[:200])
    check("...the count that is on the truck",
          float((pv.get("items") or [{}])[0].get("qty") or 0) == 2.0,
          str(pv.get("items"))[:200])
    check("...and no money anywhere on it — it is signed at a gate",
          all(i.get("unit_price") is None and i.get("line_total") is None
              for i in (pv.get("items") or [])) and pv.get("total") is None,
          str(pv.get("items"))[:200])
    fields = {f["label"]: f["value"] for f in (pv.get("fields") or [])}
    check("...the customer's own PO as the reference",
          fields.get("Customer PO") == po_no, str(fields))
    check("...where the goods are going", tag in (pv.get("notes") or ""),
          str(pv.get("notes")))
    check("...and a link to the document's own screen",
          pv.get("link") == f"/deliveries/{do_id}", str(pv.get("link")))
    check("...plus the sheet itself, as a draft",
          (pv.get("pdf_url") or "").endswith(f"/deliveries/{do_id}/pdf?draft=1"),
          str(pv.get("pdf_url")))

    print("\n── the sheet, before anybody releases it ──")
    r = await c.get(f"/operation/deliveries/{do_id}/pdf", headers=d)
    check("the real sheet is still refused before release", r.status_code == 409,
          f"{r.status_code} {J(r)}"[:150])
    r = await c.get(f"/operation/deliveries/{do_id}/pdf", headers=d,
                    params={"draft": 1})
    check("the draft renders", r.status_code == 200 and r.content[:4] == b"%PDF",
          f"{r.status_code} {r.content[:20]}")
    sheet = pdf_text(r.content)
    check("...stamped DRAFT so nobody can hand it over", "DRAFT" in sheet.upper(),
          sheet[:300])
    check("...and says so in Indonesian too",
          "BELUM DISETUJUI" in sheet.upper(), sheet[:400])
    check("...but is otherwise the real document",
          "SURAT JALAN" in sheet.upper() and f"PT KIRIM {tag}".upper() in sheet.upper()
          and po_no in sheet, sheet[:600])
    check("...carrying the goods and the count",
          "CHAIN" in sheet.upper(), sheet[:700])
    r = await c.get(f"/operation/deliveries/{do_id}/pdf", headers=s1,
                    params={"draft": 1})
    check("sales cannot pull the draft either", r.status_code in (401, 403),
          str(r.status_code))

    # ══ approving it from the inbox releases it ══════════════════════════════
    print("\n── the director approves it from the inbox ──")
    r = await c.post(f"/approvals/{req['id']}/approve", headers=d)
    check("the decision goes through", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:170])
    check("...and says what it did to the document",
          J(r).get("applied", {}).get("new_status") == "approved",
          str(J(r).get("applied"))[:170])
    row = next(x for x in (await full())["deliveries"] if x["id"] == do_id)
    check("the delivery order is released", bool(row["approved_at"]), str(row)[:200])
    check("...by the person who signed it",
          (row.get("approved_by_name") or "").strip() != "",
          str(row.get("approved_by_name")))
    check("...and the inbox stops asking",
          not [x for x in await inbox() if x["target_id"] == do_id],
          "still queued")
    r = await c.get(f"/operation/deliveries/{do_id}/pdf", headers=adm)
    check("now the sheet prints", r.status_code == 200 and r.content[:4] == b"%PDF",
          f"{r.status_code} {r.content[:20]}")
    sheet = pdf_text(r.content)
    check("...with no DRAFT on it any more", "DRAFT" not in sheet.upper(),
          sheet[:300])
    r = await c.get(f"/operation/deliveries/{do_id}/pdf", headers=adm,
                    params={"draft": 1})
    check("...and asking for a draft of a released sheet gives the real one",
          r.status_code == 200 and "DRAFT" not in pdf_text(r.content).upper(),
          str(r.status_code))

    # ══ withdrawing it puts it back ══════════════════════════════════════════
    print("\n── withdrawing the release ──")
    r = await c.post(f"/operation/deliveries/{do_id}/unapprove", headers=d)
    check("the director can withdraw it", r.status_code == 200, str(r.status_code))
    back = [x for x in await inbox() if x["target_id"] == do_id]
    check("...and it is back in the inbox, because it needs releasing again",
          len(back) == 1, str(len(back)))
    r = await c.post(f"/operation/deliveries/{do_id}/approve", headers=d)
    check("releasing it on the project page works too", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:150])
    check("...and closes the inbox card, so nobody signs it twice",
          not [x for x in await inbox() if x["target_id"] == do_id],
          "still queued after the project-page approval")

    # ══ rejecting sends it back to the desk ══════════════════════════════════
    print("\n── a second shipment, sent back ──")
    do2 = J(await c.post(f"/operation/projects/{proj}/delivery-order", headers=adm,
                         json={"items": [{"description": f"CHAIN {tag}", "qty": 2,
                                          "uom": "EA"}]}))["delivery_order"]
    req2 = next(x for x in await inbox() if x["target_id"] == do2["id"])
    why = f"Wrong site address — {tag}"
    r = await c.post(f"/approvals/{req2['id']}/reject", headers=d,
                     params={"notes": why})
    check("the director can send it back", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:150])
    row2 = next(x for x in (await full())["deliveries"] if x["id"] == do2["id"])
    check("...which releases nothing", not row2["approved_at"], str(row2)[:150])
    check("...and the project page says it came back",
          (row2.get("approval") or {}).get("status") == "rejected",
          str(row2.get("approval")))
    check("...with the reason on it, so nobody has to go and ask",
          why in ((row2.get("approval") or {}).get("notes") or ""),
          str(row2.get("approval")))
    r = await c.patch(f"/operation/deliveries/{do2['id']}", headers=adm,
                      json={"remarks": f"BARANG DI KIRIM KE:\nSITE PROPER {tag}"})
    check("the desk can still correct it — that is what a rejection is for",
          r.status_code == 200, f"{r.status_code} {J(r)}"[:150])
    again = [x for x in await inbox() if x["target_id"] == do2["id"]]
    check("...and correcting it asks the director again",
          len(again) == 1, str(len(again)))
    docs = J(await c.get("/approvals/pending-documents", headers=d))
    check("...without also nagging from the documents list — it is a card now",
          not [x for x in docs if x.get("kind") == "delivery_order"
               and do2["number"] in x.get("title", "")],
          str([x.get("title") for x in docs])[:200])

    # ══ deleting one takes its request with it ═══════════════════════════════
    print("\n── withdrawing the document itself ──")
    do3 = J(await c.post(f"/operation/projects/{proj}/delivery-order", headers=adm,
                         json={"items": [{"description": f"CHAIN {tag}", "qty": 1,
                                          "uom": "EA"}]}))["delivery_order"]
    check("a third one queues too",
          len([x for x in await inbox() if x["target_id"] == do3["id"]]) == 1,
          "not queued")
    r = await c.delete(f"/operation/deliveries/{do3['id']}", headers=adm)
    check("the desk withdraws it", r.status_code == 204, str(r.status_code))
    check("...and the inbox is not left pointing at a document that is gone",
          not [x for x in await inbox() if x["target_id"] == do3["id"]],
          "orphan left in the queue")

    # ══ the document's own screen ════════════════════════════════════════════
    print("\n── the delivery order's own screen ──")
    r = await c.get(f"/operation/deliveries/{do_id}", headers=adm)
    check("it opens", r.status_code == 200, f"{r.status_code} {J(r)}"[:150])
    v = J(r)
    check("...headed by its number and shipment", v.get("number") == do_no
          and v.get("split_index") == 1, str(v)[:200])
    check("...naming the customer and the project",
          v.get("customer_name") == f"PT Kirim {tag}" and v.get("project_code"),
          f"{v.get('customer_name')} / {v.get('project_code')}")
    check("...the customer's PO, which prints as the reference",
          v.get("po_number") == po_no, str(v.get("po_number")))
    check("...the goods it carries", len(v.get("items") or []) == 1,
          str(v.get("items"))[:170])
    check("...where they are going", tag in (v.get("remarks") or ""),
          str(v.get("remarks")))
    check("...and who released it, with the date",
          v.get("approved_by_name") and v.get("approved_at"),
          str(v.get("approved_at")))
    check("a released sheet says why it is frozen, rather than just refusing",
          "printed" in (v.get("locked_because") or "").lower(),
          str(v.get("locked_because"))[:150])
    check("...so the screen offers no edit on it",
          v["may"]["edit"] is False and v["may"]["delete"] is False,
          str(v.get("may")))

    v2 = J(await c.get(f"/operation/deliveries/{do2['id']}", headers=adm))
    check("an unreleased one is the admin desk's to edit",
          v2["may"]["edit"] and v2["may"]["delete"], str(v2.get("may")))
    check("...but not theirs to release",
          v2["may"]["approve"] is False, str(v2.get("may")))
    vd = J(await c.get(f"/operation/deliveries/{do2['id']}", headers=d))
    check("...and it is the director's to release", vd["may"]["approve"] is True,
          str(vd.get("may")))

    print("\n── who may open it ──")
    for label, hdr, ok in (("finance", fin, True), ("manager", mgr, True),
                           ("sales", s1, False), ("purchasing", pur, False)):
        r = await c.get(f"/operation/deliveries/{do_id}", headers=hdr)
        got = r.status_code == 200
        check(f"{label} {'can' if ok else 'cannot'} open a delivery order",
              got == ok, str(r.status_code))

    print("\n── editing the lines, which the table never allowed ──")
    r = await c.patch(f"/operation/deliveries/{do2['id']}", headers=adm, json={
        "items": [{"description": f"CHAIN {tag}", "qty": 1, "uom": "EA"},
                  {"description": f"SPROCKET {tag}", "qty": 3, "uom": "SET"}]})
    check("a line can be corrected and another added", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:150])
    v2 = J(await c.get(f"/operation/deliveries/{do2['id']}", headers=adm))
    check("...and the document says so",
          len(v2["items"]) == 2
          and {i["description"] for i in v2["items"]}
              == {f"CHAIN {tag}", f"SPROCKET {tag}"},
          str(v2["items"])[:220])
    r = await c.get(f"/operation/deliveries/{do2['id']}/pdf", headers=d,
                    params={"draft": 1})
    check("...and so does the draft sheet the director will see",
          r.status_code == 200 and "SPROCKET" in pdf_text(r.content).upper(),
          str(r.status_code))

    print("\n── the discussion that goes with it ──")
    r = await c.post("/comments", headers=adm, json={
        "owner_type": "delivery_order", "owner_id": do2["id"],
        "body": f"Site contact changed — {tag}"})
    check("the desk can leave a note on the document", r.status_code in (200, 201),
          f"{r.status_code} {J(r)}"[:150])
    r = await c.get("/comments", headers=d, params={
        "owner_type": "delivery_order", "owner_id": do2["id"]})
    check("...and the director reads it beside the decision",
          r.status_code == 200 and any(tag in (x.get("body") or "") for x in J(r)),
          f"{r.status_code} {str(J(r))[:150]}")
    r = await c.get("/comments", headers=s1, params={
        "owner_type": "delivery_order", "owner_id": do2["id"]})
    check("...while sales, who never sees the deliveries table, cannot",
          r.status_code in (401, 403), str(r.status_code))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)


asyncio.run(main())

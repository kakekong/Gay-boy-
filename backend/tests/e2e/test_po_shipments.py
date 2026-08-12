"""Step 2: what the split and the combining look like once it is an order.

Step 1 made a supplier price request able to cover half a job or three jobs.
This is the other end of that — the purchase orders and the project page.

**A job filled by three vendors arrives in three deliveries.** The project's
own `est_arrive_*` fields cannot hold three answers, so each supplier PO is a
*shipment* with its own ETA, numbered in the order they are expected, carrying
its own share of the items and the name of the vendor bringing them. The date
that answers "when is this job actually here" is the last of them to land, and
it is offered rather than written onto the project — the promised date stays
the director's.

**One order can cover several jobs.** One vendor, one truck, three customers'
work. So a PO line carries its own `project_id`, the PO rolls those up into
`project_ids`, and the order shows on every project it feeds — marked as
shared, because half of what is on that truck is somebody else's.

The prefill is what makes that bearable: built from the supplier's *answered
quote*, every line already knows its job, because Step 1's line provenance
carried it the whole way.
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

SPR = "/purchasing/price-requests"


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
    pur = await login("purchasing@demo.local")
    s1 = await login("sales1@demo.local")

    sup_a = J(await c.post("/purchasing/suppliers", headers=pur, json={
        "name": f"PT Rantai {tag}"}))["id"]
    sup_b = J(await c.post("/purchasing/suppliers", headers=pur, json={
        "name": f"PT Sproket {tag}"}))["id"]

    async def won_project(name: str, lines: list[tuple[str, float]]) -> dict:
        """A customer's job all the way to a live project."""
        cust = J(await c.post("/customers", headers=s1, json={
            "company_name": f"PT {name} {tag}", "industry": "mining"}))["id"]
        pr = J(await c.post("/price-requests", headers=s1, json={
            "customer_id": cust,
            "items": [{"description": desc, "qty": qty, "uom": "pcs"}
                      for desc, qty in lines]}))
        await c.post(f"/price-requests/{pr['id']}/submit", headers=s1)
        await c.post(f"/price-requests/{pr['id']}/price", headers=pur, json={
            "items": [{"line_no": i + 1, "cost_price": 1_000_000, "basis": "unit"}
                      for i in range(len(lines))]})
        await c.post(f"/price-requests/{pr['id']}/approve", headers=d, json={
            "items": [{"line_no": i + 1, "sell_price": 2_000_000, "basis": "unit"}
                      for i in range(len(lines))]})
        q = J(await c.post(f"/quotations/from-price-request/{pr['id']}", headers=s1))
        await c.post(f"/quotations/{q['id']}/submit", headers=s1)
        await c.post(f"/quotations/{q['id']}/approve", headers=d, json={"notes": ""})
        po = J(await c.post("/customer-pos", headers=s1, json={
            "customer_id": cust, "quotation_id": q["id"],
            "number": f"PO-{name}-{tag}",
            "items": [{"description": desc, "qty": qty, "unit_price": 2_000_000}
                      for desc, qty in lines], "is_downpayment": False}))
        await c.post(f"/quotations/{q['id']}/won", headers=d)
        proj = J(await c.post(f"/customer-pos/{po['id']}/approve", headers=d,
                              json={"notes": ""})).get("project_id")
        return {"pr": pr, "project_id": proj}

    # ══ one job, three vendors, three shipments ══════════════════════════════
    print("\n── a job split across two vendors arrives twice ──")
    job = await won_project("Tambang", [(f"CHAIN {tag}", 40), (f"SPROCKET {tag}", 4)])
    check("the job became a project", bool(job["project_id"]), str(job)[:150])
    proj = job["project_id"]

    po_a = J(await c.post("/purchasing/po", headers=d, json={
        "supplier_id": sup_a, "project_id": proj, "po_date": "2026-08-11",
        "eta": "2026-10-01", "quoted_lead_days": 45,
        "items": [{"description": f"CHAIN {tag}", "qty": 40, "uom": "meter",
                   "unit_price": 1_800_000, "amount": 72_000_000}],
        "total": 72_000_000}))
    po_b = J(await c.post("/purchasing/po", headers=d, json={
        "supplier_id": sup_b, "project_id": proj, "po_date": "2026-08-11",
        "eta": "2026-09-15", "quoted_lead_days": 30,
        "items": [{"description": f"SPROCKET {tag}", "qty": 4, "uom": "pcs",
                   "unit_price": 1_000_000, "amount": 4_000_000}],
        "total": 4_000_000}))
    check("both orders are raised", bool(po_a.get("id")) and bool(po_b.get("id")),
          f"{str(po_a)[:80]} / {str(po_b)[:80]}")

    ship = J(await c.get(f"/purchasing/po/for-project/{proj}", headers=pur))
    check("the project shows two shipments", len(ship["shipments"]) == 2,
          str(len(ship.get("shipments", []))))
    check("...numbered in the order they are expected",
          [s["shipment_no"] for s in ship["shipments"]] == [1, 2],
          str([(s["shipment_no"], s["eta"]) for s in ship["shipments"]]))
    check("...soonest first, whatever order they were raised in",
          ship["shipments"][0]["eta"] == "2026-09-15",
          str([s["eta"] for s in ship["shipments"]]))
    check("...each naming the vendor bringing it",
          {s["supplier_name"] for s in ship["shipments"]}
          == {f"PT Rantai {tag}", f"PT Sproket {tag}"},
          str([s["supplier_name"] for s in ship["shipments"]]))
    check("...and which items are on which truck",
          f"SPROCKET {tag}" in str(ship["shipments"][0]["items"])
          and f"CHAIN {tag}" in str(ship["shipments"][1]["items"]),
          str(ship["shipments"])[:250])
    check("every item is labelled with its supplier",
          all(i["supplier_name"] for s in ship["shipments"] for i in s["items"]),
          str(ship["shipments"])[:250])
    check("the job is complete when the LAST one lands",
          ship["last_eta"] == "2026-10-01", str(ship.get("last_eta")))
    check("...and it says how many vendors are involved",
          ship["supplier_count"] == 2, str(ship.get("supplier_count")))
    check("nothing has arrived yet", ship["all_received"] is False)

    # ══ one vendor, several jobs, one truck ══════════════════════════════════
    print("\n── one order covering three customers' work ──")
    a = await won_project("Semen", [(f"BOLT {tag}", 100)])
    b = await won_project("Kertas", [(f"NUT {tag}", 100)])

    joint = J(await c.post(SPR, headers=pur, json={
        "supplier_ids": [sup_a],
        "price_request_ids": [a["pr"]["id"], b["pr"]["id"]]}))[0]
    await c.post(f"{SPR}/{joint['id']}/quote", headers=pur, json={
        "items": [{"line_no": 1, "quoted_price": 5_000},
                  {"line_no": 2, "quoted_price": 3_000}],
        "quoted_lead_days": 21})

    pre = J(await c.get(f"/purchasing/po/from-quote/{joint['id']}", headers=pur))
    check("a PO can be prefilled straight off the vendor's answer",
          len(pre["items"]) == 2, str(pre)[:200])
    check("...at the price they actually quoted",
          [i["unit_price"] for i in pre["items"]] == [5_000, 3_000],
          str([i["unit_price"] for i in pre["items"]]))
    check("...with every line already pointing at its own job",
          len({i["project_id"] for i in pre["items"]}) == 2,
          str([(i["line_no"], i["project_code"]) for i in pre["items"]]))
    check("...and nothing left for a human to sort out",
          pre["unassigned_lines"] == [], str(pre["unassigned_lines"]))
    check("...naming both projects", len(pre["projects"]) == 2,
          str(pre["projects"]))

    combined = J(await c.post("/purchasing/po", headers=d, json={
        "supplier_id": sup_a, "project_id": a["project_id"],
        "po_date": "2026-08-11", "eta": "2026-09-20",
        "supplier_price_request_id": joint["id"],
        "items": [{"description": i["description"], "qty": i["qty"],
                   "uom": i["uom"], "unit_price": i["unit_price"],
                   "amount": i["amount"], "project_id": i["project_id"]}
                  for i in pre["items"]],
        "total": pre["total"]}))
    check("the combined order is raised", bool(combined.get("id")),
          str(combined)[:180])

    for job_key, other in ((a, b), (b, a)):
        got = J(await c.get(f"/purchasing/po/for-project/{job_key['project_id']}",
                            headers=pur))
        mine = [s for s in got["shipments"] if s["number"] == combined["number"]]
        check(f"it shows on {job_key['pr']['number']}'s page", len(mine) == 1,
              str([s["number"] for s in got["shipments"]]))
        if mine:
            check("...marked as shared with another job",
                  mine[0]["is_shared"] is True, str(mine[0]["is_shared"]))
            check("...carrying only that job's line",
                  len(mine[0]["items"]) == 1, str(mine[0]["items"]))

    got_a = J(await c.get(f"/purchasing/po/for-project/{a['project_id']}", headers=pur))
    mine = next(s for s in got_a["shipments"] if s["number"] == combined["number"])
    check("...and only that job's share of the money",
          float(mine["total_for_project"]) == 5_000 * 100,
          str(mine["total_for_project"]))

    # ══ the refusals and the edges ═══════════════════════════════════════════
    print("\n── the edges ──")
    r = await c.post("/purchasing/po", headers=d, json={
        "supplier_id": sup_a, "project_id": proj,
        "items": [{"description": "x", "qty": 1, "unit_price": 1,
                   "project_id": str(uuid.uuid4())}], "total": 1})
    check("a line naming a project that does not exist is refused",
          r.status_code == 400, f"{r.status_code} {J(r)}"[:150])
    r = await c.post("/purchasing/po", headers=d, json={
        "supplier_id": sup_a, "project_id": proj, "eta": "not-a-date",
        "items": [{"description": "x", "qty": 1, "unit_price": 1}], "total": 1})
    check("...and so is an ETA that is not a date", r.status_code == 400,
          str(r.status_code))

    plain = J(await c.post("/purchasing/po", headers=d, json={
        "supplier_id": sup_b, "project_id": proj,
        "items": [{"description": f"BEARING {tag}", "qty": 2, "unit_price": 500}],
        "total": 1000}))
    got = J(await c.get(f"/purchasing/po/for-project/{proj}", headers=pur))
    one = next(s for s in got["shipments"] if s["number"] == plain["number"])
    check("an ordinary single-job order is not marked as shared",
          one["is_shared"] is False, str(one["is_shared"]))
    check("...and sorts last when it has no ETA at all",
          got["shipments"][-1]["number"] == plain["number"],
          str([(s["number"], s["eta"]) for s in got["shipments"]]))

    # ══ what the new-PO form is told about the price request ═════════════════
    # The form prints the request's number and offers to open it, and it says
    # the buying prices came from purchasing's costing. Both have to be true:
    # the id has to come back so the number can be a link, and a request whose
    # lines were never costed must not be announced as costed — it prefills a
    # column of Rp 0, and a purchase order for nothing is easy to raise by
    # accident when the panel says the figures came from somewhere.
    print("\n── the prefill panel ──")
    pf = J(await c.get("/purchasing/po/prefill", headers=pur,
                       params={"project_id": proj}))
    check("the prefill names the price request", pf.get("price_request_number"),
          str(pf)[:160])
    check("...and returns its id, so the number can be opened",
          pf.get("price_request_id") == job["pr"]["id"],
          f"{pf.get('price_request_id')} vs {job['pr']['id']}")
    check("...with every line costed on a request that went through costing",
          pf.get("uncosted") == 0 and all(i.get("costed") for i in pf["items"]),
          str(pf.get("uncosted")))

    bare_cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Belum {tag}", "industry": "mining"}))["id"]
    bare = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": bare_cust,
        "items": [{"description": f"BELT {tag}", "qty": 5, "uom": "meter"},
                  {"description": f"PIN {tag}", "qty": 2, "uom": "pcs"}]}))
    await c.post(f"/price-requests/{bare['id']}/submit", headers=s1)
    pf2 = J(await c.get("/purchasing/po/prefill", headers=pur,
                        params={"price_request_id": bare["id"]}))
    check("an uncosted request says so rather than claiming Rp 0 is a price",
          pf2.get("uncosted") == 2, str(pf2.get("uncosted")))
    check("...naming which lines have nothing on them",
          not any(i.get("costed") for i in pf2["items"]), str(pf2["items"])[:200])
    check("...and its total is genuinely nothing", float(pf2.get("total") or 0) == 0,
          str(pf2.get("total")))

    await c.post(f"/price-requests/{bare['id']}/price", headers=pur, json={
        "items": [{"line_no": 1, "cost_price": 300_000, "basis": "unit"}]})
    pf3 = J(await c.get("/purchasing/po/prefill", headers=pur,
                        params={"price_request_id": bare["id"]}))
    check("costing one of the two lines leaves the other counted",
          pf3.get("uncosted") == 1, str(pf3.get("uncosted")))

    detail = J(await c.get(f"/purchasing/po/{po_a['id']}", headers=pur))
    check("a PO carries its price request's id, not just its number",
          "price_request_id" in detail, str(list(detail))[:200])

    # ══ keeping the date current ═════════════════════════════════════════════
    # The whole card is worthless if the one field it reads can only be set at
    # creation. A vendor phoning to say the truck slipped a week is news, not a
    # decision, so purchasing writes it straight through — while every other
    # field on the PO still waits for the director.
    print("\n── moving an ETA ──")
    r = await c.patch(f"/purchasing/po/{plain['id']}", headers=pur,
                      json={"eta": "2026-12-24"})
    check("purchasing can set the ETA", r.status_code == 200, f"{r.status_code} {J(r)}"[:150])
    check("...without it queueing for the director",
          J(r).get("pending_approval") is not True, str(J(r).get("pending_approval")))
    got = J(await c.get(f"/purchasing/po/for-project/{proj}", headers=pur))
    moved = next(s for s in got["shipments"] if s["number"] == plain["number"])
    check("...and the project's shipment moves with it",
          moved["eta"] == "2026-12-24", str(moved["eta"]))
    check("...taking the last-lands date with it",
          got["last_eta"] == "2026-12-24", str(got["last_eta"]))

    r = await c.patch(f"/purchasing/po/{plain['id']}", headers=pur,
                      json={"eta": "24/12/2026"})
    check("a date typed the Indonesian way is refused, not stored",
          r.status_code == 400, f"{r.status_code} {J(r)}"[:120])

    # The money on the same request still goes to the director: letting the
    # ETA through must not have opened a side door for the total.
    r = await c.patch(f"/purchasing/po/{plain['id']}", headers=pur,
                      json={"eta": "2026-12-25", "total": 999_999})
    check("changing the ETA and the total together still needs approval",
          J(r).get("pending_approval") is True, f"{r.status_code} {J(r)}"[:150])
    detail = J(await c.get(f"/purchasing/po/{plain['id']}", headers=pur))
    check("...the ETA applied anyway", detail["eta"] == "2026-12-25", str(detail["eta"]))
    check("...and the total did not", float(detail["total"]) == 1000.0, str(detail["total"]))

    r = await c.patch(f"/purchasing/po/{plain['id']}", headers=s1,
                      json={"eta": "2026-11-01"})
    check("sales cannot touch a supplier's arrival date either",
          r.status_code == 403, str(r.status_code))

    r = await c.patch(f"/purchasing/po/{plain['id']}", headers=pur, json={"eta": None})
    check("clearing it back to unknown is allowed", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:120])
    got = J(await c.get(f"/purchasing/po/for-project/{proj}", headers=pur))
    cleared = next(s for s in got["shipments"] if s["number"] == plain["number"])
    check("...and it sorts last again with no date",
          cleared["eta"] is None and got["shipments"][-1]["number"] == plain["number"],
          str([(s["number"], s["eta"]) for s in got["shipments"]]))

    r = await c.get(f"/purchasing/po/for-project/{uuid.uuid4()}", headers=pur)
    check("a project that does not exist is a 404", r.status_code == 404,
          str(r.status_code))
    r = await c.get(f"/purchasing/po/from-quote/{uuid.uuid4()}", headers=pur)
    check("...and so is a quote that does not", r.status_code == 404,
          str(r.status_code))
    r = await c.get(f"/purchasing/po/from-quote/{joint['id']}", headers=s1)
    check("sales cannot read a vendor's quoted prices", r.status_code == 403,
          str(r.status_code))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        sys.exit(1)


asyncio.run(main())

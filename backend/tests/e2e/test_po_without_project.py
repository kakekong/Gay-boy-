"""A purchasing PO can be raised without a project and given one later.

Stock gets ordered ahead of a job, a vendor's minimum order covers more than
one, a PO goes out while the customer's paper is still being signed — the
order is real before anyone knows which job it belongs to. A PO used to
refuse to exist without one.

Allowing "no project" is the easy half. The half that goes wrong quietly is
the LATER assignment: everything creating a PO against a job used to do has to
happen at that moment instead, or the PO ends up linked in name only. Its
lines have to carry the job (the project page and per-job costs read the
lines, not the header), `project_ids` has to include it, the PO picks up the
job's price request so cost can be traced, and the job moves to the
purchasing stage exactly as a PO raised against it would have moved it.

Which vendor serves which job is the director's decision, so from anyone else
the assignment queues for approval like every other PO edit — and finance,
who may touch the rate and the prices, may not touch this.
"""
import asyncio, os, sys, uuid
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
        return str(b)[:200].lower()
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
    pur = await login("purchasing@demo.local")
    fin = await login("finance@demo.local")
    s1 = await login("sales1@demo.local")

    async def a_project(tag):
        """A won job with a project, the ordinary way."""
        cust = J(await c.post("/customers", headers=s1, json={
            "company_name": f"PT Tanpa Proyek {tag}", "industry": "mining"}))["id"]
        pr = J(await c.post("/price-requests", headers=s1, json={
            "customer_id": cust,
            "items": [{"description": f"CHAIN {tag}", "qty": 5, "uom": "pcs"}]}))["id"]
        await c.post(f"/price-requests/{pr}/submit", headers=s1)
        await c.post(f"/price-requests/{pr}/approve", headers=d, json={
            "items": [{"line_no": 1, "sell_price": 1_000_000, "basis": "unit"}]})
        q = J(await c.post(f"/quotations/from-price-request/{pr}", headers=s1))["id"]
        await c.post(f"/quotations/{q}/submit", headers=s1)
        await c.post(f"/quotations/{q}/approve", headers=d, json={"notes": ""})
        cpo = J(await c.post("/customer-pos", headers=s1, json={
            "customer_id": cust, "quotation_id": q, "number": f"PO-TP-{tag}",
            "items": [{"description": f"CHAIN {tag}", "qty": 5,
                       "unit_price": 1_000_000}],
            "is_downpayment": False}))["id"]
        await c.post(f"/quotations/{q}/won", headers=d)
        proj = J(await c.post(f"/customer-pos/{cpo}/approve", headers=d,
                              json={"notes": ""}))["project_id"]
        return proj, pr

    async def po(po_id):
        return J(await c.get(f"/purchasing/po/{po_id}", headers=d))

    async def project(pid):
        return J(await c.get(f"/operation/projects/{pid}", headers=d))

    async def pending_edit(po_no):
        rows = J(await c.get("/approvals", headers=d))
        return next((x for x in rows if x["target_type"] == "supplier_po"
                     and (x.get("payload") or {}).get("action") == "update"
                     and (x.get("target_label") or "") == po_no), None)

    sup = J(await c.post("/purchasing/suppliers", headers=d, json={
        "name": f"PT Stok {TAG}", "category": "chain"}))["id"]

    # ══ raising one without a project ════════════════════════════════════
    print("\n── a PO with no project ──")
    r = await c.post("/purchasing/po", headers=pur, json={
        "supplier_id": sup, "number": f"PO-NOPJ-{TAG}", "currency": "IDR",
        "total": 500_000,
        "items": [{"description": f"STOCK CHAIN {TAG}", "qty": 10,
                   "unit_price": 50_000}]})
    check("purchasing can raise a PO without naming a project",
          r.status_code == 201, f"{r.status_code} {why(r)}")
    made = J(r)
    po_id, po_no = made.get("id"), made.get("number")
    check("...its project is empty — null, not the text 'None'",
          made.get("project_id") is None, repr(made.get("project_id")))
    check("...and its lines carry no job either, until one is given",
          all(i.get("project_id") is None for i in (made.get("items") or [])),
          str(made.get("items"))[:160])

    rows = J(await c.get("/approvals", headers=d))
    create_req = next((x for x in rows if x["target_type"] == "supplier_po"
                       and (x.get("target_label") or "") == po_no), None)
    check("the director is asked to approve it, and told it has no project yet",
          create_req is not None and "no project yet" in (create_req.get("reason") or ""),
          str(create_req and create_req.get("reason")))
    r = await c.post(f"/approvals/{create_req['id']}/approve", headers=d)
    check("...and can approve it", r.status_code == 200, f"{r.status_code} {why(r)}")
    check("...leaving an open PO with no project", (await po(po_id)).get("status") == "open"
          and (await po(po_id)).get("project_id") is None,
          str({k: (await po(po_id)).get(k) for k in ("status", "project_id")}))

    lst = J(await c.get("/purchasing/po", headers=d))
    lst = lst if isinstance(lst, list) else lst.get("items", [])
    check("it shows in the PO list — nothing filters out an order without a job",
          any(x.get("id") == po_id for x in lst), str(len(lst)))

    r = await c.post("/purchasing/po", headers=d, json={
        "supplier_id": sup, "number": f"PO-NOPJ-D-{TAG}", "total": 100_000,
        "items": [{"description": f"DIRECT {TAG}", "qty": 1, "unit_price": 100_000}]})
    check("the director can raise one without a project too, and it opens at once",
          r.status_code == 201 and J(r).get("status") == "open",
          f"{r.status_code} {J(r).get('status')} {why(r)}")
    direct_id = J(r).get("id")

    # ══ assigning later, through the director's queue ════════════════════
    print("\n── purchasing gives it a project later ──")
    proj_id, pr_id = await a_project(TAG)
    before_stage = (await project(proj_id)).get("status")
    r = await c.patch(f"/purchasing/po/{po_id}", headers=pur, json={"project_id": proj_id})
    check("purchasing can ask for a project to be assigned",
          r.status_code == 200 and J(r).get("pending_approval") is True,
          f"{r.status_code} {J(r).get('pending_approval')} {why(r)}")
    check("...which changes nothing until the director agrees",
          (await po(po_id)).get("project_id") is None, str((await po(po_id)).get("project_id")))
    req = await pending_edit(po_no)
    proj_code = (await project(proj_id)).get("code")
    check("the request says which job, by its code",
          req is not None and proj_code in (req.get("reason") or ""),
          str(req and req.get("reason")))
    pv = J(await c.get(f"/approvals/{req['id']}/preview", headers=d)) if req else {}
    fld = next((f for f in (pv.get("fields") or []) if f.get("label") == "Project"), {})
    check("...and the preview shows it as a before and after, in codes not ids",
          "none" in str(fld.get("value")) and proj_code in str(fld.get("value")),
          str(fld))

    r = await c.post(f"/approvals/{req['id']}/approve", headers=d)
    check("the director approves the assignment", r.status_code == 200,
          f"{r.status_code} {why(r)}")
    after = await po(po_id)
    check("the PO now belongs to the job", after.get("project_id") == proj_id,
          str(after.get("project_id")))
    check("...its lines carry the job — the project page reads the lines, not "
          "the header, so a header-only link would be a link in name only",
          all(i.get("project_id") == proj_id and i.get("project_code") == proj_code
              for i in (after.get("items") or [])),
          str(after.get("items"))[:200])
    check("...it is in the list of jobs the PO feeds",
          proj_id in (after.get("project_ids") or []), str(after.get("project_ids")))
    check("...it picked up the job's price request, so its cost can be traced",
          (after.get("price_request") or {}).get("id") == pr_id
          or after.get("price_request_id") == pr_id,
          str(after.get("price_request") or after.get("price_request_id")))

    STAGES = ["new", "po_received", "drawing", "drawing_approved", "purchasing"]
    stage_now = (await project(proj_id)).get("status")
    check("...and the job moved to purchasing, as a PO raised against it would "
          "have moved it — forward only",
          stage_now == "purchasing" or (before_stage not in STAGES and stage_now == before_stage),
          f"{before_stage} → {stage_now}")

    lst = J(await c.get("/purchasing/po", headers=d, params={"project_id": proj_id}))
    lst = lst if isinstance(lst, list) else lst.get("items", [])
    check("filtering POs by the job now finds it", any(x.get("id") == po_id for x in lst),
          str([x.get("number") for x in lst]))

    # ══ the director assigns directly ════════════════════════════════════
    print("\n── the director assigns one directly ──")
    r = await c.patch(f"/purchasing/po/{direct_id}", headers=d, json={"project_id": proj_id})
    check("the director's assignment applies at once",
          r.status_code == 200 and J(r).get("project_id") == proj_id,
          f"{r.status_code} {J(r).get('project_id')} {why(r)}")
    check("...stamping its lines too",
          all(i.get("project_id") == proj_id for i in ((await po(direct_id)).get("items") or [])),
          str((await po(direct_id)).get("items"))[:160])

    # ══ moving it to another job ═════════════════════════════════════════
    print("\n── moving it to a different job ──")
    proj2, _ = await a_project(f"B{TAG}")
    proj3, _ = await a_project(f"C{TAG}")
    code2 = (await project(proj2)).get("code")
    code3 = (await project(proj3)).get("code")
    # Give the direct PO a second line that belongs to a third job on purpose.
    cur = await po(direct_id)
    lines = [dict(i) for i in (cur.get("items") or [])]
    lines.append({"description": f"FOR ANOTHER JOB {TAG}", "qty": 1, "unit_price": 1,
                  "project_id": proj3, "project_code": code3})
    await c.patch(f"/purchasing/po/{direct_id}", headers=d, json={"items": lines})
    r = await c.patch(f"/purchasing/po/{direct_id}", headers=d, json={"project_id": proj2})
    moved = await po(direct_id)
    check("the director can move it to another job", moved.get("project_id") == proj2,
          str(moved.get("project_id")))
    own = [i for i in (moved.get("items") or []) if i.get("description") != f"FOR ANOTHER JOB {TAG}"]
    other = next((i for i in (moved.get("items") or [])
                  if i.get("description") == f"FOR ANOTHER JOB {TAG}"), {})
    check("...the lines that followed the old job follow it to the new one",
          all(i.get("project_id") == proj2 and i.get("project_code") == code2 for i in own),
          str(own)[:160])
    check("...but a line placed on a third job on purpose stays where it was put",
          other.get("project_id") == proj3, str(other))
    check("...and the PO feeds both jobs now, not the one it left",
          set(moved.get("project_ids") or []) == {proj2, proj3},
          str(moved.get("project_ids")))

    # ══ clearing it ══════════════════════════════════════════════════════
    print("\n── taking the project off again ──")
    r = await c.patch(f"/purchasing/po/{direct_id}", headers=d, json={"project_id": None})
    cleared = await po(direct_id)
    check("the director can clear the project", cleared.get("project_id") is None,
          str(cleared.get("project_id")))
    check("...its own lines lose the job with it",
          all(i.get("project_id") is None for i in (cleared.get("items") or [])
              if i.get("description") != f"FOR ANOTHER JOB {TAG}"),
          str(cleared.get("items"))[:160])

    # ══ what is refused ══════════════════════════════════════════════════
    print("\n── what is refused ──")
    r = await c.patch(f"/purchasing/po/{po_id}", headers=d,
                      json={"project_id": str(uuid.uuid4())})
    check("a project that does not exist is refused", r.status_code == 400,
          f"{r.status_code} {why(r)}")
    r = await c.patch(f"/purchasing/po/{po_id}", headers=fin, json={"project_id": proj2})
    check("finance may not assign one — the rate and the prices are theirs, "
          "which vendor serves which job is not",
          r.status_code == 403, f"{r.status_code} {why(r)}")
    r = await c.patch(f"/purchasing/po/{po_id}", headers=pur, json={"project_id": proj_id})
    check("asking for the project it already has queues nothing",
          await pending_edit(po_no) is None, str(await pending_edit(po_no)))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    for f in FAIL:
        print("  ✗", f)


asyncio.run(main())

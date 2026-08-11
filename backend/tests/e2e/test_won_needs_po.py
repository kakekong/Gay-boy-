"""Won is marked on the customer's order, and delivery dates aren't sales'.

Two rules asked for together, both about a claim being backed by the person
entitled to make it.

**Mark won needs the customer's PO on file first.** It used to be the other
way round — a PO could only be filed against an already-won quotation — which
meant Won was ticked on the rep's own say-so and the paperwork caught up
afterwards, or never. Won is not a mood: it starts a project, posts revenue
and moves the sales figures, so it now waits for the document the customer
themselves sent. The order is: approved → their PO is filed → won → the
director approves the PO → project.

The rule binds the director too. It is not a permission — it is what the word
means — and an exemption for the one person whose sign-off the rule exists to
inform would empty it out.

**Sales cannot set a delivery date.** They could, and their edit was filed as
a director approval: the screenshot that prompted this showed two of them
queued for one project. Every date on the shipping strip is a promise about
physical goods somebody else is moving — purchasing books the origin leg,
admin owns both arrival legs, the director owns what the customer is told. A
rep who could type there was really raising an approval request about a
shipment they cannot see. It is now refused outright, which is also what the
screen shows them.
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
    s1 = await login("sales1@demo.local")
    pur = await login("purchasing@demo.local")
    adm = await login("admin@demo.local")

    async def approved_quote(name: str) -> dict:
        cust = J(await c.post("/customers", headers=s1, json={
            "company_name": f"PT Bukti {tag}-{uuid.uuid4().hex[:4]}",
            "industry": "mining"}))["id"]
        q = J(await c.post("/quotations", headers=d, json={
            "customer_id": cust, "variant": "detailed",
            "items": [{"line_no": 1, "description": name, "qty": 2,
                       "uom": "pcs", "unit_price": 5_000_000}]}))
        await c.post(f"/quotations/{q['id']}/submit", headers=d)
        await c.post(f"/quotations/{q['id']}/approve", headers=d, json={"notes": ""})
        q["customer_id"] = cust
        return q

    # ══ no PO, no win ════════════════════════════════════════════════════════
    print("\n── a quotation nobody has ordered yet ──")
    q = await approved_quote(f"Gearbox {tag}")
    check("it is approved and ready to send",
          J(await c.get(f"/quotations/{q['id']}", headers=d))["status"] == "approved")

    r = await c.post(f"/quotations/{q['id']}/won", headers=s1)
    check("the rep cannot mark it won", r.status_code == 409,
          f"{r.status_code} {J(r)}"[:170])
    check("...and is told what is missing", "customer's PO" in str(J(r)),
          str(J(r))[:170])
    r = await c.post(f"/quotations/{q['id']}/won", headers=d)
    check("neither can the director — this is not a permission",
          r.status_code == 409, f"{r.status_code} {J(r)}"[:170])
    check("...and it really is still open",
          J(await c.get(f"/quotations/{q['id']}", headers=d))["status"] == "approved")

    # ══ with the PO, it goes through ═════════════════════════════════════════
    print("\n── once their PO is on file ──")
    r = await c.post("/customer-pos", headers=s1, json={
        "customer_id": q["customer_id"], "quotation_id": q["id"],
        "number": f"PO-WIN-{tag}", "po_date": "2026-08-10",
        "items": [{"description": f"Gearbox {tag}", "qty": 2,
                   "unit_price": 5_000_000}], "is_downpayment": False})
    check("a PO can be filed against an approved quotation, before the win",
          r.status_code == 201, f"{r.status_code} {J(r)}"[:170])
    po = J(r)
    r = await c.post(f"/quotations/{q['id']}/won", headers=s1)
    check("the rep's mark-won now files with the director",
          r.status_code in (200, 202), f"{r.status_code} {J(r)}"[:170])
    r = await c.post(f"/quotations/{q['id']}/won", headers=d)
    check("...and the director's lands it", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:170])
    check("...it is won", J(await c.get(f"/quotations/{q['id']}", headers=d))["status"]
          == "won")
    # tidy the PO out of the queue so the shared DB stays clean
    await c.post(f"/customer-pos/{po['id']}/approve", headers=d, json={"notes": ""})

    # ══ a PO that was thrown out is not evidence ═════════════════════════════
    print("\n── a rejected PO does not count ──")
    q2 = await approved_quote(f"Chain {tag}")
    po2 = J(await c.post("/customer-pos", headers=s1, json={
        "customer_id": q2["customer_id"], "quotation_id": q2["id"],
        "number": f"PO-REJ-{tag}",
        "items": [{"description": f"Chain {tag}", "qty": 2,
                   "unit_price": 5_000_000}], "is_downpayment": False}))
    r = await c.post(f"/customer-pos/{po2['id']}/reject", headers=d,
                     json={"notes": "wrong customer entirely"})
    check("the director throws the PO out", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:150])
    r = await c.post(f"/quotations/{q2['id']}/won", headers=d)
    check("...and the quotation cannot be won on it", r.status_code == 409,
          f"{r.status_code} {J(r)}"[:170])

    # ...and a request signed off after its PO disappears is not applied either
    print("\n── the PO vanishing between the request and the decision ──")
    q3 = await approved_quote(f"Sprocket {tag}")
    po3 = J(await c.post("/customer-pos", headers=s1, json={
        "customer_id": q3["customer_id"], "quotation_id": q3["id"],
        "number": f"PO-GONE-{tag}",
        "items": [{"description": f"Sprocket {tag}", "qty": 2,
                   "unit_price": 5_000_000}], "is_downpayment": False}))
    await c.post(f"/quotations/{q3['id']}/won", headers=s1)
    rows = J(await c.get("/approvals", headers=d))
    rows = rows if isinstance(rows, list) else (rows.get("data") or [])
    ask = next((a for a in rows if a.get("target_type") == "quotation_won"
                and str(a.get("target_id")) == q3["id"]), None)
    check("the rep's request is with the director", ask is not None, str(len(rows)))
    await c.post(f"/customer-pos/{po3['id']}/reject", headers=d,
                 json={"notes": "customer withdrew it"})
    if ask:
        r = await c.post(f"/approvals/{ask['id']}/approve", headers=d, json={"notes": ""})
        check("approving it is accepted rather than erroring",
              r.status_code in (200, 202), str(r.status_code))
        check("...but the quotation was NOT won, because the evidence went",
              J(await c.get(f"/quotations/{q3['id']}", headers=d))["status"] != "won",
              J(await c.get(f"/quotations/{q3['id']}", headers=d))["status"])

    # ══ and the shapes the PO endpoint still refuses ═════════════════════════
    print("\n── what a PO can be filed against ──")
    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Draf {tag}", "industry": "mining"}))["id"]
    draft = J(await c.post("/quotations", headers=d, json={
        "customer_id": cust, "variant": "short",
        "items": [{"line_no": 1, "description": f"Belt {tag}", "qty": 1,
                   "uom": "pcs", "unit_price": 1_000_000}]}))
    r = await c.post("/customer-pos", headers=s1, json={
        "customer_id": cust, "quotation_id": draft["id"], "number": f"PO-DRAFT-{tag}",
        "items": [{"description": f"Belt {tag}", "qty": 1, "unit_price": 1_000_000}],
        "is_downpayment": False})
    check("a draft quotation cannot take a customer PO", r.status_code == 400,
          f"{r.status_code} {J(r)}"[:170])
    check("...and says the customer has to have been given it first",
          "approved or sent" in str(J(r)), str(J(r))[:170])

    # ══ delivery dates ═══════════════════════════════════════════════════════
    print("\n── the shipping strip is not sales' to fill in ──")
    # A live project to try it on: the won quote above, through its PO.
    proj = J(await c.get(f"/customer-pos/{po['id']}", headers=d)).get("project_id")
    check("there is a project to test against", bool(proj), str(proj))

    before = J(await c.get(f"/operation/projects/{proj}", headers=d))
    for field in ("target_delivery", "actual_delivery", "est_arrive_customer",
                  "est_ship_from_origin"):
        r = await c.patch(f"/operation/projects/{proj}", headers=s1,
                          json={field: "2026-12-01"})
        check(f"sales cannot set {field}", r.status_code == 403,
              f"{r.status_code} {J(r)}"[:150])
    check("...and is told who owns them instead",
          "purchasing" in str(J(r)).lower() and "admin" in str(J(r)).lower(),
          str(J(r))[:200])
    r = await c.patch(f"/operation/projects/{proj}", headers=s1,
                      json={"is_import": True})
    check("...nor flip the import switch that drives the legs",
          r.status_code == 403, str(r.status_code))

    after = J(await c.get(f"/operation/projects/{proj}", headers=d))
    check("no date moved", all(after.get(k) == before.get(k) for k in
                               ("target_delivery", "actual_delivery",
                                "est_arrive_customer", "est_ship_from_origin")),
          str({k: (before.get(k), after.get(k)) for k in ("target_delivery",)}))

    # nothing was filed for the director to decide, either
    rows = J(await c.get("/approvals", headers=d))
    rows = rows if isinstance(rows, list) else (rows.get("data") or [])
    shipping = [a for a in rows if str(a.get("target_id")) == str(proj)
                and "hipping" in str(a.get("reason") or "")]
    check("...and nothing landed in the director's inbox to decide",
          not shipping, str(shipping)[:200])

    # the people whose job it is are unaffected
    print("\n── the people whose lanes these are ──")
    r = await c.patch(f"/operation/projects/{proj}", headers=pur,
                      json={"est_ship_from_origin": "2026-12-02"})
    check("purchasing still books the origin leg", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:150])
    r = await c.patch(f"/operation/projects/{proj}", headers=adm,
                      json={"est_arrive_customer": "2026-12-20"})
    check("admin still books the arrival", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:150])
    r = await c.patch(f"/operation/projects/{proj}", headers=d,
                      json={"target_delivery": "2026-12-22"})
    check("the director still sets what the customer is promised",
          r.status_code == 200, f"{r.status_code} {J(r)}"[:150])
    live = J(await c.get(f"/operation/projects/{proj}", headers=d))
    check("...and it applied without an approval round",
          str(live.get("target_delivery")) == "2026-12-22",
          str(live.get("target_delivery")))

    # sales can still read them — they answer the customer's phone call
    r = await c.get(f"/operation/projects/{proj}", headers=s1)
    check("sales can still SEE the dates, they just cannot set them",
          r.status_code == 200 and str(J(r).get("target_delivery")) == "2026-12-22",
          f"{r.status_code} {J(r).get('target_delivery')}")

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        sys.exit(1)


asyncio.run(main())

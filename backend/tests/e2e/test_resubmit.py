"""Sent back is not the end of the road.

Asked for: when a quotation or anything is rejected it should be possible to
resubmit it, and the reason it was rejected should be visible.

Rejection was a dead end on two of the three documents, in different ways.

A **quotation** could not be resubmitted at all — submit demanded a draft, so
a rejected one had to be *revised* into a whole new -R2 document. That is the
right tool for a quote the customer has already seen and the wrong one for a
quote the director simply handed back. Worse, the reason went only to the
audit log and to the approval request, so the quotation page never said why
it came back: the one screen the person who has to fix it is looking at.

A **customer PO** already demanded a reason and stored it, but a rejected one
was frozen — not editable, not resubmittable. "Send it back with a reason"
was an instruction nobody could act on without filing a second PO under a new
number and leaving two records of one order.

A **price request** already did both, which is what the other two now match.

The reason is deliberately *kept* through a resubmission rather than cleared:
the director is about to look at the thing again, and what they asked for
last time is the most useful line on the page.
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

    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Balik {tag}", "industry": "mining"}))["id"]

    async def a_quotation() -> dict:
        pr = J(await c.post("/price-requests", headers=s1, json={
            "customer_id": cust,
            "items": [{"description": f"CHAIN {tag}-{uuid.uuid4().hex[:4]}",
                       "qty": 10, "uom": "meter"}]}))["id"]
        await c.post(f"/price-requests/{pr}/submit", headers=s1)
        await c.post(f"/price-requests/{pr}/price", headers=pur, json={
            "items": [{"line_no": 1, "cost_price": 1_000_000, "basis": "unit"}]})
        await c.post(f"/price-requests/{pr}/approve", headers=d, json={
            "items": [{"line_no": 1, "sell_price": 1_400_000, "basis": "unit"}]})
        return J(await c.post(f"/quotations/from-price-request/{pr}", headers=s1))

    # ══ a quotation ══════════════════════════════════════════════════════════
    print("\n── a quotation the director sends back ──")
    q = await a_quotation()
    await c.post(f"/quotations/{q['id']}/submit", headers=s1)
    r = await c.post(f"/quotations/{q['id']}/reject", headers=d,
                     json={"notes": f"validity is too short, make it 30 days {tag}"})
    check("the director can reject it", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:150])
    got = J(await c.get(f"/quotations/{q['id']}", headers=s1))
    check("...it lands as rejected", got["status"] == "rejected", got["status"])
    check("...and the quotation itself says why",
          f"make it 30 days {tag}" in (got.get("decision_notes") or ""),
          str(got.get("decision_notes")))

    r = await c.patch(f"/quotations/{q['id']}", headers=s1,
                      json={"valid_until": "2026-12-31"})
    check("sales can fix what was asked", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:150])
    r = await c.post(f"/quotations/{q['id']}/submit", headers=s1)
    check("...and send it straight back up", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:150])
    back = J(await c.get(f"/quotations/{q['id']}", headers=d))
    check("...it is waiting on the director again",
          back["status"] == "pending_approval", back["status"])
    check("...under the same number, not a second document",
          back["number"] == q["number"], f"{back['number']} vs {q['number']}")
    check("...and the director can still read what they asked for",
          f"make it 30 days {tag}" in (back.get("decision_notes") or ""),
          str(back.get("decision_notes")))
    check("...with the fix applied", str(back.get("valid_until")) == "2026-12-31",
          str(back.get("valid_until")))

    appr = J(await c.get("/approvals", headers=d))
    rows = appr if isinstance(appr, list) else appr.get("data", [])
    check("the director has it in the queue again",
          any(a.get("target_type") == "quotation"
              and str(a.get("target_id")) == q["id"] for a in rows))
    r = await c.post(f"/quotations/{q['id']}/approve", headers=d, json={})
    check("...and can approve it this time", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:150])

    print("\n── and the states that still refuse ──")
    q2 = await a_quotation()
    await c.post(f"/quotations/{q2['id']}/submit", headers=s1)
    r = await c.post(f"/quotations/{q2['id']}/submit", headers=s1)
    check("a quotation already awaiting a decision cannot be submitted again",
          r.status_code == 409, str(r.status_code))
    await c.post(f"/quotations/{q2['id']}/approve", headers=d, json={})
    r = await c.post(f"/quotations/{q2['id']}/submit", headers=s1)
    check("...nor an approved one", r.status_code == 409, str(r.status_code))
    check("...and the refusal names the status it is in",
          "approved" in str(J(r)).lower(), str(J(r))[:140])
    check("revising is still there for a quote already sent out",
          (await c.post(f"/quotations/{q2['id']}/revise", headers=s1)).status_code
          in (200, 201))

    # ══ a customer PO ════════════════════════════════════════════════════════
    print("\n── a customer PO sent back ──")
    # A customer PO is filed against an approved quotation, so make one.
    qa = await a_quotation()
    await c.post(f"/quotations/{qa['id']}/submit", headers=s1)
    await c.post(f"/quotations/{qa['id']}/approve", headers=d, json={})
    await c.post(f"/quotations/{qa['id']}/won", headers=d)
    po = J(await c.post("/customer-pos", headers=s1, json={
        "customer_id": cust, "quotation_id": qa["id"], "number": f"PO-BALIK-{tag}",
        "po_date": "2026-08-01",
        "items": [{"description": "chain", "qty": 10, "unit_price": 140_000}]}))
    check("sales files it", po.get("status") == "pending_approval", str(po)[:150])
    r = await c.post(f"/customer-pos/{po['id']}/reject", headers=d,
                     json={"notes": f"PO number does not match the quotation {tag}"})
    check("the director sends it back", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:150])
    got = J(await c.get(f"/customer-pos/{po['id']}", headers=s1))
    check("...it is rejected", got["status"] == "rejected", got["status"])
    check("...and says why", f"does not match the quotation {tag}"
          in (got.get("decision_notes") or ""), str(got.get("decision_notes")))

    r = await c.patch(f"/customer-pos/{po['id']}", headers=s1,
                      json={"number": f"PO-BALIK-{tag}-B"})
    check("sales can correct it", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:150])
    r = await c.post(f"/customer-pos/{po['id']}/resubmit", headers=s1)
    check("...and resubmit it", r.status_code == 200, f"{r.status_code} {J(r)}"[:150])
    back = J(await c.get(f"/customer-pos/{po['id']}", headers=d))
    check("...it is pending the director again",
          back["status"] == "pending_approval", back["status"])
    check("...carrying the correction", back["number"] == f"PO-BALIK-{tag}-B",
          back["number"])
    check("...and still showing what was wrong last time",
          f"does not match the quotation {tag}" in (back.get("decision_notes") or ""),
          str(back.get("decision_notes")))
    rows = J(await c.get("/approvals", headers=d))
    rows = rows if isinstance(rows, list) else rows.get("data", [])
    check("the director has it to decide again",
          any(a.get("target_type") == "customer_po"
              and str(a.get("target_id")) == po["id"] for a in rows))

    r = await c.post(f"/customer-pos/{po['id']}/resubmit", headers=s1)
    check("resubmitting one that is not rejected is refused",
          r.status_code == 409, str(r.status_code))

    # Finish the loop: a resubmitted PO must be approvable like any other,
    # and leaving it pending would park a live approval request in the queue
    # for whatever runs next.
    r = await c.post(f"/customer-pos/{po['id']}/approve", headers=d, json={"notes": ""})
    done = J(r)
    check("...and the director can approve the resubmitted PO",
          r.status_code == 200 and done.get("status") == "approved",
          f"{r.status_code} {done}"[:150])
    check("...which spawns the project, as a first-time approval would",
          bool(done.get("project_id")), str(done.get("project_id")))

    # ══ a price request, which already worked ════════════════════════════════
    print("\n── a price request, unchanged ──")
    pr = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [{"description": f"BELT {tag}", "qty": 5, "uom": "meter"}]}))["id"]
    await c.post(f"/price-requests/{pr}/submit", headers=s1)
    await c.post(f"/price-requests/{pr}/reject", headers=d,
                 json={"notes": f"need the drawing first {tag}"})
    got = J(await c.get(f"/price-requests/{pr}", headers=s1))
    check("it is rejected with a reason on it",
          got["status"] == "rejected"
          and f"need the drawing first {tag}" in (got.get("decision_notes") or ""),
          str(got.get("decision_notes")))
    r = await c.patch(f"/price-requests/{pr}", headers=s1, json={
        "items": [{"description": f"BELT {tag} rev2", "qty": 5, "uom": "meter"}]})
    check("...editable again", r.status_code == 200, str(r.status_code))
    r = await c.post(f"/price-requests/{pr}/submit", headers=s1)
    check("...and resubmittable", r.status_code == 200, str(r.status_code))
    check("...back in purchasing's queue",
          J(await c.get(f"/price-requests/{pr}", headers=d))["status"]
          == "pending_purchasing")

    # ══ who may not ══════════════════════════════════════════════════════════
    print("\n── and only the people who should ──")
    s2 = await login("sales2@demo.local")
    qb = await a_quotation()
    await c.post(f"/quotations/{qb['id']}/submit", headers=s1)
    await c.post(f"/quotations/{qb['id']}/approve", headers=d, json={})
    await c.post(f"/quotations/{qb['id']}/won", headers=d)
    po2 = J(await c.post("/customer-pos", headers=s1, json={
        "customer_id": cust, "quotation_id": qb["id"], "number": f"PO-BALIK2-{tag}",
        "items": [{"description": "x", "qty": 1, "unit_price": 100}]}))
    await c.post(f"/customer-pos/{po2['id']}/reject", headers=d,
                 json={"notes": "no"})
    r = await c.post(f"/customer-pos/{po2['id']}/resubmit", headers=s2)
    check("another rep cannot resubmit somebody else's PO",
          r.status_code == 403, str(r.status_code))
    check("...and it is still rejected",
          J(await c.get(f"/customer-pos/{po2['id']}", headers=d))["status"] == "rejected")
    # Left rejected on purpose — a rejected PO holds no pending approval
    # request, so nothing is parked in anybody else's queue.

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        sys.exit(1)


asyncio.run(main())

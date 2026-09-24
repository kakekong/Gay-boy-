"""Editing the same document twice revises one request, it does not queue two.

Somebody settling a figure does not get it right first time: they edit, look
at it, edit again. Every one of those used to file a fresh approval, so the
director ended up holding a stack of near-identical rows against one document
with no way to tell which was current.

That is worse than clutter. The rows are not alternatives — they are drafts of
the same intent — and approving an older one applies a stale figure while the
newer one sits there still waiting. Approving them in the order they were
filed lands on the *first* thing somebody typed.

So there is one live proposal per document. A second edit rewrites the first
in place: same row, current values, and a count of how many times it has moved
so the director can see it is not new. What is pinned here is that the count
of pending rows stays at one however many times somebody edits, that the row
holds the LATEST values rather than the first, and that approving it applies
the latest — plus the thing that made them indistinguishable in the first
place, which is that the reason said "items, total" for every edit ever made.
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
    s1 = await login("sales1@demo.local")
    adm = await login("admin@demo.local")

    # ── a project and an open CNY purchase order ─────────────────────────
    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Ulang {TAG}", "industry": "mining"}))["id"]
    pr = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [{"description": f"WHEEL {TAG}", "qty": 3, "uom": "pcs"}]}))["id"]
    await c.post(f"/price-requests/{pr}/submit", headers=s1)
    await c.post(f"/price-requests/{pr}/price", headers=d, json={
        "items": [{"line_no": 1, "cost_price": 500, "basis": "unit"}]})
    await c.post(f"/price-requests/{pr}/approve", headers=d, json={
        "items": [{"line_no": 1, "sell_price": 1000, "basis": "unit"}]})
    q = J(await c.post(f"/quotations/from-price-request/{pr}", headers=s1))["id"]
    await c.post(f"/quotations/{q}/submit", headers=s1)
    await c.post(f"/quotations/{q}/approve", headers=d, json={"notes": ""})
    cpo = J(await c.post("/customer-pos", headers=s1, json={
        "customer_id": cust, "quotation_id": q, "number": f"PO-UL-{TAG}",
        "items": [{"description": f"WHEEL {TAG}", "qty": 3, "unit_price": 1000}],
        "is_downpayment": False}))["id"]
    await c.post(f"/quotations/{q}/won", headers=d)
    proj = J(await c.post(f"/customer-pos/{cpo}/approve", headers=d,
                          json={"notes": ""}))["project_id"]
    sup = J(await c.post("/purchasing/suppliers", headers=d, json={
        "name": f"GUI ZHOU {TAG}", "category": "transmission"}))["id"]
    po = J(await c.post("/purchasing/po", headers=d, json={
        "supplier_id": sup, "project_id": proj, "number": f"PO-UL-CNY-{TAG}",
        "currency": "CNY", "fx_rate": 2200.0, "total": 1800.0,
        "items": [{"description": f"Wheel Bed {TAG}", "qty": 3, "unit_price": 600.0}]}))
    po_id, po_no = po["id"], po["number"]

    async def pending_for_po():
        rows = J(await c.get("/approvals", headers=d))
        return [x for x in rows
                if x["target_type"] == "supplier_po"
                and (x.get("payload") or {}).get("action") == "update"
                and (x.get("target_label") or "") == po_no]

    # ══ edit it three times ══════════════════════════════════════════════
    print("\n── the same order, edited three times ──")
    async def edit(unit, total):
        return await c.patch(f"/purchasing/po/{po_id}", headers=pur, json={
            "items": [{"description": f"Wheel Bed {TAG}", "qty": 3,
                       "unit_price": unit}],
            "total": total})

    r = await edit(700.0, 2100.0)
    check("the first edit is accepted", r.status_code == 200, f"{r.status_code} {why(r)}")
    rows = await pending_for_po()
    check("...and queues exactly one request", len(rows) == 1, str(len(rows)))
    first_reason = rows[0].get("reason") if rows else ""

    r = await edit(800.0, 2400.0)
    check("a second edit is accepted", r.status_code == 200, f"{r.status_code} {why(r)}")
    r = await edit(900.0, 2700.0)
    check("a third edit is accepted", r.status_code == 200, f"{r.status_code} {why(r)}")

    rows = await pending_for_po()
    check("there is STILL only one request to decide, not three",
          len(rows) == 1, f"{len(rows)}: {[x.get('reason') for x in rows]}")
    if not rows:
        print(f"\n{len(PASS)} passed, {len(FAIL)} failed"); return
    row = rows[0]

    check("...and it says it has been revised, so the director can see it is "
          "not a fresh request",
          (row.get("revision") or 1) == 3, str(row.get("revision")))
    check("...while remembering when it was first raised",
          bool(row.get("first_requested_at")), str(row.get("first_requested_at")))

    # ══ the row holds the LATEST intent ══════════════════════════════════
    print("\n── which of the three it holds ──")
    changes = (row.get("payload") or {}).get("changes") or {}
    check("the queued total is the newest one, not the first",
          abs(float(changes.get("total") or 0) - 2700.0) < 0.01,
          str(changes.get("total")))
    line = (changes.get("items") or [{}])[0]
    check("...and so is the queued price",
          abs(float(line.get("unit_price") or 0) - 900.0) < 0.01,
          str(line.get("unit_price")))

    p = J(await c.get(f"/approvals/{row['id']}/preview", headers=d))
    check("the preview shows the newest figure too",
          abs(float(p.get("total") or 0) - 2700.0) < 0.01, str(p.get("total")))

    # ══ the reason tells them apart ══════════════════════════════════════
    print("\n── telling two edits apart without opening them ──")
    check("the reason names what moved, not which field names were touched",
          "items" != (row.get("reason") or "") and "→" in (row.get("reason") or ""),
          str(row.get("reason")))
    check("...naming the money", "CNY" in (row.get("reason") or ""),
          str(row.get("reason")))
    check("...and it changed as the edits changed, so two edits to one order "
          "never read the same",
          first_reason != row.get("reason"),
          f"{first_reason!r} vs {row.get('reason')!r}")

    # ══ approving applies the latest ═════════════════════════════════════
    print("\n── approving it ──")
    r = await c.post(f"/approvals/{row['id']}/approve", headers=d)
    check("the director approves the one row", r.status_code == 200,
          f"{r.status_code} {why(r)}")
    pos = J(await c.get("/purchasing/po", headers=d))
    po_rows = pos if isinstance(pos, list) else (pos.get("items") or [])
    after = next((x for x in po_rows if x.get("number") == po_no), {})
    check("...and the order takes the LAST thing that was typed, not the first",
          abs(float(after.get("total") or 0) - 2700.0) < 0.01,
          str(after.get("total")))
    check("...with the matching line price",
          abs(float(((after.get("items") or [{}])[0]).get("unit_price") or 0) - 900.0) < 0.01,
          str(after.get("items")))
    check("the queue is empty afterwards — there was never a second row left "
          "behind to apply a stale figure",
          len(await pending_for_po()) == 0, str(await pending_for_po()))

    # ══ the same for a project's shipping dates ══════════════════════════
    print("\n── and for a project's dates, which get settled the same way ──")
    async def ship(date_str):
        # Arrival dates are admin's to propose; a non-director's change
        # queues for the director either way, which is the part under test.
        return await c.patch(f"/operation/projects/{proj}", headers=adm,
                             json={"est_arrive_our_warehouse": date_str})

    async def pending_for_proj():
        rows = J(await c.get("/approvals", headers=d))
        return [x for x in rows
                if x["target_type"] == "project"
                and x["target_id"] == proj]

    r = await ship("2026-11-20")
    ok_first = r.status_code in (200, 202)
    check("a shipping date change is accepted", ok_first, f"{r.status_code} {why(r)}")
    if ok_first:
        await ship("2026-11-25")
        await ship("2026-12-01")
        rows = await pending_for_proj()
        check("three date changes leave one request, not three",
              len(rows) == 1, f"{len(rows)}: {[x.get('reason') for x in rows]}")
        if rows:
            ch = (rows[0].get("payload") or {}).get("changes") or {}
            check("...holding the date they settled on last",
                  str(ch.get("est_arrive_our_warehouse") or "").startswith("2026-12-01"),
                  str(ch.get("est_arrive_our_warehouse")))
            check("...and the reason says which date and what it becomes",
                  "→" in (rows[0].get("reason") or ""), str(rows[0].get("reason")))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    for f in FAIL:
        print("  ✗", f)


asyncio.run(main())

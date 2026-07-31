"""The director can correct a price request after it has left draft.

Sales and purchasing are still held to the old rule — a request stops being
editable once it is submitted — because by then it is a live commercial
document that purchasing has costed. The director is the exception, for the
ordinary case where a customer changes a spec mid-negotiation and somebody has
to be able to fix it.

The trap being pinned here is the quiet one: the line list is rebuilt on every
edit, and the cost and sell prices live *inside* those lines. A naive rebuild
blanks them, so purchasing's costing and the director's approved prices vanish
without an error, on a document that still says "approved". So most of what
follows checks that surviving lines keep their money.
"""
import asyncio, os, sys, uuid
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123", STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import httpx, logging; logging.disable(logging.INFO)
PASS, FAIL = [], []
def check(n,c,d=""):
    (PASS if c else FAIL).append(n); print(("  PASS " if c else "  FAIL ")+n+(f"  [{d}]" if d and not c else ""))
def J(r):
    try: return r.json()
    except: return {"_":r.text[:200]}
async def login(c,e):
    r=await c.post("/auth/login",json={"email":e,"password":"test-pass-123"})
    return {"Authorization":f"Bearer {r.json()['access_token']}"}

def line(pr, desc):
    return next((x for x in pr.get("items", []) if x["description"] == desc), None)


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=60)
    d = await login(c, "director@demo.local");  s1 = await login(c, "sales1@demo.local")
    pu = await login(c, "purchasing@demo.local")
    tag = uuid.uuid4().hex[:5]

    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Edit {tag}", "industry": "mining"}))["id"]

    async def fresh_pr():
        pr = J(await c.post("/price-requests", headers=s1, json={
            "customer_id": cust, "items": [
                {"description": f"Gearbox {tag}", "qty": 2, "uom": "pcs"},
                {"description": f"Coupling {tag}", "qty": 4, "uom": "pcs"},
            ]}))["id"]
        return pr

    # ── 1. the old rule still holds for everyone else ────────────────────────
    pr = await fresh_pr()
    r = await c.patch(f"/price-requests/{pr}", headers=s1, json={
        "items": [{"description": f"Gearbox {tag}", "qty": 3, "uom": "pcs"}]})
    check("sales can still edit their own draft", r.status_code == 200, J(r))
    check("...and the edit took", (line(J(r), f"Gearbox {tag}") or {}).get("qty") == 3,
          str(J(r).get("items"))[:120])

    await c.post(f"/price-requests/{pr}/submit", headers=s1)
    r = await c.patch(f"/price-requests/{pr}", headers=s1, json={
        "items": [{"description": "sneaky", "qty": 1}]})
    check("sales cannot edit it once submitted", r.status_code == 409, str(r.status_code))
    r = await c.patch(f"/price-requests/{pr}", headers=pu, json={
        "items": [{"description": "sneaky", "qty": 1}]})
    check("purchasing cannot edit it either", r.status_code == 409, str(r.status_code))

    # ── 2. the director can, at every stage ──────────────────────────────────
    r = await c.patch(f"/price-requests/{pr}", headers=d, json={
        "items": [
            {"description": f"Gearbox {tag}", "qty": 3, "uom": "pcs"},
            {"description": f"Coupling {tag}", "qty": 4, "uom": "pcs"},
            {"description": f"Seal kit {tag}", "qty": 1, "uom": "set"},
        ]})
    check("the director can edit a submitted request", r.status_code == 200, J(r))
    check("...and the new line is there", bool(line(J(r), f"Seal kit {tag}")),
          str([x["description"] for x in J(r).get("items", [])]))
    r = await c.patch(f"/price-requests/{pr}", headers=d, json={"notes": "spec revised by customer"})
    check("the director can edit the notes too", r.status_code == 200, str(r.status_code))

    # ── 3. costing survives a later edit ─────────────────────────────────────
    await c.post(f"/price-requests/{pr}/price", headers=pu, json={"items": [
        {"line_no": 1, "cost_price": 5_000_000, "basis": "unit"},
        {"line_no": 2, "cost_price": 250_000, "basis": "unit"},
        {"line_no": 3, "cost_price": 400_000, "basis": "unit"},
    ]})
    priced = J(await c.get(f"/price-requests/{pr}", headers=d))
    check("purchasing costed all three lines",
          all(line(priced, f"{n} {tag}") and line(priced, f"{n} {tag}")["cost_price"]
              for n in ("Gearbox", "Coupling", "Seal kit")),
          str(priced.get("items"))[:200])

    # The whole point: change a quantity, drop a line, add a line.
    r = await c.patch(f"/price-requests/{pr}", headers=d, json={
        "items": [
            {"description": f"Gearbox {tag}", "qty": 5, "uom": "pcs"},   # qty change
            {"description": f"Seal kit {tag}", "qty": 1, "uom": "set"},  # reordered
            {"description": f"Bearing {tag}", "qty": 8, "uom": "pcs"},   # brand new
        ]})                                                              # Coupling dropped
    after = J(r)
    check("the director's edit is accepted on a costed request", r.status_code == 200, after)
    check("a line that only changed quantity KEEPS its cost",
          (line(after, f"Gearbox {tag}") or {}).get("cost_price") == 5_000_000,
          str(line(after, f"Gearbox {tag}")))
    check("...and the quantity actually changed",
          (line(after, f"Gearbox {tag}") or {}).get("qty") == 5,
          str(line(after, f"Gearbox {tag}")))
    check("a reordered line keeps its cost despite a new line_no",
          (line(after, f"Seal kit {tag}") or {}).get("cost_price") == 400_000,
          str(line(after, f"Seal kit {tag}")))
    check("a brand-new line comes back unpriced",
          (line(after, f"Bearing {tag}") or {}).get("cost_price") is None,
          str(line(after, f"Bearing {tag}")))
    check("the dropped line is gone", line(after, f"Coupling {tag}") is None,
          str([x["description"] for x in after.get("items", [])]))
    check("the lines are renumbered 1..n",
          [x["line_no"] for x in after.get("items", [])] == [1, 2, 3],
          str([x["line_no"] for x in after.get("items", [])]))

    # ── 4. approved sell prices survive too ──────────────────────────────────
    await c.post(f"/price-requests/{pr}/price", headers=pu, json={"items": [
        {"line_no": 3, "cost_price": 120_000, "basis": "unit"}]})
    await c.post(f"/price-requests/{pr}/approve", headers=d, json={"items": [
        {"line_no": 1, "sell_price": 9_000_000, "basis": "unit"},
        {"line_no": 2, "sell_price": 700_000, "basis": "unit"},
        {"line_no": 3, "sell_price": 200_000, "basis": "unit"},
    ]})
    appr = J(await c.get(f"/price-requests/{pr}", headers=d))
    check("the request is approved", appr.get("status") == "approved", str(appr.get("status")))

    r = await c.patch(f"/price-requests/{pr}", headers=d, json={
        "items": [
            {"description": f"Gearbox {tag}", "qty": 6, "uom": "pcs"},
            {"description": f"Seal kit {tag}", "qty": 2, "uom": "set"},
            {"description": f"Bearing {tag}", "qty": 8, "uom": "pcs"},
            {"description": f"Gasket {tag}", "qty": 10, "uom": "pcs"},
        ]})
    fin = J(r)
    check("the director can edit an APPROVED request", r.status_code == 200, fin)
    # Approval assigns by line_no as the lines stood *then*: Gearbox was 1,
    # Seal kit 2, Bearing 3 — so those are the prices that must survive.
    check("approved sell prices survive on the lines that stayed",
          (line(fin, f"Gearbox {tag}") or {}).get("sell_price") == 9_000_000
          and (line(fin, f"Seal kit {tag}") or {}).get("sell_price") == 700_000
          and (line(fin, f"Bearing {tag}") or {}).get("sell_price") == 200_000,
          str([(x["description"], x.get("sell_price")) for x in fin.get("items", [])]))
    check("...and so do the costs",
          (line(fin, f"Gearbox {tag}") or {}).get("cost_price") == 5_000_000,
          str(line(fin, f"Gearbox {tag}")))
    check("the line added after approval has no sell price",
          (line(fin, f"Gasket {tag}") or {}).get("sell_price") is None,
          str(line(fin, f"Gasket {tag}")))

    # ── 5. a renamed line is a different item ────────────────────────────────
    r = J(await c.patch(f"/price-requests/{pr}", headers=d, json={
        "items": [{"description": f"Gearbox {tag} REV-B", "qty": 6, "uom": "pcs"}]}))
    check("renaming a line drops its pricing — it is a different item now",
          (line(r, f"Gearbox {tag} REV-B") or {}).get("sell_price") is None,
          str(r.get("items")))

    # ── 6. the override leaves a trail ───────────────────────────────────────
    audit = J(await c.get("/audit", headers=d,
                          params={"action": "override_edit", "entity": "price_request", "limit": 20}))
    mine = [a for a in audit if str(a.get("entity_id")) == str(pr)] if isinstance(audit, list) else []
    check("editing past draft is written to the audit log", len(mine) >= 1, str(audit)[:140])
    if mine:
        check("...recording the status it was in and the lines before",
              (mine[0].get("before") or {}).get("status") is not None
              and (mine[0].get("before") or {}).get("items") is not None,
              str(mine[0])[:180])

    # A draft edit is ordinary work and should NOT be logged as an override.
    pr2 = await fresh_pr()
    await c.patch(f"/price-requests/{pr2}", headers=d, json={
        "items": [{"description": f"Gearbox {tag}", "qty": 1, "uom": "pcs"}]})
    audit2 = J(await c.get("/audit", headers=d,
                           params={"action": "override_edit", "entity": "price_request", "limit": 50}))
    check("editing a draft is not logged as an override",
          not [a for a in audit2 if str(a.get("entity_id")) == str(pr2)] if isinstance(audit2, list) else False,
          str(audit2)[:140])

    # ── 7. scoping is unchanged ──────────────────────────────────────────────
    s2 = await login(c, "sales2@demo.local")
    r = await c.patch(f"/price-requests/{pr2}", headers=s2, json={
        "items": [{"description": "not mine", "qty": 1}]})
    check("another rep still cannot touch someone else's request",
          r.status_code in (403, 404), str(r.status_code))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")


asyncio.run(main())

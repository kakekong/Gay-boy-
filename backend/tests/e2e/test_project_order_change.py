"""The sales rep arranges a won job's order; the director approves it.

On a project's Order card the customer's sales rep can move lines, edit a
line (item name, quantity, unit, spec, selling price) and add items — as one proposal that applies only when the
director approves it (from the inbox or the card). The director's own change
applies at once. An added line named like one already on the order takes its
cost from it; a genuinely new item goes in without a cost. Lines can't be
removed. Only the customer's rep and the director arrange the order, and the
rep never sees what the goods cost.
"""
import asyncio, os, sys, uuid
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123",
    STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import httpx, logging; logging.disable(logging.INFO)
TAG = uuid.uuid4().hex[:5].upper()
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
                          base_url="http://t/api/v1", timeout=180)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d, s1, s2, pur = [await login(f"{x}@demo.local")
                      for x in ("director", "sales1", "sales2", "purchasing")]

    names = [f"Roller Chain RS 60 {TAG}", f"Sprocket B 60 1R 25T {TAG}", f"Connecting Link {TAG}"]
    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Atur {TAG}", "industry": "mining"}))["id"]
    pr = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust, "items": [{"description": n, "qty": 1, "uom": "pcs"} for n in names]}))
    await c.post(f"/price-requests/{pr['id']}/submit", headers=s1)
    await c.post(f"/price-requests/{pr['id']}/price", headers=pur, json={
        "items": [{"line_no": i + 1, "cost_price": 100_000, "basis": "unit"} for i in range(3)]})
    await c.post(f"/price-requests/{pr['id']}/approve", headers=d, json={
        "items": [{"line_no": i + 1, "sell_price": 150_000, "basis": "unit"} for i in range(3)]})
    q = J(await c.post(f"/quotations/from-price-request/{pr['id']}", headers=s1))
    await c.post(f"/quotations/{q['id']}/submit", headers=s1)
    await c.post(f"/quotations/{q['id']}/approve", headers=d, json={"notes": ""})
    po = J(await c.post("/customer-pos", headers=s1, json={
        "customer_id": cust, "quotation_id": q["id"], "number": f"PO-{TAG}",
        "items": [{"description": n, "qty": 1, "unit_price": 150_000} for n in names],
        "is_downpayment": False}))
    pid = J(await c.post(f"/customer-pos/{po['id']}/approve", headers=d, json={"notes": ""}))["project_id"]
    base = f"/operation/projects/{pid}/order-change"

    async def card(who=d):
        return J(await c.get(f"/operation/projects/{pid}/full", headers=who))["price_request"]["items"]

    def lns(items):
        return [i["line_no"] for i in items]

    print("\n── who arranges it ──")
    m = J(await c.get(base, headers=s1))
    check("the customer's rep may arrange the order", m.get("may_arrange") is True
          and m.get("is_director") is False and m.get("pending") is None, str(m))
    check("...and sees the selling price but not the cost",
          all("sell_price" in i and "cost_price" not in i for i in await card(s1)))
    r = await c.get(base, headers=s2)
    check("another rep can't", r.status_code == 403, str(r.status_code))
    r = await c.post(base, headers=pur, json={"lines": [{"line_no": n} for n in (1, 2, 3)]})
    check("nor purchasing", r.status_code == 403, str(r.status_code))

    print("\n── the rep proposes ──")
    proposal = {"note": f"Customer wants the links first {TAG}", "lines": [
        {"line_no": 3}, {"line_no": 1},
        {"line_no": 2, "sell_price": 175_000},
        {"description": f"roller chain rs 60 {TAG.lower()}", "qty": 2, "sell_price": 150_000},
        {"description": f"Brand New Bearing {TAG}", "qty": 1, "uom": "pcs", "sell_price": 50_000},
    ]}
    r = await c.post(base, headers=s1, json=proposal)
    out = J(r)
    check("the rep's change goes to the director", r.status_code == 200
          and out.get("status") == "pending_approval", f"{r.status_code} {out}"[:200])
    summ = " | ".join(out.get("summary", []))
    check("...summarised: the new order, the price, both items",
          "new order" in summ and "175.000" in summ and "cost from line 1" in summ
          and "no cost yet" in summ, summ)
    C = await card()
    check("...nothing applies yet", lns(C) == [1, 2, 3]
          and next(i for i in C if i["line_no"] == 2)["sell_price"] == 150_000, str(lns(C)))
    m = J(await c.get(base, headers=d))
    check("the director sees it waiting, with the rep's note",
          m["pending"] and TAG in (m["pending"]["note"] or ""), str(m.get("pending"))[:200])
    await c.post(base, headers=s1, json=proposal)
    rows = J(await c.get("/approvals", headers=d))
    rows = rows if isinstance(rows, list) else rows.get("items", [])
    mine = [x for x in rows if x.get("target_id") == pid and x.get("target_type") == "project_order"]
    check("asking again revises it — one request in the inbox", len(mine) == 1, str(len(mine)))

    print("\n── the director approves ──")
    r = await c.post(f"/approvals/{mine[0]['id']}/approve", headers=d)
    check("approved from the inbox", r.status_code == 200, f"{r.status_code} {J(r)}"[:200])
    C = await card()
    check("...the order is as proposed", lns(C) == [3, 1, 2, 4, 5], str(lns(C)))
    by = {i["line_no"]: i for i in C}
    check("...line 2 at the new price", by[2]["sell_price"] == 175_000, str(by[2]))
    check("...the same chain again carries line 1's cost", by[4]["cost_price"] == 100_000
          and by[4]["qty"] == 2, str(by[4]))
    check("...the new bearing has no cost yet", by[5].get("cost_price") is None, str(by[5]))
    bell = J(await c.get("/notifications", headers=s1)).get("items", [])
    check("...and the rep is told, linked to the project",
          any(i.get("kind") == "approval_decided" and i.get("link") == f"/projects/{pid}"
              for i in bell), str([i for i in bell if i.get("kind") == "approval_decided"])[:200])

    print("\n── limits ──")
    r = await c.post(base, headers=s1, json={"lines": [{"line_no": n} for n in (3, 2, 4, 5)]})
    check("a line can't be removed", r.status_code == 400, f"{r.status_code} {J(r)}"[:150])
    r = await c.post(base, headers=s1, json={"lines": [{"line_no": n} for n in (3, 1, 2, 4, 5)]})
    check("a proposal that changes nothing is refused", r.status_code == 400, str(r.status_code))

    print("\n── declined, and the director's own change ──")
    await c.post(base, headers=s1, json={"lines": [
        {"line_no": 1, "sell_price": 1}, *[{"line_no": n} for n in (3, 2, 4, 5)]]})
    req = J(await c.get(base, headers=d))["pending"]["id"]
    await c.post(f"/approvals/{req}/reject", headers=d, params={"notes": "too cheap"})
    C = await card()
    check("declined: the order stays", lns(C) == [3, 1, 2, 4, 5]
          and {i["line_no"]: i for i in C}[1]["sell_price"] == 150_000, str(lns(C)))
    r = await c.post(base, headers=d, json={"lines": [
        *[{"line_no": n} for n in (1, 2, 3, 4)], {"line_no": 5, "sell_price": 60_000}]})
    C = await card()
    check("the director's change applies at once", J(r).get("status") == "applied"
          and lns(C) == [1, 2, 3, 4, 5] and {i["line_no"]: i for i in C}[5]["sell_price"] == 60_000,
          f"{J(r)} {lns(C)}"[:200])

    print("\n── editing a line ──")
    order = [{"line_no": n} for n in (2, 3, 4, 5)]
    r = await c.post(base, headers=s1, json={"lines": [
        {"line_no": 1, "description": f"Roller Chain RS 80 {TAG}", "qty": 3, "uom": "m",
         "spec": "riveted"}, *order]})
    summ = " | ".join(J(r).get("summary", []))
    check("the rep edits a line's name, quantity, unit and spec — sent to the director",
          J(r).get("status") == "pending_approval" and "Rename" in summ and "1 → 3" in summ
          and "pcs → m" in summ and "Spec" in summ, f"{J(r)}"[:250])
    C = {i["line_no"]: i for i in await card()}
    check("...nothing changes until approved", C[1]["qty"] == 1 and C[1]["description"] == names[0])
    req = J(await c.get(base, headers=d))["pending"]["id"]
    await c.post(f"/approvals/{req}/approve", headers=d)
    C = {i["line_no"]: i for i in await card()}
    check("...approved: the line reads as edited, its cost kept",
          C[1]["description"] == f"Roller Chain RS 80 {TAG}" and C[1]["qty"] == 3
          and C[1]["uom"] == "m" and C[1]["spec"] == "riveted" and C[1]["cost_price"] == 100_000,
          str(C[1]))
    r = await c.post(base, headers=d, json={"lines": [{"line_no": 1, "qty": 5}, *order]})
    C = {i["line_no"]: i for i in await card()}
    check("the director's edit applies at once", J(r).get("status") == "applied" and C[1]["qty"] == 5,
          f"{J(r)}"[:200])
    r = await c.post(base, headers=s1, json={"lines": [{"line_no": 1, "description": "  "}, *order]})
    check("a line can't lose its name", r.status_code == 400, str(r.status_code))
    r = await c.post(base, headers=s1, json={"lines": [{"line_no": 1, "qty": 0}, *order]})
    check("...or go to zero quantity", r.status_code == 400, str(r.status_code))

    print("\n── purchasing corrects the cost ──")
    costs = f"/operation/projects/{pid}/order-costs"
    m = J(await c.get(base, headers=pur))
    check("purchasing may change costs (not arrange the order)",
          m.get("may_cost") is True and m.get("may_arrange") is False, str(m)[:150])
    r = await c.post(costs, headers=s1, json={"lines": [{"line_no": 2, "cost_price": 90_000}]})
    check("the rep can't", r.status_code == 403, str(r.status_code))
    r = await c.post(costs, headers=pur, json={"lines": [{"line_no": 2, "cost_price": -1}]})
    check("a negative cost is refused", r.status_code == 400, str(r.status_code))
    r = await c.post(costs, headers=pur, json={"lines": [{"line_no": 99, "cost_price": 1}]})
    check("...and a line that isn't there", r.status_code == 400, str(r.status_code))
    r = await c.post(costs, headers=pur, json={"lines": [{"line_no": 2, "cost_price": 90_000}]})
    C = {i["line_no"]: i for i in await card(pur)}
    check("purchasing's cost applies at once", J(r).get("status") == "applied"
          and C[2]["cost_price"] == 90_000 and "90.000" in " ".join(J(r)["summary"]), f"{J(r)}"[:200])
    qd = J(await c.get(f"/quotations/{q['id']}", headers=d))
    est = {int(i["line_no"]): float(i.get("cost_estimate") or 0) for i in qd["items"]}
    check("...and the quotation's cost estimate follows", est.get(2) == 90_000, str(est))
    D2 = {i["line_no"]: i for i in await card(d)}[2]
    check("...its selling price untouched (purchasing never sees it)",
          D2["sell_price"] == 175_000 and "sell_price" not in C[2], str(D2))
    r = await c.post(costs, headers=pur, json={"lines": [{"line_no": 2, "cost_price": 90_000}]})
    check("saving the same cost again changes nothing", r.status_code == 400, str(r.status_code))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

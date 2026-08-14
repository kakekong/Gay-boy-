"""The job starts at Won, not at the PO's second signature.

A project used to be minted when the director approved the customer PO.
Won already means the customer said yes *and* their order is on file — that
is enforced, it is what the word means here — so waiting for a second
signature left sales looking at a won deal with nowhere to put the drawing,
and purchasing unable to raise anything against it.

Now Won mints the job. The customer PO's approval still happens and still
matters; it attaches to the project already there instead of creating one.

The thing that has to hold either way is that there is exactly **one** job.
Approving the PO after Won, approving it twice, or filing a second PO
against the same quotation must all land on the same project — the old code
spawned a duplicate on a re-approval and had to grow a guard for it.

One case keeps the old timing on purpose: a **down-payment order**. The
whole point of a deposit is that we don't start until it arrives, so those
still wait for sales to confirm the money landed.
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
    pur = await login("purchasing@demo.local")
    s1 = await login("sales1@demo.local")
    fin = await login("finance@demo.local")

    async def quoted(n: int) -> tuple[str, str]:
        """A customer with an approved quotation. Returns (customer, quote)."""
        cust = J(await c.post("/customers", headers=s1, json={
            "company_name": f"PT Menang {tag}-{n}", "industry": "mining"}))["id"]
        pr = J(await c.post("/price-requests", headers=s1, json={
            "customer_id": cust,
            "items": [{"description": f"CHAIN {tag}", "qty": 2, "uom": "meter"}]}))
        await c.post(f"/price-requests/{pr['id']}/submit", headers=s1)
        await c.post(f"/price-requests/{pr['id']}/price", headers=pur, json={
            "items": [{"line_no": 1, "cost_price": 500, "basis": "unit"}]})
        await c.post(f"/price-requests/{pr['id']}/approve", headers=d, json={
            "items": [{"line_no": 1, "sell_price": 1000, "basis": "unit"}]})
        q = J(await c.post(f"/quotations/from-price-request/{pr['id']}", headers=s1))
        await c.post(f"/quotations/{q['id']}/submit", headers=s1)
        await c.post(f"/quotations/{q['id']}/approve", headers=d, json={"notes": ""})
        return cust, q["id"]

    async def projects_for(quote_id: str) -> list[dict]:
        rows = J(await c.get("/operation/projects", headers=d))
        out = []
        for p in rows if isinstance(rows, list) else []:
            full = J(await c.get(f"/operation/projects/{p['id']}/full", headers=d))
            if (full.get("quotation") or {}).get("id") == quote_id:
                out.append(full)
        return out

    # ══ the ordinary order ═══════════════════════════════════════════════════
    print("\n── Won is what starts the job ──")
    cust, quote = await quoted(1)
    check("no project before the customer's order is even filed",
          not await projects_for(quote))

    cpo = J(await c.post("/customer-pos", headers=s1, json={
        "customer_id": cust, "quotation_id": quote, "number": f"CPO-W{tag}",
        "items": [{"description": f"CHAIN {tag}", "qty": 2, "unit_price": 1000}],
        "is_downpayment": False}))
    check("sales file the customer's PO", bool(cpo.get("id")), str(cpo)[:140])
    check("...and filing it alone still starts nothing",
          not await projects_for(quote))

    r = await c.post(f"/quotations/{quote}/won", headers=d)
    check("the director marks it Won", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:140])
    made = await projects_for(quote)
    check("...and that is what creates the project", len(made) == 1,
          str(len(made)))
    proj = made[0] if made else {}
    code = (proj.get("project") or {}).get("code")
    check("...carrying the customer's PO number onto it",
          (proj.get("project") or {}).get("po_number") == f"CPO-W{tag}",
          str((proj.get("project") or {}).get("po_number")))
    check("...and the order's value", float((proj.get("project") or {}).get("po_value") or 0) == 2000.0,
          str((proj.get("project") or {}).get("po_value")))
    check("...linked back to the quotation it came from",
          (proj.get("quotation") or {}).get("id") == quote,
          str((proj.get("quotation") or {}).get("id")))

    # The PO now points at it, so the PO page opens the job.
    got = J(await c.get(f"/customer-pos/{cpo['id']}", headers=d))
    check("the customer PO points at the project",
          got.get("project_id") is not None, str(got.get("project_id")))

    print("\n── the PO's approval attaches, it does not duplicate ──")
    r = await c.post(f"/customer-pos/{cpo['id']}/approve", headers=d,
                     json={"notes": ""})
    check("the director approves the PO", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:140])
    after = await projects_for(quote)
    check("...and there is still exactly one project", len(after) == 1,
          str([(x.get('project') or {}).get('code') for x in after]))
    check("...the same one", (after[0].get("project") or {}).get("code") == code,
          f"{(after[0].get('project') or {}).get('code')} vs {code}")
    check("...and the approval still reports it",
          J(r).get("project_id") is not None, str(J(r))[:140])

    r = await c.post(f"/customer-pos/{cpo['id']}/approve", headers=d,
                     json={"notes": "again"})
    check("approving an already-approved PO is refused", r.status_code == 409,
          str(r.status_code))
    check("...and nothing was minted by the attempt",
          len(await projects_for(quote)) == 1)

    # ══ sales' Won goes through the director, and mints on approval ══════════
    print("\n── when sales ask for the Won, the approval mints it ──")
    cust2, quote2 = await quoted(2)
    await c.post("/customer-pos", headers=s1, json={
        "customer_id": cust2, "quotation_id": quote2, "number": f"CPO-S{tag}",
        "items": [{"description": f"CHAIN {tag}", "qty": 2, "unit_price": 1000}],
        "is_downpayment": False})
    r = await c.post(f"/quotations/{quote2}/won", headers=s1)
    check("sales' mark-won is queued for the director", r.status_code == 202,
          f"{r.status_code} {J(r)}"[:140])
    check("...and starts nothing on its own", not await projects_for(quote2),
          "a request is not a decision")

    req = next((a for a in J(await c.get("/approvals", headers=d))
                if a.get("target_type") == "quotation_won"
                and a.get("target_id") == quote2), None)
    check("the request is in the director's queue", req is not None)
    if req:
        r = await c.post(f"/approvals/{req['id']}/approve", headers=d)
        check("...the director signs it off", r.status_code == 200,
              f"{r.status_code} {J(r)}"[:140])
        check("...and the job starts then", len(await projects_for(quote2)) == 1,
              str(len(await projects_for(quote2))))

    # ══ a second order against the same quotation ════════════════════════════
    print("\n── a second PO on the same deal is not a second job ──")
    cpo2 = J(await c.post("/customer-pos", headers=s1, json={
        "customer_id": cust, "quotation_id": quote, "number": f"CPO-W2{tag}",
        "items": [{"description": f"CHAIN {tag}", "qty": 1, "unit_price": 1000}],
        "is_downpayment": False}))
    if cpo2.get("id"):
        r = await c.post(f"/customer-pos/{cpo2['id']}/approve", headers=d,
                         json={"notes": ""})
        check("the second PO is approved", r.status_code == 200,
              f"{r.status_code} {J(r)}"[:140])
        rows = await projects_for(quote)
        check("...onto the job that already exists", len(rows) == 1,
              str([(x.get('project') or {}).get('code') for x in rows]))

    # ══ the deposit gate is untouched ════════════════════════════════════════
    print("\n── a down payment still waits for the money ──")
    cust3, quote3 = await quoted(3)
    dp = J(await c.post("/customer-pos", headers=s1, json={
        "customer_id": cust3, "quotation_id": quote3, "number": f"CPO-DP{tag}",
        "items": [{"description": f"CHAIN {tag}", "qty": 2, "unit_price": 1000}],
        "is_downpayment": True, "dp_amount": 500}))
    check("a down-payment order is filed", bool(dp.get("id")), str(dp)[:160])
    r = await c.post(f"/quotations/{quote3}/won", headers=d)
    check("the deal can still be marked Won", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:140])
    check("...but no job starts on a deposit that hasn't arrived",
          not await projects_for(quote3),
          str([(x.get('project') or {}).get('code') for x in await projects_for(quote3)]))

    r = await c.post(f"/customer-pos/{dp['id']}/dp/finance-approve", headers=fin,
                     json={"notes": "ok"})
    check("finance approve the deposit terms", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:140])
    check("...still no job", not await projects_for(quote3))

    r = await c.post(f"/customer-pos/{dp['id']}/dp/sales-confirm", headers=s1,
                     json={"notes": "landed"})
    check("sales confirm the deposit landed", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:140])
    check("...and that is when the job starts",
          len(await projects_for(quote3)) == 1,
          str(len(await projects_for(quote3))))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        sys.exit(1)


asyncio.run(main())

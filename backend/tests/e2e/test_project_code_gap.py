"""A deleted project must not poison the next one's code.

Reported from production: approving a customer PO died with

    duplicate key value violates unique constraint "ix_projects_code"
    DETAIL: Key (code)=(PRJ-2026-0003) already exists.

and it kept dying, because nothing about it was transient. Projects took
their code from `COUNT(*) + 1` over the codes already issued that year, and
a count walks backwards the moment a row is deleted. Delete PRJ-2026-0002 —
which *Clear test data* does, hard — and the count says two while 0003 is
still sitting there. Every customer-PO approval after that asks for a code
that is already taken. Approving the PO is the step that starts the job, so
the whole pipeline stopped in the same place every time, and the only way
out was to create enough projects to climb back over the hole.

`app/services/numbering.py` exists because this was already found and fixed
for quotations, price requests and supplier POs — its docstring describes
this exact failure. Projects and purchase requests were simply never moved
onto it. They are now: the next number is one past the **highest issued**,
which cannot walk backwards, so a hole in the sequence stays a hole.

This driver digs the hole on purpose and then asks for the next code.
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

CONFIRM = "DELETE TEST DATA"


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

    async def a_project(n: int) -> tuple[str, str]:
        """Run a job all the way to an approved customer PO. Returns
        (project_id, code)."""
        cust = J(await c.post("/customers", headers=s1, json={
            "company_name": f"PT Lubang {tag}-{n}", "industry": "mining"}))["id"]
        pr = J(await c.post("/price-requests", headers=s1, json={
            "customer_id": cust,
            "items": [{"description": f"CHAIN {tag}", "qty": 1, "uom": "meter"}]}))
        await c.post(f"/price-requests/{pr['id']}/submit", headers=s1)
        await c.post(f"/price-requests/{pr['id']}/price", headers=pur, json={
            "items": [{"line_no": 1, "cost_price": 500, "basis": "unit"}]})
        await c.post(f"/price-requests/{pr['id']}/approve", headers=d, json={
            "items": [{"line_no": 1, "sell_price": 1000, "basis": "unit"}]})
        q = J(await c.post(f"/quotations/from-price-request/{pr['id']}", headers=s1))
        await c.post(f"/quotations/{q['id']}/submit", headers=s1)
        await c.post(f"/quotations/{q['id']}/approve", headers=d, json={"notes": ""})
        cpo = J(await c.post("/customer-pos", headers=s1, json={
            "customer_id": cust, "quotation_id": q["id"], "number": f"CPO-G{tag}-{n}",
            "items": [{"description": f"CHAIN {tag}", "qty": 1, "unit_price": 1000}],
            "is_downpayment": False}))
        await c.post(f"/quotations/{q['id']}/won", headers=d)
        r = await c.post(f"/customer-pos/{cpo['id']}/approve", headers=d,
                         json={"notes": ""})
        # The production symptom was a 500 here. Say so plainly rather than
        # letting the next line fail on a missing key.
        if r.status_code >= 400:
            return ("", f"HTTP {r.status_code}: {str(J(r))[:200]}")
        pid = J(r)["project_id"]
        full = J(await c.get(f"/operation/projects/{pid}/full", headers=d))
        return pid, full["project"]["code"]

    print("\n── three jobs, and a hole punched in the middle ──")
    # Production's shape exactly: the deleted row is not the last one, so a
    # higher code is still live and a count-based counter lands straight on
    # it. (Deleting the newest is a different case — that number is free
    # again, and reissuing it collides with nothing.)
    p1, code1 = await a_project(1)
    p2, code2 = await a_project(2)
    p3, code3 = await a_project(3)
    check("three customer POs became three projects", all([p1, p2, p3]),
          f"{code1} / {code2} / {code3}")
    check("...numbered in order", len({code1, code2, code3}) == 3,
          f"{code1} / {code2} / {code3}")

    # Hard delete, the way "Clear test data" does it — not the soft delete on
    # the project page, which leaves the row and would hide the bug.
    r = await c.post("/maintenance/records/delete", headers=d, json={
        "targets": [{"type": "project", "id": p2}], "confirm": CONFIRM})
    check("the middle project is deleted outright", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:160])
    r = await c.get(f"/operation/projects/{p2}/full", headers=d)
    check("...and is really gone", r.status_code == 404, str(r.status_code))

    print("\n── the next approval must still go through ──")
    p4, code4 = await a_project(4)
    check("approving the next customer PO works", bool(p4),
          code4)                       # carries the HTTP error when it doesn't
    check("...on a code no live project already holds",
          code4 not in (code1, code3), f"{code4} vs live {code1}/{code3}")

    def tail(code: str) -> int:
        return int(code.rsplit("-", 1)[-1])
    check("...counted up from the highest issued, so the hole stays a hole",
          tail(code4) > tail(code3), f"{code4} vs {code3}")

    # And prove the collision the user hit is gone for good: keep approving
    # over the gap rather than stopping at the first one.
    p5, code5 = await a_project(5)
    check("...and the one after that too", bool(p5) and tail(code5) > tail(code4),
          f"{code4} → {code5}")

    print("\n── and the same for a purchase request ──")
    # PR numbers had the identical count-based bug, one table over, so they
    # get the identical hole punched in them.
    made = []
    for _ in range(3):
        r = await c.post("/purchasing/pr", headers=pur, json={
            "project_id": p1,
            "items": [{"description": f"BOLT {tag}", "qty": 1}]})
        made.append(J(r).get("number") if r.status_code < 400 else f"HTTP {r.status_code}")
    check("three purchase requests were raised",
          all(m and "HTTP" not in str(m) for m in made), str(made))
    check("...with different numbers", len(set(made)) == 3, str(made))

    pr_rows = J(await c.get("/purchasing/pr", headers=pur))
    victim = next((x for x in pr_rows if x.get("number") == made[1]), None)
    check("the middle one is findable", victim is not None, str(made))
    if victim:
        r = await c.post("/maintenance/records/delete", headers=d, json={
            "targets": [{"type": "purchase_request", "id": victim["id"]}],
            "confirm": CONFIRM})
        check("...and deleted", r.status_code == 200, f"{r.status_code} {J(r)}"[:140])
        r = await c.post("/purchasing/pr", headers=pur, json={
            "project_id": p1,
            "items": [{"description": f"NUT {tag}", "qty": 1}]})
        check("the next purchase request still gets raised",
              r.status_code in (200, 201), f"{r.status_code} {J(r)}"[:160])
        check("...on a number no live one holds",
              J(r).get("number") not in (made[0], made[2]),
              f"{J(r).get('number')} vs live {made[0]}/{made[2]}")

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        sys.exit(1)


asyncio.run(main())

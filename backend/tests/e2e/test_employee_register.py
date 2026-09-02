"""The employee register, and the rule that a login comes second.

The thing under test is an ordering, not a form. Before this, somebody only
existed once IT had given them a password, so the record of a person was a
side effect of the account — which is why a name typed twice produced two
people, and why anybody without a login was invisible on the one page meant
to be the whole company.

So: an internal account is refused unless it is created against a register
entry, that entry cannot already have a login, and a leaver cannot be handed
one. Portal accounts are the deliberate exception in the other direction — a
customer is not an employee, and offering them a staff number is refused too,
because a rule you can satisfy by picking anything is not a rule.

The other half is that the register is the source of the name and the start
date. A misspelling fixed in HR that leaves next month's documents still
wrong is exactly the two-spellings-of-one-person problem the split was
supposed to end, so the propagation is checked, not assumed.
"""
import asyncio, os, sys, uuid
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123",
    STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import httpx, logging; logging.disable(logging.INFO)
TAG = uuid.uuid4().hex[:6]
PASS, FAIL = [], []
def check(n, c, d=""):
    (PASS if c else FAIL).append(n); print(("  PASS " if c else "  FAIL ")+n+(f"  [{d}]" if d and not c else ""))
def J(r):
    try: return r.json()
    except Exception: return {"_": r.text[:200]}
def why(r):
    b = J(r)
    return str(b.get("detail")
               or (b.get("errors") or [{}])[0].get("message", "")).lower()


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)

    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    hr = await login("hr@demo.local")
    s1 = await login("sales1@demo.local")

    # ══ the register ═════════════════════════════════════════════════════
    print("\n── somebody joins ──")
    r = await c.post("/employees", headers=hr, json={
        "full_name": f"Siti Rahmawati {TAG}", "position": "Sales Engineer",
        "department": "Sales", "intended_role": "sales",
        "join_date": "2026-03-02", "phone": "+628111000111",
        "personal_email": f"siti.{TAG}@gmail.example"})
    check("HR can put somebody on the register", r.status_code == 201,
          f"{r.status_code} {J(r)}"[:200])
    emp = J(r)
    check("...and gets a staff number without having to invent one",
          bool(emp.get("employee_no")), str(emp)[:150])
    check("...which is not yet a login", emp.get("has_login") is False, str(emp)[:150])

    r = await c.post("/employees", headers=hr, json={
        "full_name": f"Budi Hartono {TAG}", "employee_no": emp["employee_no"]})
    check("...and a staff number cannot be handed out twice",
          r.status_code == 409 and "already belongs" in why(r),
          f"{r.status_code} {why(r)}")

    r = await c.post("/employees", headers=hr, json={
        "full_name": f"Rina {TAG}", "intended_role": "chief_wizard"})
    check("...nor a role the system does not have",
          r.status_code == 400 and "not a role" in why(r), f"{r.status_code} {why(r)}")

    r = await c.post("/employees", headers=s1, json={"full_name": "Nope"})
    check("sales cannot write the register", r.status_code == 403, str(r.status_code))

    # A second person, hired into finance — one of the two roles that used to
    # be missing from the page entirely.
    fin = J(await c.post("/employees", headers=hr, json={
        "full_name": f"Dewi Anggraini {TAG}", "position": "Accounting Staff",
        "department": "Finance", "intended_role": "finance"}))
    pur = J(await c.post("/employees", headers=hr, json={
        "full_name": f"Agus Salim {TAG}", "department": "Purchasing",
        "intended_role": "purchasing"}))

    cat = J(await c.get("/employees/catalog", headers=d))
    check("the roles an employee can hold include finance and purchasing",
          {"finance", "purchasing"} <= set(cat.get("roles", [])), str(cat)[:200])
    check("...and stop short of the portal roles, who are not employees",
          not ({"customer", "supplier"} & set(cat.get("roles", []))), str(cat)[:200])

    # ══ the login comes second ═══════════════════════════════════════════
    print("\n── then, separately, a way to sign in ──")
    r = await c.post("/users", headers=d, json={
        "email": f"siti.{TAG}@demo.local", "full_name": f"Siti Rahmawati {TAG}",
        "role": "sales", "password": "test-pass-123"})
    check("an internal account is refused with nobody behind it",
          r.status_code == 400 and "register" in why(r), f"{r.status_code} {why(r)}")

    r = await c.post("/users", headers=d, json={
        "email": f"ghost.{TAG}@demo.local", "full_name": "Ghost", "role": "sales",
        "password": "test-pass-123", "employee_id": str(uuid.uuid4())})
    check("...and refused against a record that does not exist",
          r.status_code == 400 and "unknown employee" in why(r),
          f"{r.status_code} {why(r)}")

    r = await c.post("/users", headers=d, json={
        "email": f"siti.{TAG}@demo.local", "full_name": "typed wrong on purpose",
        "role": "sales", "password": "test-pass-123", "employee_id": emp["id"]})
    check("with the record named, the account is created",
          r.status_code == 201, f"{r.status_code} {J(r)}"[:200])
    uid = J(r).get("id")
    check("...and it is tied to that person",
          J(r).get("employee_id") == emp["id"], str(J(r))[:150])

    got = J(await c.get(f"/users/{uid}", headers=d))
    check("...taking its name from the register, not from what was typed",
          got.get("full_name") == f"Siti Rahmawati {TAG}", str(got.get("full_name")))
    check("...and the start date payroll reads with it",
          str(got.get("join_date")) == "2026-03-02", str(got.get("join_date")))

    r = await c.post("/users", headers=d, json={
        "email": f"siti2.{TAG}@demo.local", "full_name": "Siti again",
        "role": "sales", "password": "test-pass-123", "employee_id": emp["id"]})
    check("one person cannot be given a second login",
          r.status_code == 409 and "already signs in" in why(r),
          f"{r.status_code} {why(r)}")

    # ══ portal accounts are the other way round ══════════════════════════
    print("\n── the people who are not employees ──")
    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Register {TAG}", "industry": "mining"}))
    r = await c.post("/users", headers=d, json={
        "email": f"portal.{TAG}@customer.example", "full_name": "Customer Portal",
        "role": "customer", "password": "test-pass-123",
        "linked_customer_id": cust["id"]})
    check("a customer login needs no employee record", r.status_code == 201,
          f"{r.status_code} {J(r)}"[:200])
    check("...and does not get one", J(r).get("employee_id") is None, str(J(r))[:150])

    r = await c.post("/users", headers=d, json={
        "email": f"portal2.{TAG}@customer.example", "full_name": "Customer Portal 2",
        "role": "customer", "password": "test-pass-123",
        "linked_customer_id": cust["id"], "employee_id": fin["id"]})
    check("...and is refused one if offered", r.status_code == 400
          and "outside the company" in why(r), f"{r.status_code} {why(r)}")

    # ══ leavers ══════════════════════════════════════════════════════════
    print("\n── somebody leaves ──")
    r = await c.delete(f"/employees/{pur['id']}", headers=d)
    check("the director marks a leaver", r.status_code == 204, str(r.status_code))
    gone = J(await c.get(f"/employees/{pur['id']}", headers=hr))
    check("...the record stays — everything they signed still points at it",
          gone.get("full_name") == f"Agus Salim {TAG}", str(gone)[:150])
    check("...with the day they left written down", bool(gone.get("end_date")),
          str(gone.get("end_date")))

    r = await c.post("/users", headers=d, json={
        "email": f"agus.{TAG}@demo.local", "full_name": "Agus", "role": "purchasing",
        "password": "test-pass-123", "employee_id": pur["id"]})
    check("a leaver cannot be handed a login",
          r.status_code == 400 and "leaver" in why(r), f"{r.status_code} {why(r)}")

    r = await c.delete(f"/employees/{emp['id']}", headers=d, params={"hard": True})
    check("and a record with a login is never deleted out from under it",
          r.status_code == 409 and "has a login" in why(r), f"{r.status_code} {why(r)}")

    r = await c.delete(f"/employees/{fin['id']}", headers=d, params={"hard": True})
    check("...while one typed by mistake can be removed", r.status_code == 204,
          str(r.status_code))

    # ══ the register is where the name is decided ════════════════════════
    print("\n── HR corrects the spelling ──")
    r = await c.patch(f"/employees/{emp['id']}", headers=hr,
                      json={"full_name": f"Siti Rahmawati Dewi {TAG}",
                            "join_date": "2026-04-01"})
    check("HR can correct the record", r.status_code == 200, f"{r.status_code} {J(r)}"[:200])
    got = J(await c.get(f"/users/{uid}", headers=d))
    check("...and the login follows, rather than keeping the old spelling",
          got.get("full_name") == f"Siti Rahmawati Dewi {TAG}", str(got.get("full_name")))
    check("...as does the start date payroll pays a first month against",
          str(got.get("join_date")) == "2026-04-01", str(got.get("join_date")))

    # ══ what the two screens read ════════════════════════════════════════
    print("\n── the register, and the picker built on it ──")
    rows = J(await c.get("/employees", headers=hr))
    mine = next((x for x in rows if x["id"] == emp["id"]), None)
    check("the register lists everybody", isinstance(rows, list) and mine is not None,
          str(rows)[:200])
    check("...saying who can sign in and as what",
          mine and mine["has_login"] and mine["user_email"] == f"siti.{TAG}@demo.local",
          str(mine)[:220])
    check("...and leaves the leaver out of the active list",
          not any(x["id"] == pur["id"] for x in rows), str(len(rows)))
    check("...but finds them when asked for everyone",
          any(x["id"] == pur["id"] for x in
              J(await c.get("/employees", headers=hr, params={"active_only": False}))))

    waiting = J(await c.get("/employees", headers=d, params={"without_login": True}))
    check("the login picker offers only people who still need one",
          all(not x["has_login"] for x in waiting), str(waiting)[:200])
    check("...so nobody who already signs in is offered",
          not any(x["id"] == emp["id"] for x in waiting), str(len(waiting)))

    r = await c.get("/employees", headers=s1)
    check("and sales cannot read the register at all", r.status_code == 403,
          str(r.status_code))

    # Everyone who had a login before the register existed was given a record
    # by the migration; without that the register would open empty on the
    # first deploy and every existing account would break the new rule.
    all_rows = J(await c.get("/employees", headers=d, params={"active_only": False}))
    linked = {x["user_email"] for x in all_rows if x["has_login"]}
    check("every demo login already on the system has a record behind it",
          {"director@demo.local", "hr@demo.local", "sales1@demo.local",
           "finance@demo.local", "purchasing@demo.local"} <= linked,
          str(sorted(linked))[:300])

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)


asyncio.run(main())

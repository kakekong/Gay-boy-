"""HR keeps the employment record: the name, the start date, the bank account.

Asked for: *"fix the hr also Employee data can be edit. Add tgl masuk, nomor
rekening (nama Bank, no, atas nama)."*

Two things were wrong. HR runs the people side of the company and could not
change a single field on a person — every edit was the director's, so a
misspelled name or a new bank account meant asking them. And the record had
nowhere to put the two facts payroll actually needs: the day somebody
started, and where their salary goes.

**Three bank fields, not one.** A transfer needs the bank, the number, and
the name the account is held under — and that last one is regularly not
spelled the way the employee's own record spells it. A mismatch is what
bounces the payment, so it is its own field rather than an assumption.

**HR edits the employment record and nothing else.** Not the role, which is
the security tier; not the pages, the password, or the login address; not
whether the account is active. Phone and contact email are absent for a
different reason — HR is not allowed to *read* those, so being able to write
them would be typing blind into a field they cannot see.

**And a bank change is written down.** Where the salary goes is
money-routing data: the audit log records who changed whose account, from
what to what.
"""
import asyncio, os, sys, uuid
from datetime import date
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
                          base_url="http://t/api/v1", timeout=180)
    tag = uuid.uuid4().hex[:5]

    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    hr = await login("hr@demo.local")
    s1 = await login("sales1@demo.local")
    fin = await login("finance@demo.local")

    emp = J(await c.post("/employees", headers=d, json={
        "full_name": f"Pegawai {tag}", "intended_role": "sales"}))
    who = J(await c.post("/users", headers=d, json={
        "email": f"pegawai{tag}@demo.local", "full_name": f"Pegawai {tag}",
        "role": "sales", "employee_id": emp["id"], "password": "test-pass-123"}))
    uid = who["id"]
    check("a person exists to keep a record for", bool(uid), str(who)[:150])
    them = await login(f"pegawai{tag}@demo.local")

    # ══ the record has somewhere to put these facts ══════════════════════════
    print("\n── the employment record ──")
    started = date(2024, 3, 18).isoformat()
    body = {"join_date": started, "bank_name": "BCA",
            "bank_account_no": f"1234{tag}",
            "bank_account_name": f"PEGAWAI {tag.upper()}"}
    r = await c.patch(f"/users/{uid}", headers=hr, json=body)
    check("HR can fill it in — the whole point of the page being theirs",
          r.status_code == 200, f"{r.status_code} {J(r)}"[:200])
    row = J(await c.get(f"/users/{uid}", headers=hr))
    check("...the day they started is on the record",
          row.get("join_date") == started, str(row.get("join_date")))
    check("...the bank", row.get("bank_name") == "BCA", str(row.get("bank_name")))
    check("...the account number",
          row.get("bank_account_no") == f"1234{tag}", str(row.get("bank_account_no")))
    check("...and the name the account is held under, separately",
          row.get("bank_account_name") == f"PEGAWAI {tag.upper()}",
          str(row.get("bank_account_name")))

    r = await c.patch(f"/users/{uid}", headers=hr,
                      json={"full_name": f"Pegawai {tag} Revisi"})
    check("HR can correct a misspelled name without asking the director",
          r.status_code == 200, f"{r.status_code} {J(r)}"[:170])
    check("...and it takes",
          J(await c.get(f"/users/{uid}", headers=hr))["full_name"]
          == f"Pegawai {tag} Revisi", "unchanged")

    print("\n── it shows on the directory too ──")
    listing = J(await c.get("/users", headers=hr))
    mine = next((x for x in listing if x["id"] == uid), None)
    check("the person is in HR's list", mine is not None, "missing")
    check("...carrying the start date", mine and mine.get("join_date") == started,
          str(mine and mine.get("join_date")))
    check("...and the bank details, which is HR's job",
          mine and mine.get("bank_account_no") == f"1234{tag}",
          str(mine and mine.get("bank_account_no")))
    check("...while email and phone stay hidden from HR, as before",
          mine and mine.get("email") == "(hidden)" and mine.get("phone") is None,
          str(mine)[:200])

    # ══ and nothing beyond it ════════════════════════════════════════════════
    print("\n── what stays the director's ──")
    for field, value, why in (
        ("role", "director", "the security tier"),
        ("is_active", False, "switching an account off"),
        ("password", "hunter2xyz", "somebody's password"),
        ("pages", ["/finance"], "which pages they see"),
        ("contact_email", "x@y.com", "an address HR cannot even read"),
    ):
        r = await c.patch(f"/users/{uid}", headers=hr, json={field: value})
        check(f"HR cannot change {why}", r.status_code == 403,
              f"{r.status_code} {str(J(r))[:130]}")
    check("...and the refusal says who can",
          "director" in str(J(await c.patch(f"/users/{uid}", headers=hr,
                                            json={"role": "admin"}))).lower(),
          "no explanation")
    after = J(await c.get(f"/users/{uid}", headers=d))
    check("...none of which took effect",
          after["role"] == "sales" and after["is_active"] is True
          and after.get("contact_email") is None, str(after)[:220])
    r = await c.post("/auth/login", json={"email": f"pegawai{tag}@demo.local",
                                          "password": "test-pass-123"})
    check("...the password in particular still being theirs",
          r.status_code == 200, str(r.status_code))

    print("\n── a mixed patch is refused whole, not half-applied ──")
    r = await c.patch(f"/users/{uid}", headers=hr,
                      json={"bank_name": "Mandiri", "role": "director"})
    check("sneaking a role change in beside a bank change is refused",
          r.status_code == 403, f"{r.status_code} {str(J(r))[:130]}")
    now = J(await c.get(f"/users/{uid}", headers=d))
    check("...and the bank change did not slip through with it",
          now["bank_name"] == "BCA" and now["role"] == "sales",
          f"{now.get('bank_name')} / {now.get('role')}")

    # ══ who else ═════════════════════════════════════════════════════════════
    print("\n── everybody else ──")
    r = await c.patch(f"/users/{uid}", headers=d,
                      json={"bank_name": "Mandiri", "role": "sales"})
    check("the director can still change anything", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:150])
    for label, hdr in (("sales", s1), ("finance", fin), ("the person themselves", them)):
        r = await c.patch(f"/users/{uid}", headers=hdr, json={"bank_name": "BNI"})
        check(f"{label} cannot edit an employment record",
              r.status_code in (401, 403), str(r.status_code))
    r = await c.get(f"/users/{uid}", headers=them)
    check("...though people can read their own record",
          r.status_code == 200 and J(r).get("bank_name") == "Mandiri",
          f"{r.status_code} {str(J(r))[:130]}")
    r = await c.get(f"/users/{uid}", headers=s1)
    check("...and a colleague cannot read somebody else's bank account",
          r.status_code in (401, 403), str(r.status_code))
    r = await c.get("/users", headers=s1)
    check("...nor the directory that carries them",
          r.status_code in (401, 403), str(r.status_code))

    # ══ money-routing changes are written down ═══════════════════════════════
    print("\n── the audit trail ──")
    await c.patch(f"/users/{uid}", headers=hr, json={"bank_account_no": "999000111"})
    logs = J(await c.get("/audit", headers=d, params={"entity": "employee", "limit": 50}))
    entries = logs.get("items", logs) if isinstance(logs, dict) else logs
    hits = [x for x in entries if str(x.get("entity_id")) == uid]
    check("a bank change is recorded", len(hits) >= 1, str(entries)[:220])
    last = hits[0] if hits else {}
    check("...saying what it became", "999000111" in str(last.get("after")),
          str(last.get("after"))[:200])
    check("...and what it was", f"1234{tag}" in str(last.get("before")),
          str(last.get("before"))[:200])

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)


asyncio.run(main())

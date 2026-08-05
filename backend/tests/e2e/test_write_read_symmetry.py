"""If you may write it, you may read it back.

The reported bug was "sales uploads a file and it never shows up". The cause
was an asymmetry: `/attachments` gated *reading* by owner type and role but
gated *writing* for external portal accounts only, so internal staff could
upload anywhere. That produced two failures from one hole —

  the visible one   upload a customer file, get 403 listing it, conclude the
                    upload failed, upload it again
  the quiet one     sales, purchasing and admin could write into an EMPLOYEE
                    record (KTP, employment contract, NPWP, BPJS), which only
                    HR, finance and management may read

— so this driver checks the *property* rather than the two known cases. It
walks every (role × owner type) pair through the real API and asserts nobody
can write where they cannot read, and nobody can write to a record the read
rule says isn't theirs. A new owner type added without a matching audience
entry fails here rather than in production.

The same property is asserted for the other write-then-read surfaces —
discussions and chat — which get it right by construction: both call one
access check for reading and posting alike. Cheap to verify, and it pins the
design so a future "just let them post" doesn't quietly split them.
"""
import asyncio, io, os, sys, uuid
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123",
    STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import httpx, logging; logging.disable(logging.INFO)
PASS, FAIL = [], []
def check(n,c,d=""):
    (PASS if c else FAIL).append(n); print(("  PASS " if c else "  FAIL ")+n+(f"  [{d}]" if d and not c else ""))
def J(r):
    try: return r.json()
    except Exception: return {"_": r.text[:160]}


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    from app.api.v1.endpoints.attachments import _attachment_visible_to
    from app.core.permissions import Role
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=90)

    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    tag = uuid.uuid4().hex[:5]
    d = await login("director@demo.local")
    ROLES = {}
    for role, email in [("sales", "sales1@demo.local"), ("purchasing", "purchasing@demo.local"),
                        ("admin", "admin@demo.local"), ("finance", "finance@demo.local"),
                        ("hr", "hr@demo.local"), ("manager", "manager@demo.local"),
                        ("director", "director@demo.local")]:
        ROLES[role] = await login(email)
    s1 = ROLES["sales"]

    # ── one real row of as many owner types as the flow can reach ────────────
    ids = {}
    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Simetri {tag}", "industry": "mining"}))["id"]
    ids["customer"] = cust
    ct = J(await c.post(f"/customers/{cust}/contacts", headers=s1,
                        json={"name": f"Pic {tag}", "position": "Buyer"}))
    if ct.get("id"):
        ids["customer_contact"] = ct["id"]

    pr = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [{"description": f"Gearbox {tag}", "qty": 1, "uom": "pcs"}]}))["id"]
    ids["price_request"] = pr
    await c.post(f"/price-requests/{pr}/submit", headers=s1)
    await c.post(f"/price-requests/{pr}/price", headers=ROLES["purchasing"],
                 json={"items": [{"line_no": 1, "cost_price": 5_000_000, "basis": "unit"}]})
    await c.post(f"/price-requests/{pr}/approve", headers=d,
                 json={"items": [{"line_no": 1, "sell_price": 9_000_000, "basis": "unit"}]})
    quo = J(await c.post(f"/quotations/from-price-request/{pr}", headers=s1))["id"]
    ids["quotation"] = quo
    await c.post(f"/quotations/{quo}/submit", headers=d)
    await c.post(f"/quotations/{quo}/won", headers=d)
    po = J(await c.post("/customer-pos", headers=s1, json={
        "customer_id": cust, "quotation_id": quo, "number": f"PO-SYM-{tag}",
        "po_date": "2026-08-05",
        "items": [{"description": f"Gearbox {tag}", "qty": 1, "uom": "pcs",
                   "unit_price": 9_000_000}], "is_downpayment": False}))
    po_id = po.get("id")
    if po_id:
        ids["customer_po"] = po_id
        ap = J(await c.post(f"/customer-pos/{po_id}/approve", headers=d, json={}))
        if ap.get("project_id"):
            ids["project"] = ap["project_id"]

    users = J(await c.get("/users", headers=d))
    rows = users.get("data") if isinstance(users, dict) else users
    if isinstance(rows, list) and rows:
        ids["employee"] = rows[0]["id"]
    log = J(await c.put("/attendance/daily-log", headers=s1,
                        json={"date": "2026-08-05", "body": f"sym {tag}", "links": []}))
    if log.get("id"):
        ids["daily_log"] = log["id"]
    q = J(await c.get("/approvals", headers=d))
    if isinstance(q, list) and q:
        ids["approval_request"] = q[0]["id"]

    check("the audit has enough owner types to be meaningful", len(ids) >= 7, str(sorted(ids)))
    check("...including the sensitive ones", "employee" in ids and "customer" in ids,
          str(sorted(ids)))

    # ── the property ─────────────────────────────────────────────────────────
    write_only, ungated = [], []
    for owner, oid in ids.items():
        for role, hdr in ROLES.items():
            up = await c.post("/attachments", headers=hdr,
                              files={"file": (f"probe-{tag}.txt", io.BytesIO(b"p"), "text/plain")},
                              data={"owner_type": owner, "owner_id": str(oid)})
            wrote = up.status_code in (200, 201)
            ls = await c.get("/attachments", headers=hdr,
                             params={"owner_type": owner, "owner_id": str(oid)})
            if wrote and ls.status_code != 200:
                write_only.append(f"{role}->{owner} (read {ls.status_code})")
            if wrote and not _attachment_visible_to(owner, Role(role)):
                ungated.append(f"{role}->{owner}")
            if wrote and J(up).get("id"):
                await c.delete(f"/attachments/{J(up)['id']}", headers=d)

    check("nobody can upload a file they then cannot list",
          not write_only, "; ".join(write_only))
    check("nobody can attach to a record the read rule says isn't theirs",
          not ungated, "; ".join(ungated))

    # The gate has to actually be doing something — if every upload were
    # refused the two checks above would pass vacuously.
    r = await c.post("/attachments", headers=s1,
                     files={"file": (f"real-{tag}.txt", io.BytesIO(b"x"), "text/plain")},
                     data={"owner_type": "customer", "owner_id": str(cust)})
    check("...and a legitimate upload still goes through",
          r.status_code in (200, 201), J(r))

    # The specific hole worth naming: personnel files.
    if ids.get("employee"):
        for role in ("sales", "purchasing", "admin"):
            r = await c.post("/attachments", headers=ROLES[role],
                             files={"file": ("hr.txt", io.BytesIO(b"x"), "text/plain")},
                             data={"owner_type": "employee", "owner_id": str(ids["employee"])})
            check(f"{role} cannot write into an employee's personnel file",
                  r.status_code == 403, str(r.status_code))
        r = await c.post("/attachments", headers=ROLES["hr"],
                         files={"file": ("ktp.txt", io.BytesIO(b"x"), "text/plain")},
                         data={"owner_type": "employee", "owner_id": str(ids["employee"])})
        check("...but HR still can", r.status_code in (200, 201), J(r))
        if J(r).get("id"):
            await c.delete(f"/attachments/{J(r)['id']}", headers=d)

    # ── the same property on discussions ─────────────────────────────────────
    bad = []
    for owner in ("customer", "price_request", "quotation", "customer_po", "project"):
        oid = ids.get(owner)
        if not oid:
            continue
        for role, hdr in ROLES.items():
            w = await c.post("/comments", headers=hdr, json={
                "owner_type": owner, "owner_id": str(oid), "body": f"probe {tag}"})
            r = await c.get("/comments", headers=hdr,
                            params={"owner_type": owner, "owner_id": str(oid)})
            if w.status_code in (200, 201) and r.status_code != 200:
                bad.append(f"{role}->{owner} (read {r.status_code})")
    check("nobody can post a comment on a thread they cannot read",
          not bad, "; ".join(bad))

    # ── and on chat ──────────────────────────────────────────────────────────
    ch = J(await c.post("/chat/channels", headers=d,
                        json={"title": f"Sym {tag}", "member_ids": []}))
    cid = ch.get("id")
    bad2 = []
    if cid:
        for role, hdr in ROLES.items():
            if role == "director":
                continue
            w = await c.post(f"/chat/channels/{cid}/messages", headers=hdr,
                             json={"body": f"probe {tag}"})
            r = await c.get(f"/chat/channels/{cid}/messages", headers=hdr)
            if w.status_code in (200, 201) and r.status_code != 200:
                bad2.append(f"{role} (read {r.status_code})")
    check("nobody can post into a chat channel they cannot read",
          not bad2, "; ".join(bad2))

    # Leave the queue clean — e2e_dp_flow.py asserts no customer_po request
    # is left pending, and this driver files one to build its fixtures.
    if po_id:
        await c.post(f"/customer-pos/{po_id}/reject", headers=d,
                     json={"notes": "test fixture"})

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        sys.exit(1)


asyncio.run(main())

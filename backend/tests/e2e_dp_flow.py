"""End-to-end test of the DP customer-PO workflow against a scratch Postgres.

HOW TO RUN (needs a local Postgres; never point this at production):
  1. initdb + start a scratch PG, e.g. on port 55432, create db `transmisi_test`
  2. cd backend && python tests/e2e_dp_flow.py
  The script sets its own env (DATABASE_URL/APP_ENV/JWT_SECRET), creates the
  role accounts + one customer fixture, and drives the API in-process.

Drives the real ASGI app with per-role authenticated clients:
  sales files DP PO -> finance approves -> finance issues DP invoice (no
  project yet) -> finance approves invoice w/ faktur pajak -> sales confirms
  deposit -> project spawns + invoice re-linked. Plus reject path, the
  /approvals bypass guard, and the regular (non-DP) PO path.
"""
import asyncio
import os
import sys

os.environ["DATABASE_URL"] = "postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test"
os.environ["APP_ENV"] = "dev"
os.environ["DEMO_SEED_PASSWORD"] = "test-pass-123"
os.environ["STORAGE_LOCAL_DIR"] = "/tmp/storage_test"
os.environ["JWT_SECRET"] = "e2e-test-secret"

sys.path.insert(0, "/home/user/Gay-boy-/backend")

import httpx  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = ""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))


async def main():
    from app.scripts.seed import ensure_schema
    await ensure_schema()

    # Create every role account + the customer fixture directly (ensure_schema
    # doesn't run the demo-user seed).
    from app.core.db import SessionLocal
    from app.core.security import hash_password
    from app.models.crm import Customer
    from app.models.user import User
    from sqlalchemy import select
    async with SessionLocal() as db:
        users = {}
        for email, name, role in [
            ("director@demo.local", "Director Demo", "director"),
            ("manager@demo.local", "Manager Demo", "manager"),
            ("sales1@demo.local", "Sales One", "sales"),
            ("finance@demo.local", "Finance Demo", "finance"),
            ("purchasing@demo.local", "Purchasing Demo", "purchasing"),
        ]:
            u = await db.scalar(select(User).where(User.email == email))
            if not u:
                u = User(email=email, full_name=name, role=role,
                         password_hash=hash_password("test-pass-123"),
                         is_active=True)
                db.add(u)
                await db.flush()
            users[role] = u
        if not await db.scalar(select(Customer).where(
                Customer.company_name == "PT Bara Kalsel")):
            db.add(Customer(company_name="PT Bara Kalsel", industry="mining",
                            pic_name="Andi", whatsapp="+628123456789",
                            sales_pic_id=users["sales"].id,
                            stage="negotiation",
                            payment_terms={"type": "termin"}))
        await db.commit()

    from app.main import app
    transport = httpx.ASGITransport(app=app)

    async def client_for(email: str) -> httpx.AsyncClient:
        c = httpx.AsyncClient(transport=transport, base_url="http://test/api/v1", timeout=30)
        r = await c.post("/auth/login", json={"email": email, "password": "test-pass-123"})
        assert r.status_code == 200, f"login {email}: {r.status_code} {r.text}"
        c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        return c

    director = await client_for("director@demo.local")
    sales = await client_for("sales1@demo.local")
    finance = await client_for("finance@demo.local")
    manager = await client_for("manager@demo.local")

    # ── Fixture: customer (seeded, negotiation, sales1) + a Won quotation ──
    # Search rather than page. The other drivers each leave a handful of
    # customers behind, so the seeded one drops off any fixed-size first page
    # once the suite has grown — and this driver runs last.
    r = await director.get("/customers", params={"q": "PT Bara Kalsel", "page_size": 50})
    body = r.json()
    customers = body["data"] if isinstance(body, dict) and "data" in body else body
    cust = next((c for c in customers if c["company_name"] == "PT Bara Kalsel"), None)
    assert cust, f"seeded customer 'PT Bara Kalsel' not found in {len(customers)} result(s)"
    cust_id = cust["id"]

    r = await director.post("/quotations", json={
        "customer_id": cust_id,
        "items": [{"line_no": 1, "source": "custom", "description": "Test gearbox",
                   "qty": 2, "uom": "pcs", "unit_price": 5_000_000, "cost_estimate": 0,
                   "spec": {}}],
        "discount_pct": 0, "tax_pct": 11,
    })
    check("director direct-creates quotation", r.status_code == 201, r.text[:200])
    quote = r.json()
    r = await director.post(f"/quotations/{quote['id']}/submit")
    r = await director.post(f"/quotations/{quote['id']}/approve", json={"notes": ""})
    # Won rests on the customer's order, so their PO is filed first. This one
    # is the plain (non-DP) PO; the DP POs below are the flow under test.
    r = await sales.post("/customer-pos", json={
        "customer_id": cust_id, "quotation_id": quote["id"], "number": "PO-WIN-001",
        "items": [{"description": "Test gearbox", "qty": 2, "unit_price": 5_000_000}],
        "is_downpayment": False,
    })
    check("customer PO filed before the win", r.status_code == 201, r.text[:200])
    win_po = r.json()
    r = await director.post(f"/quotations/{quote['id']}/won")
    won_status = r.json().get("status") if r.status_code == 200 else None
    check("quotation reaches won", won_status == "won", f"{r.status_code} {r.text[:200]}")
    # ...and it is approved here so the global "nothing left pending" sweep at
    # the end of this driver stays true.
    r = await director.post(f"/customer-pos/{win_po['id']}/approve", json={"notes": ""})
    check("...and that PO is decided rather than left in the queue",
          r.status_code == 200, f"{r.status_code} {r.text[:160]}")

    # sales blocked from direct quotation create (regression check)
    r = await sales.post("/quotations", json={
        "customer_id": cust_id,
        "items": [{"line_no": 1, "source": "custom", "description": "x", "qty": 1,
                   "uom": "pcs", "unit_price": 1, "cost_estimate": 0, "spec": {}}],
    })
    check("sales blocked from direct quotation create (409)", r.status_code == 409, str(r.status_code))

    async def file_po(number: str, dp: bool):
        r = await sales.post("/customer-pos", json={
            "customer_id": cust_id, "quotation_id": quote["id"], "number": number,
            "items": [{"description": "Test gearbox", "qty": 2, "unit_price": 5_000_000}],
            "is_downpayment": dp,
        })
        assert r.status_code == 201, f"file PO {number}: {r.status_code} {r.text[:300]}"
        return r.json()

    # ══ 1. Happy-path DP flow ══════════════════════════════════════════
    po1 = await file_po("DP-001", dp=True)
    check("DP PO starts at pending_finance", po1["status"] == "pending_finance", po1["status"])

    r = await finance.get("/customer-pos")
    check("finance can list customer POs", r.status_code == 200, str(r.status_code))
    r = await finance.get(f"/customer-pos/{po1['id']}")
    check("finance can open PO detail", r.status_code == 200, str(r.status_code))

    r = await finance.get("/notifications")
    has_dp_fin = any(i["id"] == f"dp-finance:{po1['id']}" for i in r.json()["items"])
    check("finance bell shows 'DP PO awaiting finance'", has_dp_fin)

    r = await finance.post(f"/customer-pos/{po1['id']}/dp/finance-approve", json={"notes": "ok"})
    check("finance approves DP -> pending_sales_confirm",
          r.status_code == 200 and r.json()["status"] == "pending_sales_confirm",
          f"{r.status_code} {r.text[:200]}")

    r = await director.get("/approvals")
    pend = [a for a in r.json() if a.get("target_type") == "customer_po"
            and a.get("target_id") == po1["id"]]
    check("approval request closed after finance approve", len(pend) == 0, str(len(pend)))

    # DP invoice against the PO (no project exists)
    r = await finance.post(f"/customer-pos/{po1['id']}/dp-invoice", data={"amount": "3000000"})
    check("finance issues DP invoice against the PO", r.status_code == 201, r.text[:200])
    dp_inv = r.json()

    r = await finance.get("/finance/invoices/pending")
    in_queue = any(i["id"] == dp_inv["id"] for i in r.json())
    check("DP invoice appears in finance pending queue (no project)", in_queue)

    r = await finance.post(f"/finance/invoices/{dp_inv['id']}/approve",
                           data={"faktur_pajak_no": "010.000-24.00000001"})
    check("finance approves DP invoice with faktur pajak", r.status_code == 200, r.text[:200])

    r = await sales.get("/notifications")
    has_dp_sales = any(i["id"] == f"dp-sales:{po1['id']}" for i in r.json()["items"])
    check("sales bell shows 'Confirm DP received'", has_dp_sales)

    r = await sales.post(f"/customer-pos/{po1['id']}/dp/sales-confirm", json={"notes": "trf rk123"})
    body = r.json()
    check("sales confirms deposit -> PO approved + project spawned",
          r.status_code == 200 and body["status"] == "approved" and body.get("project_id"),
          f"{r.status_code} {r.text[:200]}")
    project1_id = body.get("project_id")

    r = await sales.get(f"/customer-pos/{po1['id']}")
    dp_invs = r.json().get("dp_invoices") or []
    check("PO detail lists the DP invoice", any(i["id"] == dp_inv["id"] for i in dp_invs))

    r = await director.get(f"/operation/projects/{project1_id}/full")
    proj_invs = r.json().get("invoices") or []
    check("DP invoice re-linked to spawned project",
          any(i["id"] == dp_inv["id"] for i in proj_invs),
          f"invoices on project: {[i.get('number') for i in proj_invs]}")

    # ══ 2. Reject path ═════════════════════════════════════════════════
    po2 = await file_po("DP-002", dp=True)
    r = await finance.post(f"/customer-pos/{po2['id']}/dp/finance-reject", json={"notes": ""})
    check("dp reject without reason -> 400", r.status_code == 400, str(r.status_code))
    r = await finance.post(f"/customer-pos/{po2['id']}/dp/finance-reject",
                           json={"notes": "PO number typo"})
    check("finance rejects DP PO with reason",
          r.status_code == 200 and r.json()["status"] == "rejected",
          f"{r.status_code} {r.text[:200]}")
    r = await director.get("/approvals")
    pend = [a for a in r.json() if a.get("target_id") == po2["id"]]
    check("approval request closed after reject", len(pend) == 0)

    # ══ 3. /approvals bypass guard ═════════════════════════════════════
    po3 = await file_po("DP-003", dp=True)
    r = await director.get("/approvals")
    req3 = next((a for a in r.json() if a.get("target_id") == po3["id"]), None)
    check("DP request visible to director in /approvals", req3 is not None)
    if req3:
        r = await manager.post(f"/approvals/{req3['id']}/approve", json={"notes": ""})
        check("manager blocked from deciding FINANCE-targeted request (403)",
              r.status_code == 403, f"{r.status_code} {r.text[:150]}")
        r = await director.post(f"/approvals/{req3['id']}/approve", json={"notes": ""})
        po3_now = (await director.get(f"/customer-pos/{po3['id']}")).json()
        check("director /approvals approve advances DP to pending_sales_confirm (NO project)",
              po3_now["status"] == "pending_sales_confirm" and not po3_now.get("project_id"),
              f"status={po3_now['status']} project={po3_now.get('project_id')}")
        r = await sales.post(f"/customer-pos/{po3['id']}/dp/sales-confirm", json={"notes": ""})
        check("sales confirm after bypass-guard path spawns exactly one project",
              r.status_code == 200 and r.json().get("project_id"),
              f"{r.status_code} {r.text[:150]}")

    # ══ 4. Regular (non-DP) PO regression ══════════════════════════════
    po4 = await file_po("REG-004", dp=False)
    check("regular PO starts at pending_approval", po4["status"] == "pending_approval", po4["status"])
    r = await director.post(f"/customer-pos/{po4['id']}/approve", json={"notes": ""})
    body = r.json()
    check("director approves regular PO -> project spawned",
          r.status_code == 200 and body["status"] == "approved" and body.get("project_id"),
          f"{r.status_code} {r.text[:200]}")

    # duplicate-project guard: po4's own request must be closed by the
    # approval, so a second decision can't fire and spawn a second project.
    # Scoped to po4 — every other driver's half-finished PO sits in this same
    # queue, and sweeping the lot made this pass or fail on their business.
    r = await director.get("/approvals")
    check("po4's approval request is closed", not any(
        a.get("target_type") == "customer_po" and a.get("target_id") == po4["id"]
        for a in r.json()))

    for c in (director, sales, finance, manager):
        await c.aclose()

    print(f"\n{'='*50}\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", *FAIL, sep="\n  - ")
        sys.exit(1)


asyncio.run(main())

"""An approved customer PO starts the job, not only a Won quotation.

The job used to start at exactly one moment: marking the quotation Won. The
customer PO's approval attached to whatever Won had already made, and made
nothing itself. The reasoning was that a signature on the paperwork is not the
same as the work beginning — which is true, and produced an approved order
sitting next to a dash where its project number belonged, with the step that
would fix it on a different page and nothing pointing at it.

So there are two doors now. Won still does everything it did; approval opens
the same room. Whichever is reached first makes the job and the other attaches
to it, which is the property that actually has to hold: **exactly one project**,
no matter the order or the count. Approve then win, win then approve, two POs
against one quotation, the same PO approved twice — all one job.

Two things stay exactly as they were, and both are checked here because
"approval starts the work" is the kind of change that quietly eats its
exceptions:

* **A down-payment order still waits for the money.** Not starting before the
  deposit lands is the entire point of a deposit, and an approval that jumped
  that gate would be worse than the bug this fixes.
* **Approval does not post revenue.** Won moves the sales figures; a PO can be
  approved for part of a quotation, so inferring the full quoted total from a
  signature would overstate what was sold. Starting work early costs nothing if
  the deal turns. Posting revenue early is a correction.

And the escape hatch: a director can start one by hand, for the orders already
sitting approved from before any of this was true. Director only — it is the
one door with no evidence behind it — and it still refuses to make a second
job.
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
    s1 = await login("sales1@demo.local")
    pur = await login("purchasing@demo.local")
    fin = await login("finance@demo.local")

    n = [0]

    async def approved_quote(label):
        """A customer with an approved quotation ready to be ordered against."""
        n[0] += 1
        cust = J(await c.post("/customers", headers=s1, json={
            "company_name": f"PT {label} {TAG}-{n[0]}", "industry": "mining"}))["id"]
        pr = J(await c.post("/price-requests", headers=s1, json={
            "customer_id": cust,
            "items": [{"description": f"Chain {label} {TAG}-{n[0]}", "qty": 10,
                       "uom": "pcs", "category": "roller_chain"}]}))
        await c.post(f"/price-requests/{pr['id']}/submit", headers=s1)
        await c.post(f"/price-requests/{pr['id']}/price", headers=pur,
                     json={"items": [{"line_no": 1, "cost_price": 300_000, "basis": "unit"}]})
        await c.post(f"/price-requests/{pr['id']}/approve", headers=d,
                     json={"items": [{"line_no": 1, "sell_price": 500_000, "basis": "unit"}]})
        q = J(await c.post(f"/quotations/from-price-request/{pr['id']}", headers=s1))
        await c.post(f"/quotations/{q['id']}/submit", headers=s1)
        await c.post(f"/quotations/{q['id']}/approve", headers=d, json={"decision": "approve"})
        return cust, q

    async def file_po(cust, q, *, dp=False, number=None):
        return J(await c.post("/customer-pos", headers=s1, json={
            "customer_id": cust, "quotation_id": q["id"],
            "number": number or f"PO-{TAG}-{n[0]}", "po_date": "2026-09-08",
            "is_downpayment": dp,
            "items": [{"description": f"Chain {TAG}", "qty": 10, "unit_price": 500_000}]}))

    async def po_now(po_id, headers=None):
        return J(await c.get(f"/customer-pos/{po_id}", headers=headers or d))

    # ══ the door that was missing ════════════════════════════════════════
    print("\n── an order is approved, and the work has somewhere to go ──")
    cust, q = await approved_quote("Pintu")
    po = await file_po(cust, q)
    check("the order is filed, with no job yet", po.get("project_id") is None,
          str(po.get("project_id")))

    r = await c.post(f"/customer-pos/{po['id']}/approve", headers=d,
                     json={"decision": "approve"})
    check("the director approves it", r.status_code == 200, f"{r.status_code} {why(r)}")
    after = await po_now(po["id"])
    check("...and the project exists, without anyone marking the deal Won",
          after.get("project_id") is not None, str(after.get("project_id")))
    check("...carrying a real code", bool(after.get("project_code")),
          str(after.get("project_code")))

    proj = J(await c.get(f"/operation/projects/{after['project_id']}", headers=d))
    check("...linked back to the quotation it came from",
          (proj.get("quotation") or {}).get("id") == q["id"], str(proj.get("quotation")))
    check("...and carrying the order's paperwork",
          proj.get("po_number") == po["number"], str(proj.get("po_number")))

    # ══ what approval must NOT do ════════════════════════════════════════
    print("\n── but the deal is not won by approving the paperwork ──")
    qs = J(await c.get(f"/quotations/{q['id']}", headers=d))
    check("the quotation is still 'approved', not 'won'", qs["status"] == "approved",
          qs["status"])
    summary = J(await c.get(f"/customers/{cust}/summary", headers=d))
    check("...so no revenue has been posted against it",
          float(summary.get("won_revenue") or 0) == 0, str(summary.get("won_revenue")))

    print("\n── and winning it afterwards lands on the same job ──")
    r = await c.post(f"/quotations/{q['id']}/won", headers=d)
    check("the deal is marked Won", r.status_code == 200, f"{r.status_code} {why(r)}")
    again = await po_now(po["id"])
    check("...on the project that already existed — not a second one",
          again.get("project_id") == after.get("project_id"),
          f"{after.get('project_id')} -> {again.get('project_id')}")

    # ══ the other order, the other way round ═════════════════════════════
    print("\n── won first, then approved: still one job ──")
    cust2, q2 = await approved_quote("Balik")
    po2 = await file_po(cust2, q2)
    await c.post(f"/quotations/{q2['id']}/won", headers=d)
    won_proj = (await po_now(po2["id"])).get("project_id")
    check("Won made the job while the order sat pending", won_proj is not None,
          str(won_proj))
    await c.post(f"/customer-pos/{po2['id']}/approve", headers=d, json={"decision": "approve"})
    check("...and approving the order attaches to it",
          (await po_now(po2["id"])).get("project_id") == won_proj,
          str((await po_now(po2['id'])).get("project_id")))

    print("\n── a second order against the same quotation joins the job ──")
    po2b = await file_po(cust2, q2, number=f"PO-{TAG}-{n[0]}-B")
    await c.post(f"/customer-pos/{po2b['id']}/approve", headers=d, json={"decision": "approve"})
    check("the addition does not mint a second project",
          (await po_now(po2b["id"])).get("project_id") == won_proj,
          str((await po_now(po2b['id'])).get("project_id")))

    print("\n── and approving one twice changes nothing ──")
    r = await c.post(f"/customer-pos/{po['id']}/approve", headers=d, json={"decision": "approve"})
    check("a re-approval is refused or harmless", r.status_code in (200, 400, 409),
          str(r.status_code))
    check("...and the job is still the one job",
          (await po_now(po["id"])).get("project_id") == after.get("project_id"),
          str((await po_now(po['id'])).get("project_id")))

    # ══ the exception that must survive ══════════════════════════════════
    print("\n── a deposit order still waits for the deposit ──")
    cust3, q3 = await approved_quote("Muka")
    dp = await file_po(cust3, q3, dp=True)
    check("a DP order goes to finance, not straight to approved",
          dp["status"] == "pending_finance", dp["status"])
    r = await c.post(f"/customer-pos/{dp['id']}/dp/finance-approve", headers=fin,
                     json={"notes": "ok"})
    check("finance approves it", r.status_code == 200, f"{r.status_code} {why(r)}")
    mid = await po_now(dp["id"])
    check("...and there is STILL no project — that is what a deposit means",
          mid.get("project_id") is None, str(mid.get("project_id")))
    check("...the order is waiting on the money",
          mid["status"] == "pending_payment_confirm", mid["status"])

    # ══ the director's escape hatch ══════════════════════════════════════
    print("\n── and a director can start one by hand ──")
    cust4, q4 = await approved_quote("Tangan")
    po4 = await file_po(cust4, q4)
    # Put it in the state the old code left orders in: approved, no project.
    from app.core.db import SessionLocal
    from app.models.customer_po import CustomerPO as _CPO
    async with SessionLocal() as db:
        row = await db.get(_CPO, uuid.UUID(po4["id"]))
        row.status = "approved"
        row.project_id = None
        await db.commit()
    stranded = await po_now(po4["id"])
    check("an order stranded approved with no job", stranded["status"] == "approved"
          and stranded.get("project_id") is None, str(stranded.get("project_id")))

    r = await c.post(f"/customer-pos/{po4['id']}/create-project", headers=s1)
    check("sales may not do it", r.status_code == 403, str(r.status_code))
    r = await c.post(f"/customer-pos/{po4['id']}/create-project", headers=fin)
    check("nor finance", r.status_code == 403, str(r.status_code))

    r = await c.post(f"/customer-pos/{po4['id']}/create-project", headers=d)
    check("the director can", r.status_code == 200, f"{r.status_code} {why(r)}")
    made = J(r)
    check("...and the order now has its job", made.get("project_id") is not None,
          str(made.get("project_id")))
    check("...which is a real project", bool(made.get("project_code")),
          str(made.get("project_code")))

    print("\n── pressed twice, it does not make a second ──")
    r = await c.post(f"/customer-pos/{po4['id']}/create-project", headers=d)
    check("the second press is not an error", r.status_code == 200,
          f"{r.status_code} {why(r)}")
    check("...and hands back the same job",
          J(r).get("project_id") == made.get("project_id"),
          f"{made.get('project_id')} -> {J(r).get('project_id')}")

    print("\n── and it will not start a job on an order nobody agreed to ──")
    cust5, q5 = await approved_quote("Belum")
    po5 = await file_po(cust5, q5)
    check("that order is still pending", po5["status"] == "pending_approval",
          po5["status"])
    r = await c.post(f"/customer-pos/{po5['id']}/create-project", headers=d)
    check("the hatch refuses it", r.status_code == 400, str(r.status_code))
    check("...and says to approve it instead", "approve" in why(r), why(r)[:160])
    check("...leaving it without a project",
          (await po_now(po5["id"])).get("project_id") is None,
          str((await po_now(po5['id'])).get("project_id")))

    print("\n── a link that exists but was never joined is repaired, not doubled ──")
    async with SessionLocal() as db:
        row = await db.get(_CPO, uuid.UUID(po4["id"]))
        row.project_id = None            # the job exists; the PO forgot it
        await db.commit()
    r = await c.post(f"/customer-pos/{po4['id']}/create-project", headers=d)
    check("it re-links rather than minting a duplicate",
          r.status_code == 200 and J(r).get("project_id") == made.get("project_id"),
          f"{r.status_code} {J(r).get('project_id')}")

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)


asyncio.run(main())

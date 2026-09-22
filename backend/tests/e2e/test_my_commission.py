"""The rep's own commission page: what it shows, and what it refuses to show.

Until now a rep could not see their commission at all — the figures lived on
the employee page, which is the director's and HR's. This is the endpoint
behind their own page, and it has two jobs.

The first is to be the *same* answer as the claim endpoint. A page that offers
a Claim button on a job the server will refuse is worse than no page: the rep
files, gets a 409, and stops trusting the number. So `claimable` is derived
from the same collected figure the gate uses, and this pins that a job leaves
the list the instant the gate shuts — including when a payment is reversed
weeks later.

The second is that pay is private. A rep reads their own and nobody else's;
management can read anybody's, because somebody has to be able to answer "what
am I owed?" on a rep's behalf. A refused claim is not a dead end either: its
job comes straight back onto the claimable list, which is what makes "claim
again" the ordinary button rather than a second, special door.
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
    s1 = await login("sales1@demo.local")
    s2 = await login("sales2@demo.local")
    fin = await login("finance@demo.local")
    adm = await login("admin@demo.local")

    s1_id = J(await c.get("/auth/me", headers=s1)).get("id")
    s2_id = J(await c.get("/auth/me", headers=s2)).get("id")

    async def a_job(tag, *, pay=True, unit=1_000_000, qty=10, seller=None):
        """A project driven to a real invoice, optionally settled in full."""
        who = seller or s1
        cust = J(await c.post("/customers", headers=who, json={
            "company_name": f"PT Mine {tag}", "industry": "mining"}))["id"]
        pr = J(await c.post("/price-requests", headers=who, json={
            "customer_id": cust,
            "items": [{"description": f"SHACKLE {tag}", "qty": qty, "uom": "pcs"}]}))["id"]
        await c.post(f"/price-requests/{pr}/submit", headers=who)
        await c.post(f"/price-requests/{pr}/price", headers=d, json={
            "items": [{"line_no": 1, "cost_price": unit // 2, "basis": "unit"}]})
        await c.post(f"/price-requests/{pr}/approve", headers=d, json={
            "items": [{"line_no": 1, "sell_price": unit, "basis": "unit"}]})
        q = J(await c.post(f"/quotations/from-price-request/{pr}", headers=who))["id"]
        await c.post(f"/quotations/{q}/submit", headers=who)
        await c.post(f"/quotations/{q}/approve", headers=d, json={"notes": ""})
        cpo = J(await c.post("/customer-pos", headers=who, json={
            "customer_id": cust, "quotation_id": q, "number": f"PO-MINE-{tag}",
            "items": [{"description": f"SHACKLE {tag}", "qty": qty, "unit_price": unit}],
            "is_downpayment": False}))["id"]
        await c.post(f"/quotations/{q}/won", headers=d)
        proj = J(await c.post(f"/customer-pos/{cpo}/approve", headers=d,
                              json={"notes": ""}))["project_id"]
        await c.post(f"/operation/projects/{proj}/qc", headers=adm,
                     json={"decision": "pass"})
        await c.post(f"/operation/projects/{proj}/issue-invoice", headers=d,
                     data={"invoice_type": "single"})
        from app.core.db import SessionLocal
        from sqlalchemy import select as _sel
        from app.models.finance import Invoice as _Inv
        async with SessionLocal() as db:
            row = await db.scalar(_sel(_Inv).where(_Inv.project_id == proj)
                                  .order_by(_Inv.created_at.desc()))
            iid, total = str(row.id), float(row.total or 0)
        await c.post(f"/finance/invoices/{iid}/approve", headers=fin,
                     data={"faktur_pajak_no": f"FP-MINE-{tag}"})
        if pay:
            await c.post("/payments/manual", headers=fin, json={
                "invoice_id": iid, "amount": total, "method": "transfer",
                "reference": f"TRX-{tag}"})
        return proj, iid, total

    async def summary(hdr=s1, **params):
        return J(await c.get("/commissions/summary", headers=hdr, params=params))
    def claimable_ids(s):
        return {r["project_id"] for r in s.get("claimable", [])}
    def filed_id(s, claim_id):
        return next((x for x in s.get("filed", []) if x["id"] == claim_id), {})
    def filed_for(s, proj):
        return next((x for x in s.get("filed", []) if x["project_id"] == proj), {})
    def tot(s, key):
        return float((s.get("totals") or {}).get(key) or 0)

    # ══ the page a rep opens ══════════════════════════════════════════════
    print("\n── the rep reads their own page ──")
    r = await c.get("/commissions/summary", headers=s1)
    check("a sales rep can open their own commission summary",
          r.status_code == 200, f"{r.status_code} {why(r)}")
    s = J(r)
    check("...it is addressed to them", s.get("beneficiary", {}).get("id") == s1_id,
          str(s.get("beneficiary")))
    check("...and states the baseline rate rather than leaving the page to guess",
          float(s.get("rate_pct") or 0) == 2.0, str(s.get("rate_pct")))
    for key in ("claimable", "filed", "paid"):
        check(f"...it carries the '{key}' list", isinstance(s.get(key), list),
              str(type(s.get(key))))
    for key in ("claimable", "claimable_jobs", "pending", "approved", "paid"):
        check(f"...and a '{key}' total the strip can print",
              key in (s.get("totals") or {}), str(s.get("totals")))

    # ══ paid vs unpaid ════════════════════════════════════════════════════
    print("\n── only settled jobs are offered ──")
    unpaid, _, unpaid_total = await a_job(f"U{TAG}", pay=False)
    paid_job, paid_inv, paid_total = await a_job(f"P{TAG}")

    s = await summary()
    check("a job the customer has settled is offered to claim",
          paid_job in claimable_ids(s), str(claimable_ids(s))[:160])
    check("a job still owing money is NOT offered — it is absent, not greyed out",
          unpaid not in claimable_ids(s), str(claimable_ids(s))[:160])

    offer = next(r for r in s["claimable"] if r["project_id"] == paid_job)
    check("the offer names the job", bool(offer.get("project_code")), str(offer)[:160])
    check("...and the customer, because that is how a rep recognises it",
          bool(offer.get("customer_name")), str(offer)[:160])
    check("...and what the customer actually paid",
          abs(float(offer["collected"]) - paid_total) < 1,
          f"{offer['collected']} vs {paid_total}")
    check("...and the 2% that follows from it, so the button can say the figure",
          abs(float(offer["amount"]) - round(paid_total * 0.02, 2)) < 1,
          str(offer.get("amount")))
    check("the claimable total is the sum of what is on offer",
          abs(float(s["totals"]["claimable"])
              - round(sum(r["amount"] for r in s["claimable"]), 2)) < 1,
          str(s["totals"]["claimable"]))
    check("...and the job count matches the list",
          s["totals"]["claimable_jobs"] == len(s["claimable"]),
          f'{s["totals"]["claimable_jobs"]} vs {len(s["claimable"])}')

    # The page and the gate have to be the same answer, or the button lies.
    r = await c.post("/commissions", headers=s1, json={"project_id": unpaid})
    check("the server refuses the job the page did not offer",
          r.status_code == 409, f"{r.status_code} {why(r)}")

    # ══ claiming moves it along ═══════════════════════════════════════════
    print("\n── claiming from the page ──")
    was = await summary()
    before, was_pending = tot(was, "claimable"), tot(was, "pending")
    r = await c.post("/commissions", headers=s1,
                     json={"project_id": paid_job, "notes": f"page claim {TAG}"})
    check("the rep claims the job the page offered", r.status_code == 201,
          f"{r.status_code} {why(r)}")
    claim = J(r)

    s = await summary()
    check("...it leaves the claimable list at once",
          paid_job not in claimable_ids(s), str(claimable_ids(s))[:160])
    check("...and the claimable total drops by exactly its amount",
          abs((before - tot(s, "claimable")) - float(claim["amount"])) < 1,
          f'{before} -> {tot(s, "claimable")}')
    filed = filed_id(s, claim["id"])
    check("...it appears under the claims they have filed", bool(filed), str(filed)[:160])
    check("...marked as waiting on the director", filed.get("status") == "pending",
          str(filed.get("status")))
    check("...carrying the customer's name for the row",
          bool(filed.get("customer_name")), str(filed)[:160])
    check("...and counted into the 'with the director' figure",
          abs((tot(s, "pending") - was_pending) - float(claim["amount"])) < 1,
          f'{was_pending} -> {tot(s, "pending")}')
    check("nothing is double-counted: it is not in claimable and pending at once",
          paid_job not in claimable_ids(s) and bool(filed))

    # ══ pay is private ════════════════════════════════════════════════════
    print("\n── whose figures these are ──")
    r = await c.get("/commissions/summary", headers=s2, params={"user_id": s1_id})
    check("another rep cannot read this rep's commission",
          r.status_code == 403, f"{r.status_code} {why(r)}")
    r = await c.get("/commissions/summary", headers=d, params={"user_id": s1_id})
    check("the director can, because somebody has to answer for the payout",
          r.status_code == 200, f"{r.status_code} {why(r)}")
    check("...and gets that rep's figures, not their own",
          J(r).get("beneficiary", {}).get("id") == s1_id,
          str(J(r).get("beneficiary")))
    r = await c.get("/commissions/summary", headers=fin, params={"user_id": s1_id})
    check("finance can too — they are the ones who pay it out",
          r.status_code == 200, f"{r.status_code} {why(r)}")

    s2_view = await summary(s2)
    check("the other rep's own page holds none of this rep's jobs",
          paid_job not in claimable_ids(s2_view)
          and not filed_for(s2_view, paid_job),
          str(claimable_ids(s2_view))[:160])

    # ══ a refusal is not a dead end ═══════════════════════════════════════
    print("\n── refused, and put again ──")
    was_pending = tot(await summary(), "pending")
    r = await c.post(f"/commissions/{claim['id']}/reject", headers=d,
                     json={"notes": f"re-priced after delivery {TAG}"})
    check("the director refuses it with a reason", r.status_code == 200,
          f"{r.status_code} {why(r)}")

    s = await summary()
    filed = filed_id(s, claim["id"])
    check("the refusal shows on the rep's page", filed.get("status") == "rejected",
          str(filed.get("status")))
    check("...with the director's words, so nobody has to go and ask",
          TAG in (filed.get("decision_notes") or ""), str(filed.get("decision_notes")))
    check("...and who said it", bool(filed.get("decided_by_name")),
          str(filed.get("decided_by_name")))
    check("a refused claim stops counting towards what is owed",
          abs((was_pending - tot(s, "pending")) - float(claim["amount"])) < 1,
          f'{was_pending} -> {tot(s, "pending")}')
    check("...but stays on the page, so the rep can read why",
          bool(filed), str([x["status"] for x in s["filed"]]))
    check("...and the job comes BACK onto the claimable list, so 'claim again' "
          "is the ordinary button",
          paid_job in claimable_ids(s), str(claimable_ids(s))[:160])

    r = await c.post("/commissions", headers=s1, json={"project_id": paid_job})
    check("...and putting it again is accepted", r.status_code == 201,
          f"{r.status_code} {why(r)}")
    claim2 = J(r)

    # ══ agreed, then paid ═════════════════════════════════════════════════
    print("\n── agreed at a different rate, then paid ──")
    was = await summary()
    was_pending, was_approved, was_paid = (
        tot(was, "pending"), tot(was, "approved"), tot(was, "paid"))
    r = await c.post(f"/commissions/{claim2['id']}/approve", headers=d,
                     json={"rate_pct": 2.5, "notes": f"good margin {TAG}"})
    check("the director agrees it at 2.5% rather than the baseline",
          r.status_code == 200, f"{r.status_code} {why(r)}")
    agreed = J(r)

    s = await summary()
    filed = filed_id(s, claim2["id"])
    check("the rep's page shows the rate the director settled on, not the baseline",
          abs(float(filed.get("rate_pct") or 0) - 2.5) < 0.001, str(filed.get("rate_pct")))
    check("...and the amount that follows from it",
          abs(float(filed["amount"]) - round(float(filed["basis_amount"]) * 0.025, 2)) < 1,
          str(filed.get("amount")))
    check("...counted under 'agreed, in payroll' and not still 'with the director'",
          abs((tot(s, "approved") - was_approved) - float(agreed["amount"])) < 1
          and abs((was_pending - tot(s, "pending")) - float(claim2["amount"])) < 1,
          str(s["totals"]))
    check("...and it is still not in the paid figure, because it has not gone out",
          abs(tot(s, "paid") - was_paid) < 1, f'{was_paid} -> {tot(s, "paid")}')

    was_paid = tot(await summary(), "paid")
    r = await c.post(f"/commissions/{claim2['id']}/mark-paid", headers=fin, json={})
    check("finance marks it paid when it goes out with payroll",
          r.status_code == 200, f"{r.status_code} {why(r)}")

    s = await summary()
    check("it moves out of the filed list", not filed_id(s, claim2["id"]),
          str([x["status"] for x in s["filed"]]))
    paid_row = next((x for x in s["paid"] if x["id"] == claim2["id"]), {})
    check("...and into the payout history", bool(paid_row), str(s["paid"])[:160])
    check("...stamped with when it was paid", bool(paid_row.get("paid_at")),
          str(paid_row.get("paid_at")))
    check("...and counted in the paid total",
          abs((tot(s, "paid") - was_paid) - float(agreed["amount"])) < 1,
          f'{was_paid} -> {tot(s, "paid")}')
    check("the year it was paid is offered as a period to look at",
          any(isinstance(y, int) for y in (s.get("paid_years") or [])),
          str(s.get("paid_years")))

    # ══ the period filter ═════════════════════════════════════════════════
    print("\n── looking at another year ──")
    s_old = await summary(s1, year=2001)
    check("a year with no payouts shows none", len(s_old["paid"]) == 0,
          str(len(s_old["paid"])))
    check("...and a paid total of zero", tot(s_old, "paid") == 0,
          str(s_old["totals"]["paid"]))
    check("but claimable money is NOT filtered by year — it is owed today, "
          "whenever the job started",
          len(s_old["claimable"]) == len((await summary())["claimable"]),
          f'{len(s_old["claimable"])} vs {len((await summary())["claimable"])}')

    # ══ the money going back out ══════════════════════════════════════════
    print("\n── a receipt reversed after the fact ──")
    proj_r, inv_r, _ = await a_job(f"R{TAG}")
    s = await summary()
    check("the new settled job is offered", proj_r in claimable_ids(s),
          str(claimable_ids(s))[:160])

    inv = J(await c.get(f"/finance/invoices/{inv_r}", headers=fin))
    pay_id = (inv.get("payments") or [{}])[0].get("id")
    r = await c.post(f"/payments/{pay_id}/reverse", headers=d,
                     json={"reason": f"bounced {TAG}"})
    check("the director reverses the customer's payment", r.status_code == 201,
          f"{r.status_code} {why(r)}")

    s = await summary()
    check("the job disappears from the rep's claimable list — the page and the "
          "gate shut together",
          proj_r not in claimable_ids(s), str(claimable_ids(s))[:160])
    r = await c.post("/commissions", headers=s1, json={"project_id": proj_r})
    check("...and claiming it is refused", r.status_code == 409,
          f"{r.status_code} {why(r)}")

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    for f in FAIL:
        print("  ✗", f)


asyncio.run(main())

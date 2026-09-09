"""Logging a follow-up is a record, not a request.

Sales logging a follow-up used to file an approval request instead of writing
anything down. The activity and its reminder appeared only once the director
signed off — so a rep rang a customer on Monday, typed what was said, and the
customer's timeline showed nothing until somebody got round to the queue.

Nothing was being decided. The call had already happened; the note is the
record of it, and a record written days late is one nobody trusts to be
complete. It also buried the queue that exists for decisions that *are*
decisions — a price, a Won, an order — under a stream of "rang the customer,
will call Tuesday".

So it is written when it is logged, by whoever made the call, from both places
that log one: the quotation page and the customer's own activity list. What
this checks is that the note is actually *there* immediately — not merely that
the endpoint stopped answering 202 — and that the reminder booked alongside it
lands too, since that was the other half held back.

The scope rule is untouched and is checked here as well: dropping an approval
gate must not turn into dropping the rule that a rep only works their own
customers.
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
    s2 = await login("sales2@demo.local")
    pur = await login("purchasing@demo.local")

    async def pending_followups():
        rows = J(await c.get("/approvals", headers=d))
        return [a for a in (rows if isinstance(rows, list) else [])
                if a.get("target_type") == "followup"]

    before = len(await pending_followups())

    # ── a customer with a quotation to follow up on ──────────────────────
    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Tindak {TAG}", "industry": "mining"}))["id"]
    pr = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [{"description": f"Chain {TAG}", "qty": 5, "uom": "pcs",
                   "category": "roller_chain"}]}))
    await c.post(f"/price-requests/{pr['id']}/submit", headers=s1)
    await c.post(f"/price-requests/{pr['id']}/price", headers=pur,
                 json={"items": [{"line_no": 1, "cost_price": 100_000, "basis": "unit"}]})
    await c.post(f"/price-requests/{pr['id']}/approve", headers=d,
                 json={"items": [{"line_no": 1, "sell_price": 200_000, "basis": "unit"}]})
    q = J(await c.post(f"/quotations/from-price-request/{pr['id']}", headers=s1))
    await c.post(f"/quotations/{q['id']}/submit", headers=s1)
    await c.post(f"/quotations/{q['id']}/approve", headers=d, json={"decision": "approve"})

    # ══ on the quotation ═════════════════════════════════════════════════
    print("\n── a rep logs a follow-up on the quotation ──")
    r = await c.post(f"/quotations/{q['id']}/followup", headers=s1, json={
        "notes": f"Rang Pak Budi, wants the price held — {TAG}",
        "next_at": "2026-10-05T09:00:00Z", "next_channel": "whatsapp"})
    check("it is written, not queued", r.status_code == 201,
          f"{r.status_code} {why(r)}")
    body = J(r)
    check("...and comes back as an activity, not an approval request",
          bool(body.get("activity_id")) and "approval_request_id" not in body,
          str(body)[:200])
    check("...with the reminder booked alongside it",
          bool(body.get("reminder_id")), str(body.get("reminder_id")))

    print("\n── and it is on the record straight away ──")
    lst = J(await c.get(f"/quotations/{q['id']}/followups", headers=s1))
    acts = lst.get("activities") or []
    check("the quotation's own follow-up list shows it",
          any(TAG in (a.get("notes") or "") for a in acts), str(len(acts)))
    check("...and the reminder is listed too",
          any((lst.get("reminders") or [])), str(len(lst.get("reminders") or [])))
    ca = J(await c.get(f"/customers/{cust}/activities", headers=s1))
    check("the customer's timeline has it as well",
          any(TAG in (a.get("notes") or "") for a in ca), str(len(ca)))
    check("...recorded as the rep who made the call, not the director",
          next((a for a in ca if TAG in (a.get("notes") or "")), {}).get("user_id")
          == J(await c.get("/auth/me", headers=s1))["id"],
          str(next((a for a in ca if TAG in (a.get('notes') or "")), {}).get("user_id")))

    print("\n── and the director's queue is left alone ──")
    check("no follow-up request was filed",
          len(await pending_followups()) == before,
          f"{before} -> {len(await pending_followups())}")

    # ══ on the customer ══════════════════════════════════════════════════
    print("\n── the same from the customer's activity list ──")
    r = await c.post(f"/customers/{cust}/activities", headers=s1, json={
        "type": "follow_up", "direction": "outbound",
        "notes": f"Second call, sending revised sheet — {TAG}"})
    check("it is written there too", r.status_code == 201, f"{r.status_code} {why(r)}")
    check("...and returns the activity itself", bool(J(r).get("id")), str(J(r))[:160])
    ca = J(await c.get(f"/customers/{cust}/activities", headers=s1))
    check("...visible immediately on the timeline",
          sum(1 for a in ca if TAG in (a.get("notes") or "")) == 2,
          str(sum(1 for a in ca if TAG in (a.get('notes') or ""))))
    check("still nothing in the director's queue",
          len(await pending_followups()) == before,
          str(len(await pending_followups())))

    # ══ other roles were never gated, and still are not ══════════════════
    print("\n── and the roles that could always log one still can ──")
    r = await c.post(f"/customers/{cust}/activities", headers=d, json={
        "type": "follow_up", "direction": "outbound",
        "notes": f"Director note — {TAG}"})
    check("the director logs one directly", r.status_code == 201,
          f"{r.status_code} {why(r)}")

    # ══ the boundary that must NOT have moved ════════════════════════════
    print("\n── but a rep still only works their own customers ──")
    r = await c.post(f"/customers/{cust}/activities", headers=s2, json={
        "type": "follow_up", "direction": "outbound",
        "notes": f"Another rep's customer — {TAG}"})
    check("another rep cannot log against it", r.status_code == 403,
          str(r.status_code))
    r = await c.post(f"/quotations/{q['id']}/followup", headers=s2,
                     json={"notes": f"Not mine — {TAG}"})
    check("...nor on the quotation", r.status_code == 403, str(r.status_code))

    print("\n── and an empty note is still refused ──")
    r = await c.post(f"/quotations/{q['id']}/followup", headers=s1,
                     json={"notes": "   "})
    check("a blank follow-up is not a record of anything", r.status_code == 400,
          str(r.status_code))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)


asyncio.run(main())

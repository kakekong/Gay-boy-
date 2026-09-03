"""Which quotations follow their price request, and which only hear about it.

The rule was stated once and is easy to get wrong from the outside: a
quotation nobody has acted on is rewritten, one that has gone somewhere is
not. "Gone somewhere" is a list of statuses, and a list nobody checks is a
list that drifts — so this walks a quotation into every state it can be in
and records what a change to the request does to it.

One state is reached by hand: nothing in the app ever sets a quotation to
"sent" — the status is checked for in several places but never written, so it
only exists on older data. The rule still has to cover it.

It exists because the rule is invisible from the screen you are standing on.
Edit a request whose quotation is won and nothing appears to happen, which
looks exactly like a broken feature and is in fact the feature. The answer
has to be somewhere you can point at.
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

# What each state is expected to do. Written out rather than derived, so a
# change to the rule has to be made here too, deliberately.
EXPECTED = {
    "draft":            True,
    "rejected":         True,
    "pending_approval": False,
    "approved":         False,
    "sent":             False,
    "won":              False,
}


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

    async def make(label):
        """An approved request with a quotation drafted off it."""
        cust = J(await c.post("/customers", headers=s1, json={
            "company_name": f"PT {label} {TAG}", "industry": "mining"}))["id"]
        pr = J(await c.post("/price-requests", headers=s1, json={
            "customer_id": cust,
            "items": [{"description": f"Rotor {label} {TAG}", "qty": 4,
                       "uom": "pcs"}]}))
        await c.post(f"/price-requests/{pr['id']}/submit", headers=s1)
        await c.post(f"/price-requests/{pr['id']}/price", headers=pur, json={
            "items": [{"line_no": 1, "cost_price": 500_000, "basis": "unit"}]})
        await c.post(f"/price-requests/{pr['id']}/approve", headers=d, json={
            "items": [{"line_no": 1, "sell_price": 1_000_000, "basis": "unit"}]})
        q = J(await c.post(f"/quotations/from-price-request/{pr['id']}", headers=s1))
        return cust, pr["id"], q["id"]

    async def drive(q_id, cust, to):
        """Walk the quotation into `to`, by the routes the app actually uses."""
        if to == "draft":
            return
        if to == "rejected":
            await c.post(f"/quotations/{q_id}/submit", headers=s1)
            await c.post(f"/quotations/{q_id}/reject", headers=d, json={"notes": "no"})
            return
        await c.post(f"/quotations/{q_id}/submit", headers=s1)
        if to == "pending_approval":
            return
        await c.post(f"/quotations/{q_id}/approve", headers=d, json={"notes": ""})
        if to == "approved":
            return
        if to == "sent":
            # Nothing in the app sets this: the status is checked for in
            # several places but never written, so it is reachable only from
            # older data. The rule still has to cover it, so it is set
            # directly rather than left untested.
            from app.core.db import SessionLocal
            from app.models.quotation import Quotation as _Q
            async with SessionLocal() as db:
                row = await db.get(_Q, uuid.UUID(q_id))
                row.status = "sent"
                await db.commit()
            return
        if to == "won":
            # Won needs a customer PO, and approving that PO opens the project
            # — which is the state the report came from.
            cpo = J(await c.post("/customer-pos", headers=s1, json={
                "customer_id": cust, "quotation_id": q_id,
                "number": f"PO-MTX-{TAG}-{uuid.uuid4().hex[:4]}",
                "items": [{"description": "x", "qty": 4, "unit_price": 1_000_000}],
                "is_downpayment": False}))["id"]
            await c.post(f"/quotations/{q_id}/won", headers=d)
            await c.post(f"/customer-pos/{cpo}/approve", headers=d, json={"notes": ""})

    print("\n── what a price-request change does, per quotation status ──")
    for state, should_sync in EXPECTED.items():
        cust, pr_id, q_id = await make(state.replace("_", "")[:6])
        await drive(q_id, cust, state)
        q = J(await c.get(f"/quotations/{q_id}", headers=d))
        got_state = q.get("status")
        if got_state != state:
            check(f"{state}: the fixture reaches that state", False,
                  f"landed in '{got_state}'")
            continue
        was_total = float(q.get("total") or 0)
        was_desc = q["items"][0]["description"]

        r = await c.patch(f"/price-requests/{pr_id}", headers=d, json={
            "items": [{"line_no": 1, "description": f"CHANGED {TAG}", "qty": 40,
                       "uom": "pcs"}]})
        if r.status_code != 200:
            check(f"{state}: the request can still be edited", False,
                  f"{r.status_code} {why(r)}")
            continue
        rep = (J(r).get("quotations") or [{}])[0]
        q2 = J(await c.get(f"/quotations/{q_id}", headers=d))
        moved = (q2["items"][0]["description"] != was_desc
                 or float(q2.get("total") or 0) != was_total)

        if should_sync:
            check(f"{state}: the quotation is rewritten to match",
                  moved and rep.get("synced") is True,
                  f"moved={moved} report={rep}")
            check(f"{state}: ...taking the new wording and quantity",
                  q2["items"][0]["description"] == f"CHANGED {TAG}"
                  and float(q2["items"][0]["qty"]) == 40,
                  str(q2["items"][0])[:200])
        else:
            check(f"{state}: the quotation is left exactly as it was",
                  not moved and rep.get("synced") is False,
                  f"moved={moved} report={rep}")
            check(f"{state}: ...but told, in writing, that the request moved",
                  "changed after this quotation was" in (q2.get("notes") or ""),
                  str(q2.get("notes"))[:260])
            check(f"{state}: ...naming what it would now come to",
                  str(rep.get("new_total")) not in ("None", "")
                  and rep.get("old_total") is not None,
                  str(rep)[:220])

    # ══ the case the report came from ════════════════════════════════════
    # A won quotation with a project behind it is the one place a silent
    # rewrite would be worst, and the one place somebody is most likely to
    # try it. It must refuse *and* say so — not merely do nothing.
    print("\n── the reported case: won, with a project open ──")
    cust, pr_id, q_id = await make("Proyek")
    await drive(q_id, cust, "won")
    q = J(await c.get(f"/quotations/{q_id}", headers=d))
    check("the quotation is won", q.get("status") == "won", str(q.get("status")))
    projs = J(await c.get("/operation/projects", headers=d, params={"limit": 200}))
    rows = projs if isinstance(projs, list) else projs.get("items", [])
    check("...and a project was opened from it",
          any(str(x.get("customer_id")) == str(cust) for x in rows),
          str(len(rows)))
    r = await c.patch(f"/price-requests/{pr_id}", headers=d, json={
        "items": [{"line_no": 1, "description": f"Rotor Proyek {TAG} rev C",
                   "qty": 4, "uom": "pcs"}]})
    check("the request still takes the edit", r.status_code == 200,
          f"{r.status_code} {why(r)}")
    rep = (J(r).get("quotations") or [{}])[0]
    check("...and the answer says the quotation was not rewritten",
          rep.get("synced") is False and rep.get("status") == "won", str(rep)[:220])
    q = J(await c.get(f"/quotations/{q_id}", headers=d))
    check("...the quotation the customer signed is untouched",
          q["items"][0]["description"] != f"Rotor Proyek {TAG} rev C",
          str(q["items"][0].get("description")))
    check("...and it carries the warning where somebody will read it",
          "changed after this quotation was won" in (q.get("notes") or ""),
          str(q.get("notes"))[:260])

    # ══ the notice is ours, not the customer's ═══════════════════════════
    # The warning lives in the notes blob, which is printed on the quotation
    # the customer receives. It has to survive the read that puts it on our
    # screen and be gone from the copy that leaves the building — those pull
    # from the same field, so one of them is always about to be wrong.
    print("\n── who gets to read the warning ──")
    q = J(await c.get(f"/quotations/{q_id}", headers=d))
    check("we can still read it after a reload",
          "[system]" in (q.get("notes") or "")
          or "changed after this quotation was" in (q.get("notes") or ""),
          str(q.get("notes"))[:260])

    r = await c.get(f"/quotations/{q_id}/export.pdf", headers=d)
    check("the customer's PDF still builds", r.status_code == 200,
          f"{r.status_code} {r.text[:150]}")
    body = r.content
    check("...and carries none of our side-channel",
          b"[system]" not in body and b"changed after this quotation" not in body,
          "the warning reached the customer's copy")

    r = await c.get(f"/quotations/{q_id}/export.xlsx", headers=d)
    check("the spreadsheet builds too", r.status_code == 200,
          f"{r.status_code} {r.text[:150]}")
    check("...and is clean as well",
          b"[system]" not in r.content, "the warning reached the spreadsheet")

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)


asyncio.run(main())

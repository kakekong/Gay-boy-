"""A red badge is a claim that work is waiting. Most of them weren't.

Purchasing opened the app to a "10" on Purchasing PO and a "4" on Price
requests, with nothing behind either one. The sidebar was counting every
active bell item under a section, and the bell carries two very different
kinds of thing: work that needs doing, and news that something already
happened. Ten of those "10" were *their own* requests coming back approved
— the good outcome, already acted on by the approver, asking nothing of
anyone. Supplier POs make that pile fast, because since edits started
needing sign-off every revision to a PO files its own approval.

Severity already draws the line at the source, so the fix leans on it
rather than inventing a second rule: 'low' is the FYI tier and never
badges, high/medium is work and does. The bell still lists all of it.

Two corrections at the source go with it:

* An approved outcome is news with a short life — two days, not the week a
  rejection gets, because a rejection is work you still have to do.
* A decided price request is *not* FYI either way: approved means quote it,
  sent back means revise it. Both land on the rep, so both badge.

What this driver protects is the classification, since that is what the
sidebar reads: the right severity on each row, the right shelf life on each
outcome, and no work quietly demoted to silent.
"""
import asyncio, os, sys, uuid
from datetime import UTC, datetime, timedelta
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

# What the sidebar does with the feed, kept here so the rule is asserted
# rather than described: anything below the FYI line badges its section.
def badge_counts(items) -> dict:
    out: dict[str, int] = {}
    for i in items:
        if i.get("severity") == "low":
            continue
        link = (i.get("link") or "").split("?")[0].rstrip("/")
        if link:
            out[link] = out.get(link, 0) + 1
    return out


async def a_project(c, d, s1, pur, tag) -> str:
    """A live project to hang supplier POs off — a PO needs one."""
    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Lonceng PO {tag}", "industry": "mining"}))["id"]
    pr = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [{"description": f"BOLT {tag}", "qty": 10, "uom": "pcs"}]}))
    await c.post(f"/price-requests/{pr['id']}/submit", headers=s1)
    await c.post(f"/price-requests/{pr['id']}/price", headers=pur, json={
        "items": [{"line_no": 1, "cost_price": 100_000, "basis": "unit"}]})
    await c.post(f"/price-requests/{pr['id']}/approve", headers=d, json={
        "items": [{"line_no": 1, "sell_price": 200_000, "basis": "unit"}]})
    q = J(await c.post(f"/quotations/from-price-request/{pr['id']}", headers=s1))
    await c.post(f"/quotations/{q['id']}/submit", headers=s1)
    await c.post(f"/quotations/{q['id']}/approve", headers=d, json={"notes": ""})
    cpo = J(await c.post("/customer-pos", headers=s1, json={
        "customer_id": cust, "quotation_id": q["id"], "number": f"CPO-N{tag}",
        "items": [{"description": f"BOLT {tag}", "qty": 10,
                   "unit_price": 200_000}],
        "is_downpayment": False}))
    await c.post(f"/quotations/{q['id']}/won", headers=d)
    return J(await c.post(f"/customer-pos/{cpo['id']}/approve", headers=d,
                          json={"notes": ""}))["project_id"]


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

    async def feed(headers):
        return (J(await c.get("/notifications", headers=headers))).get("items") or []

    # Start from a clean bell for purchasing so the counts below are this
    # run's doing and not six other drivers'.
    await c.post("/notifications/dismiss-all", headers=pur)
    check("purchasing starts with an empty bell", not await feed(pur))

    # ══ a purchaser's own approved requests ══════════════════════════════════
    # Three supplier POs, each filed by purchasing and signed off by the
    # director. Three approvals, none of which asks the purchaser for
    # anything: the PO is open, the job moved on.
    print("\n── your own request coming back approved ──")
    proj = await a_project(c, d, s1, pur, tag)
    sup = J(await c.post("/purchasing/suppliers", headers=pur,
                         json={"name": f"PT Notif {tag}"}))["id"]
    po_ids = []
    for n in range(3):
        po = J(await c.post("/purchasing/po", headers=pur, json={
            "supplier_id": sup, "project_id": proj, "eta": "2026-12-01",
            "items": [{"description": f"BOLT {tag}-{n}", "qty": 5, "uom": "pcs",
                       "unit_price": 100_000, "amount": 500_000}],
            "total": 500_000}))
        po_ids.append(po.get("id"))
    check("purchasing filed three POs", all(po_ids), str(po_ids))

    pend = [a for a in J(await c.get("/approvals", headers=d))
            if a.get("target_id") in po_ids]
    check("...each waiting on the director", len(pend) == 3, str(len(pend)))
    for a in pend:
        r = await c.post(f"/approvals/{a['id']}/approve", headers=d)
        check(f"...and the director signs it off", r.status_code == 200,
              f"{r.status_code} {J(r)}"[:120])

    items = await feed(pur)
    mine = [i for i in items if i.get("kind") == "approval_decided"]
    check("the purchaser is told all three went through", len(mine) == 3,
          str([i.get("title") for i in mine]))
    check("...and they point at the POs", all(i.get("link") == "/purchase-orders"
                                              for i in mine),
          str([i.get("link") for i in mine]))
    check("...as news, not work", all(i.get("severity") == "low" for i in mine),
          str([i.get("severity") for i in mine]))
    check("...so nothing lights up on Purchasing PO",
          badge_counts(items).get("/purchase-orders", 0) == 0,
          str(badge_counts(items)))
    check("...while the bell still carries them", len(items) >= 3, str(len(items)))

    # ══ a rejection is a different thing entirely ════════════════════════════
    print("\n── a rejection is work ──")
    po = J(await c.post("/purchasing/po", headers=pur, json={
        "supplier_id": sup, "project_id": proj, "eta": "2026-12-01",
        "items": [{"description": f"NUT {tag}", "qty": 1, "uom": "pcs",
                   "unit_price": 9, "amount": 9}],
        "total": 9}))
    bad = next(a for a in J(await c.get("/approvals", headers=d))
               if a.get("target_id") == po["id"])
    r = await c.post(f"/approvals/{bad['id']}/reject", headers=d,
                     params={"notes": "wrong supplier"})
    check("the director turns it down", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:120])

    items = await feed(pur)
    rej = [i for i in items if i.get("kind") == "approval_decided"
           and "rejected" in (i.get("title") or "")]
    check("the purchaser is told it was turned down", len(rej) == 1,
          str([i.get("title") for i in items]))
    check("...and it is not filed as news", rej and rej[0]["severity"] != "low",
          str(rej[0].get("severity")) if rej else "")
    check("...so Purchasing PO does light up, once",
          badge_counts(items).get("/purchase-orders", 0) == 1,
          str(badge_counts(items)))
    check("...carrying the reason to fix it",
          rej and "wrong supplier" in (rej[0].get("body") or ""),
          str(rej[0].get("body")) if rej else "")

    # ══ shelf life ═══════════════════════════════════════════════════════════
    # Approvals stack up because every PO edit files one. Age them and the
    # good news goes; the rejection, which is still owed work, stays.
    print("\n── how long each outcome is worth saying ──")
    from sqlalchemy import select
    from app.core.db import SessionLocal
    from app.models.approval import ApprovalRequest
    async with SessionLocal() as db:
        rows = (await db.scalars(
            select(ApprovalRequest).where(
                ApprovalRequest.target_id.in_([uuid.UUID(x) for x in po_ids]
                                              + [uuid.UUID(po["id"])])
            )
        )).all()
        for a in rows:
            a.decided_at = datetime.now(UTC) - timedelta(days=3)
        await db.commit()
    check("four decisions were aged three days", len(rows) == 4, str(len(rows)))

    items = await feed(pur)
    aged = [i for i in items if i.get("kind") == "approval_decided"]
    check("the approvals have stopped being said",
          all("approved" not in (i.get("title") or "") for i in aged),
          str([i.get("title") for i in aged]))
    check("...while the rejection is still owed work, so it stays",
          any("rejected" in (i.get("title") or "") for i in aged),
          str([i.get("title") for i in aged]))

    async with SessionLocal() as db:
        stale = (await db.scalars(
            select(ApprovalRequest).where(
                ApprovalRequest.target_id == uuid.UUID(po["id"])
            )
        )).all()
        for a in stale:
            a.decided_at = datetime.now(UTC) - timedelta(days=9)
        await db.commit()
    items = await feed(pur)
    check("...and after a week even the rejection stops",
          not [i for i in items if i.get("kind") == "approval_decided"],
          str([i.get("title") for i in items
               if i.get("kind") == "approval_decided"]))

    # ══ a decided price request is nobody's FYI ══════════════════════════════
    # "Approved — quote it" is an instruction. It used to be filed at the
    # same silent tier as "your request went through", which meant the one
    # prompt a rep gets to turn a price into a quotation never badged.
    print("\n── the rep's handoff is not news either ──")
    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Lonceng {tag}", "industry": "mining"}))["id"]
    pr = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [{"description": f"CHAIN {tag}", "qty": 2, "uom": "meter"}]}))
    await c.post(f"/price-requests/{pr['id']}/submit", headers=s1)
    await c.post(f"/price-requests/{pr['id']}/price", headers=pur, json={
        "items": [{"line_no": 1, "cost_price": 1_000, "basis": "unit"}]})
    await c.post(f"/price-requests/{pr['id']}/approve", headers=d, json={
        "items": [{"line_no": 1, "sell_price": 2_000, "basis": "unit"}]})

    items = await feed(s1)
    dec = [i for i in items if i.get("id", "").startswith(f"pr-decided:{pr['id']}")]
    check("the rep is told their price request came back", len(dec) == 1,
          str([i.get("id") for i in items])[:200])
    check("...told to quote it", dec and "quote it" in (dec[0].get("title") or ""),
          str(dec[0].get("title")) if dec else "")
    check("...and it is work, so Price requests lights up",
          dec and dec[0]["severity"] != "low",
          str(dec[0].get("severity")) if dec else "")
    check("...counted under the price requests section",
          badge_counts(items).get("/price-requests", 0) >= 1,
          str(badge_counts(items)))

    # ══ nothing that IS work got demoted ═════════════════════════════════════
    # The whole fix is a filter, so the thing to prove is what survives it:
    # every queue row that asks someone to act is still above the line.
    print("\n── what must still badge ──")
    waiting = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [{"description": f"PIN {tag}", "qty": 1, "uom": "pcs"}]}))
    await c.post(f"/price-requests/{waiting['id']}/submit", headers=s1)
    got = await feed(pur)
    cost_row = next((i for i in got
                     if i.get("id") == f"pr-cost:{waiting['id']}"), None)
    check("purchasing is asked to cost the new price request",
          cost_row is not None, str([i.get("id") for i in got])[:200])
    check("...loudly", cost_row and cost_row["severity"] == "high",
          str(cost_row.get("severity")) if cost_row else "")
    check("...so Price requests carries the number",
          badge_counts(got).get("/price-requests", 0) >= 1, str(badge_counts(got)))

    # Hand the same job on to the director and it must shout at them too —
    # built here rather than read off whatever the rest of the suite left
    # lying around, so the assertion means the same thing on a fresh DB.
    await c.post(f"/price-requests/{waiting['id']}/price", headers=pur, json={
        "items": [{"line_no": 1, "cost_price": 500, "basis": "unit"}]})
    got = await feed(d)
    price_row = next((i for i in got
                      if i.get("id") == f"pr-price:{waiting['id']}"), None)
    check("the director is asked to set the sell price",
          price_row is not None, str([i.get("id") for i in got])[:200])
    check("...loudly", price_row and price_row["severity"] == "high",
          str(price_row.get("severity")) if price_row else "")
    check("...and it counts toward their Price requests badge",
          badge_counts(got).get("/price-requests", 0) >= 1, str(badge_counts(got)))

    # And the pending approvals they still owe a decision on.
    po2 = J(await c.post("/purchasing/po", headers=pur, json={
        "supplier_id": sup, "project_id": proj, "eta": "2026-12-02",
        "items": [{"description": f"WASHER {tag}", "qty": 2, "uom": "pcs",
                   "unit_price": 50, "amount": 100}],
        "total": 100}))
    got = await feed(d)
    appr = [i for i in got if i.get("kind") == "approval"]
    check("the director's pending approvals are still in the bell", bool(appr),
          str(sorted({i.get("kind") for i in got})))
    check("...including the PO just filed",
          any(i.get("id") == f"approval:{a['id']}"
              for a in J(await c.get("/approvals", headers=d))
              if a.get("target_id") == po2.get("id")
              for i in appr),
          str([i.get("id") for i in appr])[:200])
    # Approvals has its own live counter rather than a path badge, so what
    # matters here is only that these never fall to the silent tier.
    check("...and none of them silent",
          all(i.get("severity") != "low" for i in appr),
          str([(i.get("title"), i.get("severity")) for i in appr]))

    # Every row must carry a severity at all — the sidebar reads it, and a
    # missing one would silently badge (or silently not).
    everyone = await feed(d)
    check("every row is classified",
          all(i.get("severity") in ("high", "medium", "low") for i in everyone),
          str([i.get("id") for i in everyone if i.get("severity")
               not in ("high", "medium", "low")])[:200])

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        sys.exit(1)


asyncio.run(main())

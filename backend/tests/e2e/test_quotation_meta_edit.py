"""Typing a note is not editing the price.

Reported: a sales rep opens a quotation that came from an approved price
request, types a note, presses Save, and is told "Line prices are fixed by the
approved price request and can't be edited." They had not touched a price.

The cause was not the rule, which is right, but what triggered it. The edit
form posts the whole document back — number, variant, tax, discount and every
line item — so a note arrives alongside line items that are identical to the
ones already stored. Every guard in the update handler asked "are items in
this payload?" when what it meant was "did the items change".

That produced two failures from one confusion, and only one of them was
visible:

  the loud one     a draft price-request-backed quotation refused the note
                   outright, naming prices nobody had touched

  the quiet one    on an approved or sent quotation the same note was filed
                   as a pricing edit awaiting the director's approval — so
                   the note did not appear, and the director got an approval
                   request for a change that did not exist

So this driver checks the distinction itself, in both directions. A no-op
payload must be treated as no edit; a real price change must still be refused
or still need approval, exactly as before. The second half matters more than
the first — a fix that let sales quietly rewrite an approved price would be
far worse than the bug it replaced.
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


def form_payload(q: dict, **over) -> dict:
    """What the edit modal actually posts: the whole document, every time."""
    body = {
        "variant": q["variant"],
        "number": q["number"],
        "tax_pct": q["tax_pct"],
        "discount_pct": q["discount_pct"],
        "notes": q.get("notes") or "",
        "valid_until": q.get("valid_until"),
        "items": [{"line_no": it["line_no"], "description": it["description"],
                   "qty": it["qty"], "uom": it["uom"],
                   "unit_price": it["unit_price"]} for it in q["items"]],
    }
    body.update(over)
    return body


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=120)

    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    tag = uuid.uuid4().hex[:5]
    d = await login("director@demo.local")
    s1 = await login("sales1@demo.local")
    pur = await login("purchasing@demo.local")

    async def pr_quotation(price: float = 2_556_061) -> dict:
        """A quotation generated from an approved price request, as the real
        flow produces them — which is the only way sales gets one."""
        cust = J(await c.post("/customers", headers=s1, json={
            "company_name": f"PT Catatan {tag}-{uuid.uuid4().hex[:4]}",
            "industry": "mining"}))["id"]
        pr = J(await c.post("/price-requests", headers=s1, json={
            "customer_id": cust,
            "items": [{"description": f"CHAIN C-2122-H {tag}", "qty": 40,
                       "uom": "meter"}]}))["id"]
        await c.post(f"/price-requests/{pr}/submit", headers=s1)
        await c.post(f"/price-requests/{pr}/price", headers=pur, json={
            "items": [{"line_no": 1, "cost_price": 2_000_000, "basis": "unit"}]})
        await c.post(f"/price-requests/{pr}/approve", headers=d, json={
            "items": [{"line_no": 1, "sell_price": price, "basis": "unit"}]})
        return J(await c.post(f"/quotations/from-price-request/{pr}", headers=s1))

    async def pending_edits(qid: str) -> int:
        q = J(await c.get("/approvals", headers=d))
        rows = q if isinstance(q, list) else (q.get("data") or [])
        return sum(1 for a in rows
                   if a.get("target_type") == "quotation_edit"
                   and str(a.get("target_id")) == str(qid))

    # ══ the reported bug ═════════════════════════════════════════════════════
    print("\n── a note on a draft price-request quotation ──")
    q = await pr_quotation()
    check("the quotation is price-request backed", bool(q.get("price_request_id")),
          str(q.get("price_request_id")))
    r = await c.patch(f"/quotations/{q['id']}", headers=s1,
                      json=form_payload(q, notes="note"))
    check("sales can save a note", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:170])
    got = J(await c.get(f"/quotations/{q['id']}", headers=d))
    check("...and the note is actually stored", got.get("notes") == "note",
          str(got.get("notes")))
    check("...with the approved price untouched",
          float(got["items"][0]["unit_price"]) == 2_556_061,
          str(got["items"][0]["unit_price"]))
    check("...and the total unchanged", float(got["total"]) == float(q["total"]),
          f"{got['total']} vs {q['total']}")

    # ══ the quiet half ═══════════════════════════════════════════════════════
    print("\n── the same note once the quotation is approved ──")
    q2 = await pr_quotation()
    await c.post(f"/quotations/{q2['id']}/submit", headers=d)
    await c.post(f"/quotations/{q2['id']}/approve", headers=d, json={})
    cur = J(await c.get(f"/quotations/{q2['id']}", headers=d))
    check("it is approved", cur["status"] == "approved", cur["status"])
    before = await pending_edits(q2["id"])
    r = await c.patch(f"/quotations/{q2['id']}", headers=s1,
                      json=form_payload(cur, notes="approved note"))
    check("a note on an approved quotation saves straight away",
          r.status_code == 200, f"{r.status_code} {J(r)}"[:170])
    got = J(await c.get(f"/quotations/{q2['id']}", headers=d))
    check("...the note is there", got.get("notes") == "approved note", str(got.get("notes")))
    check("...the quotation is still approved, not knocked back",
          got["status"] == "approved", got["status"])
    check("...and the director was not asked to approve a note",
          await pending_edits(q2["id"]) == before, "an approval request was filed")

    # ══ and the rule it was mistaken for still bites ═════════════════════════
    print("\n── a real price change is still refused ──")
    q3 = await pr_quotation()
    bad = form_payload(q3)
    bad["items"][0]["unit_price"] = 1
    r = await c.patch(f"/quotations/{q3['id']}", headers=s1, json=bad)
    check("sales cannot change a price-request-backed line price",
          r.status_code == 409, str(r.status_code))
    check("...and is told why",
          "fixed by the approved price request" in str(J(r)), str(J(r))[:150])
    still = J(await c.get(f"/quotations/{q3['id']}", headers=d))
    check("...and the price really did not move",
          float(still["items"][0]["unit_price"]) == 2_556_061,
          str(still["items"][0]["unit_price"]))

    bad_qty = form_payload(q3)
    bad_qty["items"][0]["qty"] = 999
    r = await c.patch(f"/quotations/{q3['id']}", headers=s1, json=bad_qty)
    check("changing the quantity is refused too — it changes the value",
          r.status_code == 409, str(r.status_code))

    bad_desc = form_payload(q3)
    bad_desc["items"][0]["description"] = "something else entirely"
    r = await c.patch(f"/quotations/{q3['id']}", headers=s1, json=bad_desc)
    check("...and so is rewriting the line the director approved",
          r.status_code == 409, str(r.status_code))

    # A discount is a price change by another name, and the guard for it is
    # separate — make sure the pruning did not open that door either.
    disc = form_payload(q3, discount_pct=25)
    r = await c.patch(f"/quotations/{q3['id']}", headers=s1, json=disc)
    after = J(await c.get(f"/quotations/{q3['id']}", headers=d))
    check("a discount change is not silently applied and lost",
          r.status_code != 200 or float(after["discount_pct"]) == 25,
          f"{r.status_code} -> {after['discount_pct']}")

    # ══ a genuine pricing edit still needs the director ══════════════════════
    print("\n── a genuine pricing edit on an approved quotation ──")
    # Built by the director directly, so it has no price request behind it and
    # the queue-for-approval path is the one under test rather than the 409.
    cust = J(await c.post("/customers", headers=d, json={
        "company_name": f"PT Langsung {tag}", "industry": "cement"}))["id"]
    q4 = J(await c.post("/quotations", headers=d, json={
        "customer_id": cust, "variant": "detailed",
        "items": [{"line_no": 1, "description": f"Sprocket {tag}", "qty": 2,
                   "uom": "pcs", "unit_price": 1_000_000}]}))
    await c.post(f"/quotations/{q4['id']}/submit", headers=d)
    await c.post(f"/quotations/{q4['id']}/approve", headers=d, json={})
    # The director owns it, so hand it to sales1 — the path under test is the
    # non-director one. Quotation ownership has no API, hence the direct write.
    me = J(await c.get("/auth/me", headers=s1))
    await c.patch(f"/customers/{cust}", headers=d, json={"sales_pic_id": me["id"]})
    from sqlalchemy import update as sqlupdate
    from app.core.db import SessionLocal
    from app.models.quotation import Quotation as _Q
    async with SessionLocal() as sess:            # ownership isn't editable via the API
        await sess.execute(sqlupdate(_Q).where(_Q.id == uuid.UUID(q4["id"]))
                           .values(sales_pic_id=uuid.UUID(me["id"])))
        await sess.commit()

    cur4 = J(await c.get(f"/quotations/{q4['id']}", headers=s1))
    before = await pending_edits(q4["id"])
    real = form_payload(cur4)
    real["items"][0]["unit_price"] = 1_500_000
    r = await c.patch(f"/quotations/{q4['id']}", headers=s1, json=real)
    check("a real price change by sales still goes to the director",
          r.status_code == 202, f"{r.status_code} {J(r)}"[:150])
    check("...and an approval request was filed",
          await pending_edits(q4["id"]) == before + 1, "none filed")
    unchanged = J(await c.get(f"/quotations/{q4['id']}", headers=d))
    check("...while the live quotation keeps the approved price",
          float(unchanged["items"][0]["unit_price"]) == 1_000_000,
          str(unchanged["items"][0]["unit_price"]))

    # ...but a note on that same quotation does not need anyone.
    before = await pending_edits(q4["id"])
    r = await c.patch(f"/quotations/{q4['id']}", headers=s1,
                      json=form_payload(cur4, notes=f"just a note {tag}"))
    check("a note on it saves without another approval request",
          r.status_code == 200, f"{r.status_code} {J(r)}"[:150])
    check("...and filed none", await pending_edits(q4["id"]) == before, "one was filed")

    # ══ pressing Save with nothing altered ═══════════════════════════════════
    print("\n── Save with nothing changed ──")
    q5 = await pr_quotation()
    r = await c.patch(f"/quotations/{q5['id']}", headers=s1, json=form_payload(q5))
    check("an unchanged save is accepted rather than refused",
          r.status_code == 200, f"{r.status_code} {J(r)}"[:150])
    same = J(await c.get(f"/quotations/{q5['id']}", headers=d))
    check("...and changes nothing",
          float(same["total"]) == float(q5["total"])
          and same["number"] == q5["number"], f"{same['total']} vs {q5['total']}")

    # ══ the other meta field on the same form ════════════════════════════════
    r = await c.patch(f"/quotations/{q5['id']}", headers=s1,
                      json=form_payload(q5, valid_until="2026-12-31"))
    check("validity is editable the same way", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:150])
    got = J(await c.get(f"/quotations/{q5['id']}", headers=d))
    check("...and lands", str(got.get("valid_until")) == "2026-12-31",
          str(got.get("valid_until")))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        sys.exit(1)


asyncio.run(main())

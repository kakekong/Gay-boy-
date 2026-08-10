"""Sales writing a note on a price request.

Asked for: "make sales be able to upload notes."

They could not, and the reason had two halves that reinforced each other.

The only ways a note ever got written were the box on the create form and the
one purchasing and the director get while costing or approving. The moment a
request left draft the whole document locked to everyone but the director, so
a rep with something to say about their own request — a spec the customer just
changed, a deadline, a warning that the quantity is about to move — had
nowhere to put it.

And the page never displayed `notes` back at all, so even the ones typed on the
create form were write-only. Nobody noticed the first problem because the
field looked empty either way.

Notes are now appended, never replaced, and tagged with the writer's role.
Both properties are load-bearing and both are checked here:

  appending      two people writing about the same request must not overwrite
                 each other, and — worse — sales replacing the blob would
                 silently delete the [purchasing] lines it cannot even see

  the tag        it is what keeps purchasing's costing chatter out of the
                 quotation PDF the customer receives, and what lets sales read
                 its own note back while still being blind to the cost side
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
    s1 = await login("sales1@demo.local")
    s2 = await login("sales2@demo.local")
    pur = await login("purchasing@demo.local")

    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Catatan {tag}", "industry": "mining"}))["id"]
    other_cust = J(await c.post("/customers", headers=s2, json={
        "company_name": f"PT Lain {tag}", "industry": "cement"}))["id"]

    async def fresh(headers=s1, customer=None) -> str:
        return J(await c.post("/price-requests", headers=headers, json={
            "customer_id": customer or cust,
            "notes": "customer asked for galvanised",
            "items": [{"description": f"CHAIN {tag}-{uuid.uuid4().hex[:4]}",
                       "qty": 10, "uom": "meter"}]}))["id"]

    # ══ the reported gap ═════════════════════════════════════════════════════
    print("\n── a note on a request that has left draft ──")
    pr = await fresh()
    await c.post(f"/price-requests/{pr}/submit", headers=s1)
    got = J(await c.get(f"/price-requests/{pr}", headers=s1))
    check("the request is out of the rep's hands", got["status"] == "pending_purchasing",
          got["status"])
    check("...and the note typed on the create form is readable",
          "galvanised" in (got.get("notes") or ""), str(got.get("notes")))

    r = await c.patch(f"/price-requests/{pr}", headers=s1,
                      json={"notes": "trying the old way"})
    check("the old route is still shut — editing a live document",
          r.status_code == 409, str(r.status_code))

    r = await c.post(f"/price-requests/{pr}/note", headers=s1,
                     json={"text": f"customer moved the deadline to Friday {tag}"})
    check("but sales can add a note", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:150])
    got = J(await c.get(f"/price-requests/{pr}", headers=s1))
    check("...and read it back", f"deadline to Friday {tag}" in (got.get("notes") or ""),
          str(got.get("notes"))[:200])
    check("...without losing what was there before",
          "galvanised" in (got.get("notes") or ""), str(got.get("notes"))[:200])
    check("...and the request did not move stage",
          got["status"] == "pending_purchasing", got["status"])

    # ══ at every other stage too ═════════════════════════════════════════════
    print("\n── and at any point in its life ──")
    await c.post(f"/price-requests/{pr}/price", headers=pur, json={
        "items": [{"line_no": 1, "cost_price": 1_000_000, "basis": "unit"}]})
    r = await c.post(f"/price-requests/{pr}/note", headers=s1,
                     json={"text": "chased the customer while it is being costed"})
    check("while purchasing has it", r.status_code == 200, str(r.status_code))
    await c.post(f"/price-requests/{pr}/approve", headers=d, json={
        "items": [{"line_no": 1, "sell_price": 1_400_000, "basis": "unit"}]})
    r = await c.post(f"/price-requests/{pr}/note", headers=s1,
                     json={"text": "quote sent to the customer"})
    check("...and once it is approved", r.status_code == 200, str(r.status_code))
    draft = await fresh()
    r = await c.post(f"/price-requests/{draft}/note", headers=s1,
                     json={"text": "still writing this one"})
    check("...and while it is still a draft", r.status_code == 200, str(r.status_code))

    # ══ nothing gets overwritten ═════════════════════════════════════════════
    print("\n── everybody's notes survive each other ──")
    got = J(await c.get(f"/price-requests/{pr}", headers=d))
    blob = got.get("notes") or ""
    check("the director sees every line", all(x in blob for x in [
        "galvanised", f"deadline to Friday {tag}",
        "chased the customer", "quote sent to the customer"]), blob[:300])
    check("...each tagged with who wrote it", blob.count("[sales]") == 3, blob[:300])

    await c.post(f"/price-requests/{pr}/note", headers=pur,
                 json={"text": f"supplier quoted 3 weeks {tag}"})
    await c.post(f"/price-requests/{pr}/note", headers=d,
                 json={"text": f"hold the margin at 40 {tag}"})
    mgmt = J(await c.get(f"/price-requests/{pr}", headers=d))["notes"]
    check("purchasing's line lands", f"supplier quoted 3 weeks {tag}" in mgmt, mgmt[:300])
    check("...and the director's", f"hold the margin at 40 {tag}" in mgmt, mgmt[:300])
    check("...and none of the earlier ones were lost",
          f"deadline to Friday {tag}" in mgmt, mgmt[:300])

    # ══ and the margin wall still stands ═════════════════════════════════════
    print("\n── while nobody learns what they should not ──")
    sales_view = J(await c.get(f"/price-requests/{pr}", headers=s1))["notes"] or ""
    check("sales reads its own notes", f"deadline to Friday {tag}" in sales_view,
          sales_view[:250])
    check("...and the original from the create form", "galvanised" in sales_view,
          sales_view[:250])
    check("...but never purchasing's", f"supplier quoted 3 weeks {tag}" not in sales_view,
          sales_view[:250])
    check("...nor the director's pricing aside",
          f"hold the margin at 40 {tag}" not in sales_view, sales_view[:250])
    pur_view = J(await c.get(f"/price-requests/{pr}", headers=pur))["notes"] or ""
    check("purchasing keeps its side-channel with the director",
          f"supplier quoted 3 weeks {tag}" in pur_view
          and f"hold the margin at 40 {tag}" in pur_view, pur_view[:250])

    # ══ and none of it reaches the customer ══════════════════════════════════
    print("\n── the quotation the customer receives ──")
    q = J(await c.post(f"/quotations/from-price-request/{pr}", headers=s1))
    qnotes = q.get("notes") or ""
    check("it inherits the customer-facing note", "galvanised" in qnotes, qnotes[:200])
    check("...and not one internal line",
          all(x not in qnotes for x in [
              f"deadline to Friday {tag}", f"supplier quoted 3 weeks {tag}",
              f"hold the margin at 40 {tag}", "[sales]", "[purchasing]", "[director]"]),
          qnotes[:250])

    # ══ the edges ════════════════════════════════════════════════════════════
    print("\n── refusals ──")
    r = await c.post(f"/price-requests/{pr}/note", headers=s1, json={"text": "   "})
    check("an empty note is refused", r.status_code == 400, str(r.status_code))
    r = await c.post(f"/price-requests/{pr}/note", headers=s1,
                     json={"text": "x" * 1001})
    check("...and one that is far too long", r.status_code == 400, str(r.status_code))
    theirs = await fresh(headers=s2, customer=other_cust)
    r = await c.post(f"/price-requests/{theirs}/note", headers=s1,
                     json={"text": "not my request"})
    check("a rep cannot write on another rep's customer", r.status_code == 403,
          str(r.status_code))
    r = await c.post(f"/price-requests/{uuid.uuid4()}/note", headers=s1,
                     json={"text": "nowhere"})
    check("...nor on one that does not exist", r.status_code == 404, str(r.status_code))

    # A note must not be mistaken for a line-item edit: the pricing is
    # untouched and no approval is filed off the back of it.
    before = J(await c.get(f"/price-requests/{pr}", headers=d))
    await c.post(f"/price-requests/{pr}/note", headers=s1, json={"text": "another"})
    after = J(await c.get(f"/price-requests/{pr}", headers=d))
    check("a note changes no price", after["items"] == before["items"],
          "items moved")
    check("...and does not knock the request back", after["status"] == before["status"],
          after["status"])

    audit = J(await c.get("/audit", headers=d, params={"entity": "price_request",
                                                       "limit": 50}))
    rows = audit if isinstance(audit, list) else audit.get("data", [])
    check("and the note is in the audit log",
          any(a.get("action") == "note" for a in rows))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        sys.exit(1)


asyncio.run(main())

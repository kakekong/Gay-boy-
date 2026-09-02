"""A reworded line keeps its price, and the quotation follows the request.

Two faults, one cause: the price request and the things made from it were
matched by what the lines *said* rather than by which line they were.

Renaming a line reset its price. `_norm_items` paired old lines to new ones by
description, so correcting a typo in a product name — the most ordinary edit
there is — read as "this is a different item" and blanked the cost and the
approved selling price. Sales fixed a spelling and watched two days of
purchasing work go to zero, with nothing on the screen saying why.

And a quotation built from a request never heard about it again. The page said
so outright, which was honest and useless: the customer got the old wording,
the old quantity and the old price, and only somebody reading both documents
would ever find out.

So: lines are identified by `line_no`, and a change to the request reaches the
quotation — rewritten while it is still a draft nobody has acted on, and left
alone but *flagged* once it has been submitted or sent, because a quotation in
a customer's hands must not silently become a different number. That last rule
is the one worth the test; syncing everything would be easier to write and
would eventually rewrite a figure under somebody's signature.
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

    async def costed(label, lines=1):
        """A request costed and approved, ready to become a quotation."""
        cust = J(await c.post("/customers", headers=s1, json={
            "company_name": f"PT {label} {TAG}", "industry": "mining"}))["id"]
        items = [{"description": f"Rotor {label} {TAG}", "qty": 4, "uom": "pcs"}]
        if lines > 1:
            items.append({"description": f"Shaft {label} {TAG}", "qty": 2,
                          "uom": "pcs"})
        pr = J(await c.post("/price-requests", headers=s1,
                            json={"customer_id": cust, "items": items}))
        await c.post(f"/price-requests/{pr['id']}/submit", headers=s1)
        await c.post(f"/price-requests/{pr['id']}/price", headers=pur, json={
            "items": [{"line_no": i + 1, "cost_price": 500_000, "basis": "unit"}
                      for i in range(lines)]})
        await c.post(f"/price-requests/{pr['id']}/approve", headers=d, json={
            "items": [{"line_no": i + 1, "sell_price": 1_000_000, "basis": "unit"}
                      for i in range(lines)]})
        return cust, pr["id"]

    # ══ a reworded line keeps its price ══════════════════════════════════
    print("\n── sales fixes a spelling ──")
    cust, pr_id = await costed("Ejaan")
    pr = J(await c.get(f"/price-requests/{pr_id}", headers=d))
    check("the line is costed and priced",
          float(pr["items"][0]["cost_price"]) == 500_000
          and float(pr["items"][0]["sell_price"]) == 1_000_000,
          str(pr["items"][0])[:200])

    # The director is the only one who may edit a request this far along —
    # which is exactly when there are prices to lose.
    r = await c.patch(f"/price-requests/{pr_id}", headers=d, json={
        "items": [{"line_no": 1, "description": f"Rotor & Shaft {TAG}",
                   "qty": 4, "uom": "pcs"}]})
    check("the description can be corrected", r.status_code == 200,
          f"{r.status_code} {why(r)}")
    pr = J(await c.get(f"/price-requests/{pr_id}", headers=d))
    check("...and it took", pr["items"][0]["description"] == f"Rotor & Shaft {TAG}",
          str(pr["items"][0].get("description")))
    check("...without resetting the cost",
          float(pr["items"][0]["cost_price"] or 0) == 500_000,
          str(pr["items"][0].get("cost_price")))
    check("...or the approved selling price",
          float(pr["items"][0]["sell_price"] or 0) == 1_000_000,
          str(pr["items"][0].get("sell_price")))
    check("...and the provenance of the cost survives too",
          pr["items"][0].get("cost_source") is not None
          or pr["items"][0].get("cost_basis") is not None,
          str(pr["items"][0])[:220])

    # A genuinely new line has no line_no, and starts unpriced — that half of
    # the old rule was right and must not be lost.
    r = await c.patch(f"/price-requests/{pr_id}", headers=d, json={
        "items": [{"line_no": 1, "description": f"Rotor & Shaft {TAG}",
                   "qty": 4, "uom": "pcs"},
                  {"description": f"Bearing {TAG}", "qty": 8, "uom": "pcs"}]})
    check("a line added alongside is accepted", r.status_code == 200,
          f"{r.status_code} {why(r)}")
    pr = J(await c.get(f"/price-requests/{pr_id}", headers=d))
    check("...the old line still priced",
          float(pr["items"][0]["sell_price"] or 0) == 1_000_000,
          str(pr["items"][0].get("sell_price")))
    check("...and the new one is not — nobody has quoted it",
          pr["items"][1].get("cost_price") in (None, "")
          and pr["items"][1].get("sell_price") in (None, ""),
          str(pr["items"][1])[:200])

    # Dropping a line must not shuffle prices onto its neighbour.
    r = await c.patch(f"/price-requests/{pr_id}", headers=d, json={
        "items": [{"line_no": 2, "description": f"Bearing {TAG}", "qty": 8,
                   "uom": "pcs"}]})
    check("the priced line can be removed", r.status_code == 200,
          f"{r.status_code} {why(r)}")
    pr = J(await c.get(f"/price-requests/{pr_id}", headers=d))
    check("...and the survivor keeps its own emptiness, not the dead line's price",
          len(pr["items"]) == 1
          and pr["items"][0]["description"] == f"Bearing {TAG}"
          and pr["items"][0].get("sell_price") in (None, ""),
          str(pr["items"])[:250])

    # ══ the quotation follows the request ════════════════════════════════
    print("\n── a draft quotation is brought into line ──")
    cust2, pr2 = await costed("Ikut", lines=2)
    q = J(await c.post(f"/quotations/from-price-request/{pr2}", headers=s1))
    q_id = q["id"]
    check("a quotation is made from it", bool(q_id), str(q)[:200])
    check("...at the approved price", float(q["total"] or 0) > 0, str(q.get("total")))
    before_total = float(q["total"])

    r = await c.patch(f"/price-requests/{pr2}", headers=d, json={
        "items": [{"line_no": 1, "description": f"Rotor Ikut {TAG} rev B",
                   "qty": 10, "uom": "pcs"},
                  {"line_no": 2, "description": f"Shaft Ikut {TAG}", "qty": 2,
                   "uom": "pcs"}]})
    check("the request is changed", r.status_code == 200, f"{r.status_code} {why(r)}")
    check("...and says it reached the quotation",
          J(r).get("quotations") and J(r)["quotations"][0]["synced"] is True,
          str(J(r).get("quotations"))[:250])

    q = J(await c.get(f"/quotations/{q_id}", headers=s1))
    line1 = next((x for x in q["items"] if int(x["line_no"]) == 1), None)
    check("the quotation's wording followed",
          line1 and line1["description"] == f"Rotor Ikut {TAG} rev B",
          str(line1)[:200])
    check("...and its quantity", line1 and float(line1["qty"]) == 10,
          str(line1 and line1.get("qty")))
    check("...so the total is the new one, not the old",
          float(q["total"]) != before_total and float(q["total"]) > 0,
          f"{q['total']} vs {before_total}")
    check("...still a draft — following a request is not submitting it",
          q["status"] == "draft", str(q.get("status")))

    # Moving the price on an approved request goes through reprice — the
    # route that insists on a reason. It is the sharpest case for the
    # quotation, whose line prices ARE those numbers.
    r = await c.post(f"/price-requests/{pr2}/reprice", headers=d, json={
        "items": [{"line_no": 1, "sell_price": 1_500_000, "sell_basis": "unit"}],
        "reason": "supplier raised the price"})
    check("the director moves the approved price", r.status_code == 200,
          f"{r.status_code} {why(r)}")
    q = J(await c.get(f"/quotations/{q_id}", headers=s1))
    line1 = next((x for x in q["items"] if int(x["line_no"]) == 1), None)
    check("...and the quotation carries it",
          line1 and float(line1["unit_price"]) == 1_500_000,
          str(line1 and line1.get("unit_price")))
    check("...its total following with it",
          float(q["total"]) > 0, str(q.get("total")))

    # ══ but not one that has gone out ════════════════════════════════════
    print("\n── a quotation the customer may be holding ──")
    cust3, pr3 = await costed("Kirim")
    q3 = J(await c.post(f"/quotations/from-price-request/{pr3}", headers=s1))
    q3_id = q3["id"]
    await c.post(f"/quotations/{q3_id}/submit", headers=s1)
    r = await c.post(f"/quotations/{q3_id}/approve", headers=d, json={"notes": ""})
    check("the quotation is approved and out of sales' hands",
          r.status_code == 200, f"{r.status_code} {why(r)}")
    sent_total = float(J(await c.get(f"/quotations/{q3_id}", headers=s1))["total"])

    r = await c.patch(f"/price-requests/{pr3}", headers=d, json={
        "items": [{"line_no": 1, "description": f"Rotor Kirim {TAG}", "qty": 40,
                   "uom": "pcs"}]})
    check("the request can still be changed", r.status_code == 200,
          f"{r.status_code} {why(r)}")
    rep = (J(r).get("quotations") or [{}])[0]
    check("...but the quotation is reported as left alone",
          rep.get("synced") is False, str(rep)[:250])

    q3 = J(await c.get(f"/quotations/{q3_id}", headers=s1))
    check("...its figure is untouched", float(q3["total"]) == sent_total,
          f"{q3['total']} vs {sent_total}")
    check("...its line is untouched too",
          float(q3["items"][0]["qty"]) == 4, str(q3["items"][0].get("qty")))
    check("...and it says on the quotation that the request moved",
          "changed after this quotation was" in (q3.get("notes") or ""),
          str(q3.get("notes"))[:300])
    check("...naming both figures, so somebody can decide",
          "against the" in (q3.get("notes") or ""), str(q3.get("notes"))[:300])

    # Changing it twice must not paper the quotation with the same note.
    await c.patch(f"/price-requests/{pr3}", headers=d, json={
        "items": [{"line_no": 1, "description": f"Rotor Kirim {TAG}", "qty": 40,
                   "uom": "pcs"}]})
    q3b = J(await c.get(f"/quotations/{q3_id}", headers=s1))
    check("...and the same warning is not written twice",
          (q3b.get("notes") or "").count("changed after this quotation was") == 1,
          str(q3b.get("notes"))[:300])

    # ══ nothing said, nothing done ═══════════════════════════════════════
    print("\n── an edit that changes nothing ──")
    q_before = J(await c.get(f"/quotations/{q_id}", headers=s1))
    r = await c.patch(f"/price-requests/{pr2}", headers=d, json={"notes": "just a note"})
    check("a notes-only edit does not touch the quotation's lines",
          not J(r).get("quotations"), str(J(r).get("quotations"))[:200])
    q_after = J(await c.get(f"/quotations/{q_id}", headers=s1))
    check("...and its total is where it was",
          float(q_after["total"]) == float(q_before["total"]),
          f"{q_after['total']} vs {q_before['total']}")

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)


asyncio.run(main())

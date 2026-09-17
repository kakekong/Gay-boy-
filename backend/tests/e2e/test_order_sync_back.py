"""The deal changes; the order behind it follows — and the supplier is asked.

Sync ran one way. A price request changed and the quotation built from it
followed, which covered the case where the *request* is edited. It is not the
case that happens: the deal is negotiated on the quotation. The customer wants
four more of item eight, a price moves on a call, a line gets reworded to the
name they use. All of that lands on the quotation, and the price request it
came from went on saying what was asked for a fortnight ago.

That is not a filing problem. The price request is what purchasing buys
against and what the project page shows as the order being fulfilled, so a
stale one puts the wrong quantity in front of a supplier and the wrong job on
the floor — with two screens describing the same order differently and nothing
saying which is current. That is what this fixes, and the shape of the fix is
three different answers to "who is already holding a copy":

  * **quotation → price request** happens on its own. Nobody outside the
    company reads a price request, and a line change on a PR-backed quotation
    has already been through the director — sales cannot make one at all.
  * **price request → supplier request** is a button. The vendor has been sent
    a list and may have priced it; rewriting that under them would make their
    answer say something they never agreed to. So the drift is reported and
    purchasing presses when they mean it.
  * **the project** needs nothing, because its order card reads the request
    live. Its button is for the jobs that were already running before any of
    this existed.

The last two are the ones worth the test, because "it does nothing on its own"
is indistinguishable from "it is broken" unless something pins it.
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
    adm = await login("admin@demo.local")

    async def pr_of(pr_id, hdr=None):
        return J(await c.get(f"/price-requests/{pr_id}", headers=hdr or d))
    def line(doc, no):
        for it in (doc.get("items") or []):
            if int(it.get("line_no") or 0) == no:
                return it
        return {}

    # ══ a deal, quoted ═══════════════════════════════════════════════════
    print("\n── an approved request with a quotation on it ──")
    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Selaras {TAG}", "industry": "mining"}))["id"]
    pr = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [
            {"description": f"ROLLER CHAIN RS 80 {TAG}", "qty": 28, "uom": "roll"},
            {"description": f"SPROCKET RS 100 {TAG}", "qty": 8, "uom": "pcs"},
            {"description": f"CONNECTING LINK RS 60 {TAG}", "qty": 5, "uom": "pcs"},
        ]}))["id"]
    await c.post(f"/price-requests/{pr}/submit", headers=s1)
    await c.post(f"/price-requests/{pr}/price", headers=d, json={"items": [
        {"line_no": 1, "cost_price": 380_000, "basis": "unit"},
        {"line_no": 2, "cost_price": 365_000, "basis": "unit"},
        {"line_no": 3, "cost_price": 10_000, "basis": "unit"}]})
    await c.post(f"/price-requests/{pr}/approve", headers=d, json={"items": [
        {"line_no": 1, "sell_price": 500_000, "basis": "unit"},
        {"line_no": 2, "sell_price": 500_000, "basis": "unit"},
        {"line_no": 3, "sell_price": 20_000, "basis": "unit"}]})
    q = J(await c.post(f"/quotations/from-price-request/{pr}", headers=s1))["id"]
    got = J(await c.get(f"/quotations/{q}", headers=d))
    check("the quotation carries the request's lines",
          len(got.get("items") or []) == 3, str(len(got.get("items") or [])))

    # ══ the deal moves, on the quotation ═════════════════════════════════
    print("\n── the customer changes their mind, on the quotation ──")
    items = [dict(i) for i in got["items"]]
    for it in items:
        it.pop("id", None); it.pop("line_total", None)
    items[1]["qty"] = 10                     # two more sprockets
    items[2]["unit_price"] = 25_000          # a price moves
    items[0]["description"] = f"ROLLER CHAIN RS 80 x 1L {TAG}"   # reworded
    r = await c.patch(f"/quotations/{q}", headers=d, json={"items": items})
    check("the director edits the quotation", r.status_code == 200,
          f"{r.status_code} {why(r)}")

    back = await pr_of(pr)
    check("the request hears about the quantity",
          float(line(back, 2).get("qty") or 0) == 10, str(line(back, 2).get("qty")))
    check("...and the price", float(line(back, 3).get("sell_price") or 0) == 25_000,
          str(line(back, 3).get("sell_price")))
    check("...and the rewording", "x 1L" in str(line(back, 1).get("description")),
          str(line(back, 1).get("description")))
    check("...while purchasing's cost is left exactly where they put it",
          float(line(back, 2).get("cost_price") or 0) == 365_000,
          str(line(back, 2).get("cost_price")))
    check("...and the request says why it changed",
          "quotation" in str(back.get("notes") or "").lower(),
          str(back.get("notes"))[:160])

    print("\n── a line added on the quotation joins the request ──")
    items = [dict(i) for i in J(await c.get(f"/quotations/{q}", headers=d))["items"]]
    for it in items:
        it.pop("id", None); it.pop("line_total", None)
    items.append({"line_no": 4, "description": f"BELT CONVEYOR {TAG}", "qty": 138,
                  "uom": "meter", "unit_price": 900_000})
    r = await c.patch(f"/quotations/{q}", headers=d, json={"items": items})
    check("the fourth line is accepted", r.status_code == 200, f"{r.status_code} {why(r)}")
    back = await pr_of(pr)
    check("...and reaches the request", len(back.get("items") or []) == 4,
          str(len(back.get("items") or [])))
    check("...with no cost on it, because nobody has been asked yet",
          line(back, 4).get("cost_price") in (None, 0),
          str(line(back, 4).get("cost_price")))

    # ══ the supplier request does NOT move on its own ════════════════════
    print("\n── the supplier is holding the old list, and keeps holding it ──")
    sup = J(await c.post("/purchasing/suppliers", headers=pur, json={
        "name": f"PT Rantai {TAG}", "category": "fabrication"}))["id"]
    spr = J(await c.post("/purchasing/price-requests", headers=pur, json={
        "price_request_id": pr, "supplier_ids": [sup]}))
    spr = (spr if isinstance(spr, list) else spr.get("created") or [spr])[0]
    spr_id = spr["id"]
    check("purchasing asks a vendor", bool(spr_id), str(spr)[:160])
    check("...for every line the request has now",
          len(spr.get("items") or []) == 4, str(len(spr.get("items") or [])))

    # now move the deal again, after the vendor has the list
    items = [dict(i) for i in J(await c.get(f"/quotations/{q}", headers=d))["items"]]
    for it in items:
        it.pop("id", None); it.pop("line_total", None)
    items[0]["qty"] = 40
    items[1]["description"] = f"SPROCKET RS 100 X 22T {TAG}"
    await c.patch(f"/quotations/{q}", headers=d, json={"items": items})
    await c.post(f"/purchasing/price-requests/{spr_id}/send", headers=pur)

    got = J(await c.get(f"/purchasing/price-requests/{spr_id}", headers=pur))
    sline = next((i for i in got["items"] if int(i.get("source_line_no") or 0) == 1), {})
    check("the vendor's list still says what it said when it was sent",
          float(sline.get("qty") or 0) == 28, str(sline.get("qty")))
    check("...but the request says so, line by line",
          any(x.get("change") == "differs" for x in got.get("source_drift") or []),
          str(got.get("source_drift"))[:220])
    drift1 = next((x for x in got["source_drift"] if x["line_no"] == 1), {})
    check("...naming the field and both figures",
          any(f["field"] == "qty" and f["on_request"] == 28 and f["on_source"] == 40
              for f in drift1.get("fields") or []), str(drift1)[:200])
    check("...and offers the button", got.get("may_refresh") is True,
          str(got.get("may_refresh")))

    print("\n── purchasing presses it ──")
    r = await c.post(f"/purchasing/price-requests/{spr_id}/refresh-from-source",
                     headers=pur, json={})
    check("the refresh runs", r.status_code == 200, f"{r.status_code} {why(r)}")
    body = J(r)
    check("...and says what it moved", body.get("changed") is True
          and len(body.get("updated") or []) >= 2, str(body)[:220])
    got = J(await c.get(f"/purchasing/price-requests/{spr_id}", headers=pur))
    sline = next((i for i in got["items"] if int(i.get("source_line_no") or 0) == 1), {})
    check("...the vendor's list now matches the order",
          float(sline.get("qty") or 0) == 40, str(sline.get("qty")))
    check("...with nothing left drifting", not got.get("source_drift"),
          str(got.get("source_drift"))[:200])
    check("...and a note on the record saying it was refreshed",
          "refreshed from" in str(got.get("notes") or "").lower(),
          str(got.get("notes"))[:160])

    r = await c.post(f"/purchasing/price-requests/{spr_id}/refresh-from-source",
                     headers=pur, json={})
    check("pressing it again is honest about finding nothing",
          r.status_code == 200 and J(r).get("changed") is False, str(J(r))[:160])

    print("\n── what the supplier said is kept ──")
    await c.post(f"/purchasing/price-requests/{spr_id}/quote", headers=pur, json={
        "items": [{"line_no": i["line_no"], "quoted_price": 100_000,
                   "quoted_basis": "unit"} for i in got["items"]]})
    items = [dict(i) for i in J(await c.get(f"/quotations/{q}", headers=d))["items"]]
    for it in items:
        it.pop("id", None); it.pop("line_total", None)
    items[0]["qty"] = 44
    await c.patch(f"/quotations/{q}", headers=d, json={"items": items})
    r = await c.post(f"/purchasing/price-requests/{spr_id}/refresh-from-source",
                     headers=pur, json={})
    check("an answered request can still be brought up to date",
          r.status_code == 200 and J(r).get("changed") is True,
          f"{r.status_code} {str(J(r))[:160]}")
    got = J(await c.get(f"/purchasing/price-requests/{spr_id}", headers=pur))
    sline = next((i for i in got["items"] if int(i.get("source_line_no") or 0) == 1), {})
    check("...the quantity follows", float(sline.get("qty") or 0) == 44,
          str(sline.get("qty")))
    check("...and the price they quoted is still theirs",
          float(sline.get("quoted_price") or 0) == 100_000,
          str(sline.get("quoted_price")))

    print("\n── and a finished one is left as the record it is ──")
    await c.post(f"/purchasing/price-requests/{spr_id}/close", headers=pur, json={})
    r = await c.post(f"/purchasing/price-requests/{spr_id}/refresh-from-source",
                     headers=pur, json={})
    check("a closed request refuses the refresh", r.status_code == 409,
          f"{r.status_code} {why(r)}")

    # ══ the project ══════════════════════════════════════════════════════
    print("\n── the project, whose card reads the request live ──")
    # The deal has to be on the table before a PO can be filed against it —
    # and an approved quotation is also the path where a line edit needs the
    # director, which is the path the sync has to survive.
    await c.post(f"/quotations/{q}/submit", headers=s1)
    await c.post(f"/quotations/{q}/approve", headers=d, json={"notes": ""})
    _r = await c.post("/customer-pos", headers=s1, json={
        "customer_id": cust, "quotation_id": q, "number": f"PO-SYNC-{TAG}",
        "items": [{"description": f"ROLLER CHAIN RS 80 {TAG}", "qty": 44,
                   "unit_price": 500_000}],
        "is_downpayment": False})
    check("a customer PO can be filed against the quotation",
          _r.status_code in (200, 201), f"{_r.status_code} {why(_r)}")
    cpo = J(_r)["id"]
    await c.post(f"/quotations/{q}/won", headers=d)
    proj = J(await c.post(f"/customer-pos/{cpo}/approve", headers=d,
                          json={"notes": ""}))["project_id"]
    full = J(await c.get(f"/operation/projects/{proj}/full", headers=d))
    card = (full.get("project") or {}).get("price_request") or full.get("price_request") or {}
    check("the order card names the quotation it should agree with",
          card.get("quotation_number"), str(card)[:200])
    check("...and reports no drift, because the sync already happened",
          not card.get("drift"), str(card.get("drift"))[:200])
    check("...showing the quantity as the deal has it",
          any(float(i.get("qty") or 0) == 44 for i in card.get("items") or []),
          str(card.get("items"))[:200])

    r = await c.post(f"/operation/projects/{proj}/sync-order", headers=d)
    check("the button says there was nothing to do", r.status_code == 200
          and J(r).get("changed") is False, f"{r.status_code} {str(J(r))[:160]}")

    # Drift the pair by hand, the way a job running before any of this would
    # already be, and check the button earns its place.
    from app.core.db import SessionLocal
    from sqlalchemy import select as _sel
    from app.models.price_request import PriceRequest as _PR
    async with SessionLocal() as db:
        row = await db.scalar(_sel(_PR).where(_PR.id == uuid.UUID(pr)))
        stale = [dict(i) for i in row.items]
        stale[0]["qty"] = 4
        row.items = stale
        await db.commit()
    full = J(await c.get(f"/operation/projects/{proj}/full", headers=d))
    card = (full.get("project") or {}).get("price_request") or full.get("price_request") or {}
    check("an order that has fallen behind says so on the card",
          any(x.get("change") == "differs" for x in card.get("drift") or []),
          str(card.get("drift"))[:220])

    r = await c.post(f"/operation/projects/{proj}/sync-order", headers=adm)
    check("admin cannot declare what the order is", r.status_code == 403,
          f"HTTP{r.status_code}")
    r = await c.post(f"/operation/projects/{proj}/sync-order", headers=d)
    check("the director can", r.status_code == 200 and J(r).get("changed") is True,
          f"{r.status_code} {str(J(r))[:160]}")
    check("...and is pointed at the supplier requests that will not have noticed",
          isinstance(J(r).get("supplier_requests_to_review"), list),
          str(J(r))[:220])
    full = J(await c.get(f"/operation/projects/{proj}/full", headers=d))
    card = (full.get("project") or {}).get("price_request") or full.get("price_request") or {}
    check("...leaving the card matching the deal again", not card.get("drift"),
          str(card.get("drift"))[:200])

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)


asyncio.run(main())

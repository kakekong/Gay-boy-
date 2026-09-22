"""Global search: does the thing you remember actually find the document?

Two complaints drove this, and they are both about reach rather than ranking.

**"I search a PR number and nothing comes up."** Price requests were not in
the search endpoint at all — nor customer POs, supplier POs, supplier price
requests, invoices or suppliers. Six document types you could not find by
number. And a number is never typed the way it is stored: people write
`PR 2026 0012` or `pr-2026-0012` or paste `PR20260012` off a chat, so all of
those have to land on the same row.

**"I search a product name and it doesn't show everywhere it appears."**
Only headers were searched — numbers and notes — so a part number found an
inventory row and stopped. The lines are the point: the same item travels
from a price request to a quotation to a customer PO to a supplier PO, and
searching its name should surface that whole trail. The lines live in two
different shapes (JSONB arrays on most documents, a real table on
quotations), which is exactly the kind of split that gets half-implemented,
so both are pinned here.

The third thing this guards is scope. Search is a way to reach a page, so a
result nobody can open is a bug: a sales rep must not be offered another
rep's price request, and must not be offered supplier pricing at all.
"""
import asyncio, os, sys, uuid
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123",
    STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import httpx, logging; logging.disable(logging.INFO)
TAG = uuid.uuid4().hex[:6].upper()
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
    pur = await login("purchasing@demo.local")
    adm = await login("admin@demo.local")

    async def find(term, hdr=d):
        r = await c.get("/search", headers=hdr, params={"q": term})
        return J(r) if r.status_code == 200 else {"_status": r.status_code,
                                                 "_why": why(r), "groups": []}
    def group(res, label):
        return next((g for g in res.get("groups", []) if g["label"] == label), None)
    def labels(res, label):
        g = group(res, label)
        return [i["label"] for i in (g or {}).get("items", [])]
    def item(res, label, needle):
        g = group(res, label) or {"items": []}
        return next((i for i in g["items"] if needle in (i.get("label") or "")), None)
    def all_group_names(res):
        return [g["label"] for g in res.get("groups", [])]

    # A part number nobody else will have, carried down the whole chain.
    PART = f"SHACKLE-GX{TAG}"

    # ══ build one job, end to end ════════════════════════════════════════
    print("\n── a job with one distinctive part on every document ──")
    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Cari {TAG}", "industry": "mining"}))["id"]
    pr = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [{"description": PART, "qty": 12, "uom": "pcs"}]}))
    pr_id, pr_no = pr["id"], pr["number"]
    print(f"   price request {pr_no}")
    await c.post(f"/price-requests/{pr_id}/submit", headers=s1)
    await c.post(f"/price-requests/{pr_id}/price", headers=d, json={
        "items": [{"line_no": 1, "cost_price": 500_000, "basis": "unit"}]})
    await c.post(f"/price-requests/{pr_id}/approve", headers=d, json={
        "items": [{"line_no": 1, "sell_price": 1_000_000, "basis": "unit"}]})
    quote = J(await c.post(f"/quotations/from-price-request/{pr_id}", headers=s1))
    q_id, q_no = quote["id"], quote["number"]
    await c.post(f"/quotations/{q_id}/submit", headers=s1)
    await c.post(f"/quotations/{q_id}/approve", headers=d, json={"notes": ""})
    cpo = J(await c.post("/customer-pos", headers=s1, json={
        "customer_id": cust, "quotation_id": q_id, "number": f"PO-CARI-{TAG}",
        "items": [{"description": PART, "qty": 12, "unit_price": 1_000_000}],
        "is_downpayment": False}))
    cpo_id, cpo_no = cpo["id"], cpo["number"]
    await c.post(f"/quotations/{q_id}/won", headers=d)
    proj_id = J(await c.post(f"/customer-pos/{cpo_id}/approve", headers=d,
                             json={"notes": ""}))["project_id"]
    proj = J(await c.get(f"/operation/projects/{proj_id}", headers=d))
    proj_code = proj.get("code")

    # ══ the number, however it is typed ══════════════════════════════════
    print("\n── a price request, found by its number ──")
    res = await find(pr_no)
    check("a price request is in the search results at all",
          bool(item(res, "Price requests", pr_no)),
          str(all_group_names(res)))
    hit = item(res, "Price requests", pr_no) or {}
    check("...and links to the price request, not just the list",
          str(pr_id) in (hit.get("link") or ""), str(hit.get("link")))

    squashed = pr_no.replace("-", "")
    spaced = pr_no.replace("-", " ")
    lowered = pr_no.lower()
    for variant, story in [
        (squashed, "pasted with the dashes gone"),
        (spaced, "typed with spaces instead of dashes"),
        (lowered, "typed in lower case"),
        (pr_no.split("-")[-1], "only the tail somebody read out"),
    ]:
        res = await find(variant)
        check(f"...found when it is {story} ({variant})",
              bool(item(res, "Price requests", pr_no)),
              str(labels(res, "Price requests")))

    # ══ one part name, every document it is on ═══════════════════════════
    print("\n── a part number finds the whole trail ──")
    res = await find(PART)
    for label, number in [
        ("Price requests", pr_no),
        ("Quotations", q_no),
        ("Customer POs", cpo_no),
    ]:
        check(f"searching the part name finds the {label[:-1].lower()} it is on",
              bool(item(res, label, number)),
              f"{label}: {labels(res, label)}")

    hit = item(res, "Price requests", pr_no) or {}
    check("...and the result says WHICH line matched, so the hit is explicable",
          PART in (hit.get("sublabel") or ""), str(hit.get("sublabel")))
    check("...including the quantity and unit off that line",
          "12 pcs" in (hit.get("sublabel") or ""), str(hit.get("sublabel")))
    qhit = item(res, "Quotations", q_no) or {}
    check("the quotation hit names its matching line too — lines live in a "
          "different table there, and that half is easy to forget",
          PART in (qhit.get("sublabel") or ""), str(qhit.get("sublabel")))

    # Part of a name is enough — nobody types the whole SKU.
    res = await find(f"SHACKLE-GX{TAG[:3]}")
    check("half a part number is enough to find it",
          bool(item(res, "Price requests", pr_no)),
          str(labels(res, "Price requests")))

    # ══ documents that were missing entirely ═════════════════════════════
    print("\n── the document types search could not reach before ──")
    res = await find(cpo_no)
    check("a customer PO is findable by its number",
          bool(item(res, "Customer POs", cpo_no)), str(all_group_names(res)))

    res = await find(proj_code)
    hit = item(res, "Projects", proj_code) or {}
    check("a project is findable by its code", bool(hit), str(all_group_names(res)))
    check("...and its link opens THAT project rather than the project list",
          (hit.get("link") or "").rstrip("/") != "/projects"
          and str(proj_id) in (hit.get("link") or ""),
          str(hit.get("link")))

    # An invoice, once there is one.
    await c.post(f"/operation/projects/{proj_id}/qc", headers=adm,
                 json={"decision": "pass"})
    await c.post(f"/operation/projects/{proj_id}/issue-invoice", headers=d,
                 data={"invoice_type": "single"})
    from app.core.db import SessionLocal
    from sqlalchemy import select as _sel
    from app.models.finance import Invoice as _Inv
    async with SessionLocal() as db:
        inv = await db.scalar(_sel(_Inv).where(_Inv.project_id == proj_id)
                              .order_by(_Inv.created_at.desc()))
        inv_id, inv_no = str(inv.id), inv.number
    fp_no = f"FP-CARI-{TAG}"
    await c.post(f"/finance/invoices/{inv_id}/approve", headers=fin,
                 data={"faktur_pajak_no": fp_no})

    res = await find(inv_no, fin)
    check("finance can find an invoice by its number",
          bool(item(res, "Invoices", inv_no)), str(all_group_names(res)))
    res = await find(fp_no, fin)
    check("...and by its faktur pajak number, which is what the tax office "
          "quotes back at you",
          bool(item(res, "Invoices", inv_no)), str(labels(res, "Invoices")))

    # A supplier, and the price request sent to them.
    sup = J(await c.post("/purchasing/suppliers", headers=d, json={
        "name": f"PT Pemasok {TAG}", "category": "rigging"}))
    sup_id, sup_name = sup["id"], sup["name"]
    res = await find(f"Pemasok {TAG}", pur)
    check("a supplier is findable by name",
          bool(item(res, "Suppliers", sup_name)), str(all_group_names(res)))
    hit = item(res, "Suppliers", sup_name) or {}
    check("...and links to their page", str(sup_id) in (hit.get("link") or ""),
          str(hit.get("link")))

    spr = J(await c.post("/purchasing/price-requests", headers=d, json={
        "price_request_id": pr_id, "supplier_ids": [sup_id]}))
    spr_row = spr[0] if isinstance(spr, list) and spr else spr
    spr_no = (spr_row or {}).get("number")
    check("a supplier price request was raised to search for", bool(spr_no),
          str(spr)[:180])
    if spr_no:
        res = await find(spr_no, pur)
        check("purchasing can find a supplier price request by number",
              bool(item(res, "Supplier price requests", spr_no)),
              str(all_group_names(res)))
        res = await find(PART, pur)
        check("...and the part name reaches it as well, so the buy side of "
              "the trail is searchable too",
              bool(item(res, "Supplier price requests", spr_no)),
              str(labels(res, "Supplier price requests")))

    # ══ the supplier's own page lists what we asked them ═════════════════
    print("\n── opening a supplier shows their price requests ──")
    page = J(await c.get(f"/purchasing/suppliers/{sup_id}", headers=pur))
    check("the supplier page carries a price-request list at all",
          isinstance(page.get("price_requests"), list),
          str(sorted(page.keys()))[:200])
    rows = page.get("price_requests") or []
    check("...holding the request we just sent them",
          any(x.get("number") == spr_no for x in rows),
          str([x.get("number") for x in rows]))
    row = next((x for x in rows if x.get("number") == spr_no), {})
    check("...saying what we asked about, so the row is recognisable",
          PART in (row.get("first_item") or ""), str(row.get("first_item")))
    check("...and how many lines it covers", row.get("line_count") == 1,
          str(row.get("line_count")))
    check("the page counts them", page.get("price_request_count") == len(rows),
          f'{page.get("price_request_count")} vs {len(rows)}')
    check("...and counts the ones still waiting on the supplier's price, "
          "which is the reason to open the page",
          page.get("awaiting_quote_count") ==
          len([x for x in rows if x.get("status") in ("draft", "sent")]),
          str(page.get("awaiting_quote_count")))
    check("an unanswered request shows no price rather than a zero",
          row.get("quoted_total") is None, str(row.get("quoted_total")))

    # A supplier nobody has asked anything gets an empty list, not a missing key.
    lonely = J(await c.post("/purchasing/suppliers", headers=d, json={
        "name": f"PT Sepi {TAG}", "category": "misc"}))["id"]
    empty = J(await c.get(f"/purchasing/suppliers/{lonely}", headers=pur))
    check("a supplier we have never asked anything reports an empty list",
          empty.get("price_requests") == []
          and empty.get("price_request_count") == 0,
          str(empty.get("price_requests")))

    # ══ scope: a result you cannot open is a bug ═════════════════════════
    print("\n── who is offered what ──")
    res = await find(pr_no, s1)
    check("the rep who raised the price request finds it",
          bool(item(res, "Price requests", pr_no)), str(all_group_names(res)))
    res = await find(pr_no, s2)
    check("another rep does not — it is not their customer",
          not item(res, "Price requests", pr_no),
          str(labels(res, "Price requests")))
    res = await find(PART, s2)
    check("...and the part name does not leak it to them either",
          not item(res, "Price requests", pr_no)
          and not item(res, "Customer POs", cpo_no),
          str(all_group_names(res)))

    res = await find(sup_name, s1)
    check("sales is not offered suppliers — the customer/supplier mapping is "
          "the director's",
          group(res, "Suppliers") is None, str(all_group_names(res)))
    if spr_no:
        res = await find(spr_no, s1)
        check("...nor supplier pricing", group(res, "Supplier price requests") is None,
              str(all_group_names(res)))

    res = await find(inv_no, s1)
    check("sales is not offered invoices", group(res, "Invoices") is None,
          str(all_group_names(res)))

    # ══ it still behaves ═════════════════════════════════════════════════
    print("\n── the ordinary cases ──")
    r = await c.get("/search", headers=d, params={"q": ""})
    check("an empty query returns nothing rather than everything",
          r.status_code == 200 and J(r).get("groups") == [], f"{r.status_code}")
    res = await find(f"zzz-nothing-{TAG}")
    check("a query that matches nothing returns no groups",
          res.get("groups") == [], str(all_group_names(res)))
    check("...and says so with a total", res.get("total") == 0, str(res.get("total")))
    res = await find(PART)
    check("a real query reports how many results it found",
          isinstance(res.get("total"), int) and res["total"] > 0,
          str(res.get("total")))

    # A query with the separator characters in it must not break the SQL.
    for weird in ["PR-", "-", "  ", "a/b", "#12", "50%", "it's"]:
        r = await c.get("/search", headers=d, params={"q": weird})
        check(f"a query of {weird!r} is answered, not an error",
              r.status_code == 200, f"{r.status_code} {why(r)}")

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    for f in FAIL:
        print("  ✗", f)


asyncio.run(main())

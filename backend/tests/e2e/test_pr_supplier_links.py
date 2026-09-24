"""A price request and the supplier requests raised off it are one click apart.

A price request is the customer side of a job, a supplier price request is the
vendor side, and the only way from one to the other used to be finding the
supplier request by number on the purchasing board. Now opening a price
request lists every supplier request drawn from it — who was asked, how far
along they are, and the price if it is in — and the supplier request links
back.

The things worth pinning are the ones that go wrong quietly:

* **Joint requests.** One vendor asked about several jobs at once has no
  single header link, so a lookup on the header misses it entirely — the
  supplier-request list filter did exactly that. And on a joint request only
  THIS job's lines may be counted and priced: the vendor's total for the
  whole basket says nothing about what this customer's items cost.
* **Partial quotes.** A total summed over half the lines reads as a cheap
  quote when it is an incomplete one, so it is withheld until every line has
  an answer.
* **Who sees it.** Which vendor serves which customer is the director's to
  know. Sales never gets the list; nor does anyone who could only bounce off
  the page it links to.
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
    pur = await login("purchasing@demo.local")
    s1 = await login("sales1@demo.local")
    fin = await login("finance@demo.local")
    mgr = await login("manager@demo.local")

    async def a_pr(tag, lines):
        cust = J(await c.post("/customers", headers=s1, json={
            "company_name": f"PT Tautan {tag}", "industry": "mining"}))["id"]
        pr = J(await c.post("/price-requests", headers=s1, json={
            "customer_id": cust,
            "items": [{"description": f"{name} {tag}", "qty": q, "uom": "pcs"}
                      for name, q in lines]}))
        await c.post(f"/price-requests/{pr['id']}/submit", headers=s1)
        return pr["id"], pr["number"]

    pr_id, pr_no = await a_pr(TAG, [("CHAIN", 10), ("SHACKLE", 4)])
    other_id, other_no = await a_pr(f"O{TAG}", [("SPROCKET", 2)])

    sup_a = J(await c.post("/purchasing/suppliers", headers=d, json={
        "name": f"PT Cepat {TAG}", "category": "chain"}))["id"]
    sup_b = J(await c.post("/purchasing/suppliers", headers=d, json={
        "name": f"Jiangsu Lambat {TAG}", "category": "chain"}))["id"]
    sup_c = J(await c.post("/purchasing/suppliers", headers=d, json={
        "name": f"PT Gabung {TAG}", "category": "chain"}))["id"]

    # Two suppliers asked about this job alone.
    made = J(await c.post("/purchasing/price-requests", headers=pur, json={
        "price_request_id": pr_id, "supplier_ids": [sup_a, sup_b]}))
    made = made if isinstance(made, list) else [made]
    by_sup = {m.get("supplier_id"): m for m in made}
    spr_a, spr_b = by_sup.get(sup_a), by_sup.get(sup_b)
    check("two supplier requests are raised off the price request",
          bool(spr_a and spr_b), str(made)[:200])

    # One vendor asked about both jobs in a single request.
    joint = J(await c.post("/purchasing/price-requests", headers=pur, json={
        "price_request_ids": [pr_id, other_id], "supplier_ids": [sup_c]}))
    joint = (joint if isinstance(joint, list) else [joint])[0]
    check("a joint request covering both jobs is raised",
          bool(joint.get("id")) and joint.get("is_joint") is True, str(joint)[:200])

    # Supplier A answers every line; supplier B answers only one.
    await c.post(f"/purchasing/price-requests/{spr_a['id']}/send", headers=pur)
    await c.post(f"/purchasing/price-requests/{spr_b['id']}/send", headers=pur)
    r = await c.post(f"/purchasing/price-requests/{spr_a['id']}/quote", headers=pur, json={
        "items": [{"line_no": 1, "quoted_price": 100.0},
                  {"line_no": 2, "quoted_price": 250.0}],
        "currency": "CNY", "fx_rate": 2200.0, "quoted_lead_days": 45})
    check("supplier A's full quote is recorded", r.status_code == 200,
          f"{r.status_code} {why(r)}")
    r = await c.post(f"/purchasing/price-requests/{spr_b['id']}/quote", headers=pur, json={
        "items": [{"line_no": 1, "quoted_price": 90.0}]})
    check("supplier B's partial quote is recorded", r.status_code == 200,
          f"{r.status_code} {why(r)}")

    # ══ opening the price request ════════════════════════════════════════
    print("\n── opening the price request ──")
    pr = J(await c.get(f"/price-requests/{pr_id}", headers=pur))
    links = pr.get("supplier_requests")
    check("the price request lists the supplier requests raised off it",
          isinstance(links, list), str(sorted(pr.keys()))[:200])
    links = links or []
    ids = {x["id"] for x in links}
    check("...both single-job requests are there",
          spr_a["id"] in ids and spr_b["id"] in ids, str(ids))
    check("...AND the joint one, which has no header link and used to be missed",
          joint.get("id") in ids, str(ids))

    a = next((x for x in links if x["id"] == spr_a["id"]), {})
    check("each row names the supplier", a.get("supplier_name") == f"PT Cepat {TAG}",
          str(a.get("supplier_name")))
    check("...and its number, to link by", a.get("number") == spr_a.get("number"),
          str(a.get("number")))
    check("...and how many lines are answered", (a.get("lines_quoted"), a.get("lines")) == (2, 2),
          f"{a.get('lines_quoted')}/{a.get('lines')}")
    check("...and the price, in the currency the vendor quoted in",
          a.get("currency") == "CNY"
          and abs(float(a.get("quoted_total") or 0) - (100 * 10 + 250 * 4)) < 0.01,
          f"{a.get('currency')} {a.get('quoted_total')}")
    check("...and their lead time", a.get("quoted_lead_days") == 45,
          str(a.get("quoted_lead_days")))

    b = next((x for x in links if x["id"] == spr_b["id"]), {})
    check("a half-answered quote shows how far along it is",
          (b.get("lines_quoted"), b.get("lines")) == (1, 2),
          f"{b.get('lines_quoted')}/{b.get('lines')}")
    check("...but NO total — a sum over half the lines reads as a cheap quote",
          b.get("quoted_total") is None, str(b.get("quoted_total")))

    j = next((x for x in links if x["id"] == joint.get("id")), {})
    check("the joint request is marked as covering other jobs too",
          j.get("is_joint") is True, str(j.get("is_joint")))
    check("...and counts only THIS job's lines, not the whole basket",
          j.get("lines") == 2, str(j.get("lines")))

    # The other job sees the joint request with its own single line.
    other = J(await c.get(f"/price-requests/{other_id}", headers=pur))
    oj = next((x for x in (other.get("supplier_requests") or [])
               if x["id"] == joint.get("id")), {})
    check("the other job sees the same joint request with ITS one line",
          oj.get("lines") == 1, str(oj.get("lines")))
    check("...and none of this job's single-supplier requests",
          not ({spr_a["id"], spr_b["id"]} & {x["id"] for x in (other.get("supplier_requests") or [])}),
          str([x["number"] for x in (other.get("supplier_requests") or [])]))

    # ══ the purchasing list, filtered by job ═════════════════════════════
    print("\n── the supplier-request list, filtered to one job ──")
    rows = J(await c.get("/purchasing/price-requests", headers=pur,
                         params={"price_request_id": pr_id}))
    got = {x["id"] for x in (rows if isinstance(rows, list) else [])}
    check("filtering by price request now finds the joint one too",
          joint.get("id") in got, str(got))
    check("...alongside the single-job ones",
          spr_a["id"] in got and spr_b["id"] in got, str(got))

    # ══ who gets the list ════════════════════════════════════════════════
    print("\n── who sees which vendor was asked ──")
    for hdr, who, should in [(d, "the director", True), (mgr, "a manager", True),
                             (pur, "purchasing", True)]:
        body = J(await c.get(f"/price-requests/{pr_id}", headers=hdr))
        check(f"{who} gets the supplier requests",
              isinstance(body.get("supplier_requests"), list), str(sorted(body.keys()))[:120])
    body = J(await c.get(f"/price-requests/{pr_id}", headers=s1))
    check("sales does NOT — which vendor serves their customer is not theirs to know",
          "supplier_requests" not in body, str(body.get("supplier_requests"))[:120])
    r = await c.get(f"/price-requests/{pr_id}", headers=fin)
    if r.status_code == 200:
        check("finance does not either — they cannot open the page it links to",
              "supplier_requests" not in J(r), str(J(r).get("supplier_requests"))[:120])

    # A job nobody has asked a supplier about yet answers with an empty list,
    # not a missing key — the screen says "not sent yet" rather than nothing.
    lone_id, _ = await a_pr(f"L{TAG}", [("BOLT", 1)])
    lone = J(await c.get(f"/price-requests/{lone_id}", headers=pur))
    check("a request no supplier has been asked about reports an empty list",
          lone.get("supplier_requests") == [], str(lone.get("supplier_requests")))

    # ══ the supplier page's price, while we are here ═════════════════════
    print("\n── the supplier's own page shows the price they gave ──")
    page = J(await c.get(f"/purchasing/suppliers/{sup_a}", headers=pur))
    row = next((x for x in (page.get("price_requests") or [])
                if x.get("id") == spr_a["id"]), {})
    check("an answered request shows the supplier's price on their page — it "
          "read the wrong field and always showed nothing",
          abs(float(row.get("quoted_total") or 0) - 2000.0) < 0.01,
          str(row.get("quoted_total")))
    page_b = J(await c.get(f"/purchasing/suppliers/{sup_b}", headers=pur))
    row_b = next((x for x in (page_b.get("price_requests") or [])
                  if x.get("id") == spr_b["id"]), {})
    check("...while a half-answered one still shows none",
          row_b.get("quoted_total") is None, str(row_b.get("quoted_total")))

    # ══ and back again ═══════════════════════════════════════════════════
    print("\n── from the supplier request back to the job ──")
    spr_page = J(await c.get(f"/purchasing/price-requests/{spr_a['id']}", headers=pur))
    srcs = spr_page.get("source_price_requests") or []
    check("the supplier request names the price request it came from, by id, "
          "so the page can link back",
          any(x.get("id") == pr_id and x.get("number") == pr_no for x in srcs)
          or spr_page.get("price_request_id") == pr_id,
          str(srcs)[:200])

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    for f in FAIL:
        print("  ✗", f)


asyncio.run(main())

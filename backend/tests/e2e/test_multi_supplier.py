"""One order, several suppliers — and one supplier, several orders.

Asked for, as two scenarios purchasing lives with and the system had no shape
for:

**Scenario 1 — several suppliers needed for one order.** Nobody makes the
whole basket. The chain comes from one vendor and the sprockets from another,
so asking either of them to quote the lot wastes everyone's time and produces
a price for goods they will not supply. Purchasing now picks which *lines*
each supplier is asked about.

**Scenario 2 — one supplier filling several orders.** Three customers' jobs
go to the same vendor and arrive on one truck, for tax and for sanity. That
is one conversation with the vendor, so it should be one request — but each
line still belongs to a different customer's job, and the price that comes
back has to find its way home to the right one.

Both rest on the same thing: **every line remembers where it came from**
(`source_pr_id` + `source_line_no`), so it survives being cut up and mixed
together. Once that holds, applying a quote is per-line, and the consequence
that matters falls out of it — a customer price request only goes up to the
director when *every* one of its lines has a cost. Half a job reaching a
margin decision is how a price gets set on a number nobody has.

Also here: the buy-side request now carries the discussion thread and the file
uploads the sell-side one has, so the vendor's quotation sheet lives on the
request it answers instead of in an inbox.
"""
import asyncio, io, os, sys, uuid
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

BASE = "/purchasing/price-requests"


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

    chain_sup = J(await c.post("/purchasing/suppliers", headers=pur, json={
        "name": f"PT Rantai {tag}", "category": "chain"}))["id"]
    sprocket_sup = J(await c.post("/purchasing/suppliers", headers=pur, json={
        "name": f"PT Sproket {tag}", "category": "machining"}))["id"]

    async def price_request(name: str, lines: list[tuple[str, float, str]]) -> dict:
        cust = J(await c.post("/customers", headers=s1, json={
            "company_name": f"PT {name} {tag}", "industry": "mining"}))["id"]
        pr = J(await c.post("/price-requests", headers=s1, json={
            "customer_id": cust,
            "items": [{"description": desc, "qty": qty, "uom": uom}
                      for desc, qty, uom in lines]}))
        await c.post(f"/price-requests/{pr['id']}/submit", headers=s1)
        return pr

    # ══ scenario 1: one job, two suppliers ═══════════════════════════════════
    print("\n── nobody makes the whole basket ──")
    job = await price_request("Tambang", [
        (f"CHAIN C-2122 {tag}", 40, "meter"),
        (f"SPROCKET 24T {tag}", 4, "pcs"),
        (f"BEARING 6205 {tag}", 8, "pcs"),
    ])

    r = await c.post(BASE, headers=pur, json={
        "price_request_id": job["id"],
        "assignments": [
            {"supplier_id": chain_sup, "lines": [
                {"price_request_id": job["id"], "line_no": 1}]},
            {"supplier_id": sprocket_sup, "lines": [
                {"price_request_id": job["id"], "line_no": 2},
                {"price_request_id": job["id"], "line_no": 3}]},
        ]})
    check("the job is split between two suppliers", r.status_code == 201,
          f"{r.status_code} {J(r)}"[:200])
    made = J(r)
    check("...one request each", len(made) == 2, str(len(made)))
    chain_req = next(x for x in made if x["supplier_id"] == chain_sup)
    sprk_req = next(x for x in made if x["supplier_id"] == sprocket_sup)
    check("the chain vendor is asked about one line",
          chain_req["lines_total"] == 1, str(chain_req["lines_total"]))
    check("...and it is the chain", f"CHAIN C-2122 {tag}"
          in str(chain_req["items"]), str(chain_req["items"])[:200])
    check("the other vendor gets the remaining two",
          sprk_req["lines_total"] == 2, str(sprk_req["lines_total"]))
    check("...renumbered from 1 for their own sheet",
          [i["line_no"] for i in sprk_req["items"]] == [1, 2],
          str([i["line_no"] for i in sprk_req["items"]]))
    check("...while each line still points home",
          [i["source_line_no"] for i in sprk_req["items"]] == [2, 3],
          str([i.get("source_line_no") for i in sprk_req["items"]]))
    check("...naming the request it came from",
          all(i["source_pr_number"] == job["number"] for i in sprk_req["items"]),
          str(sprk_req["items"])[:200])

    cov = J(await c.get(f"{BASE}/for-price-request/{job['id']}/coverage", headers=pur))
    check("coverage says all three lines are with somebody",
          cov["lines_asked"] == 3, str(cov["lines_asked"]))
    check("...and none of them is costed yet", cov["uncovered"] == [1, 2, 3],
          str(cov["uncovered"]))
    check("...so it is not ready for the director", cov["fully_costed"] is False)
    line1 = cov["lines"][0]
    check("...line 1 names the vendor holding it",
          line1["asked"] and f"PT Rantai {tag}" == line1["asked"][0]["supplier_name"],
          str(line1["asked"])[:200])

    # the chain vendor answers first
    await c.post(f"{BASE}/{chain_req['id']}/quote", headers=pur, json={
        "items": [{"line_no": 1, "quoted_price": 1_800_000}]})
    r = await c.post(f"{BASE}/{chain_req['id']}/apply", headers=pur)
    check("their half can be applied on its own", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:200])
    res = J(r)["price_requests"][0]
    check("...costing one line", res["applied_lines"] == 1, str(res))
    check("...and the job does NOT go to the director yet",
          res["status"] == "pending_purchasing", res["status"])
    check("...because two lines still have nobody's price",
          res["lines_still_uncosted"] == [2, 3], str(res["lines_still_uncosted"]))

    priced = J(await c.get(f"/price-requests/{job['id']}", headers=pur))
    check("the costed line carries its supplier's name",
          priced["items"][0].get("cost_supplier") == f"PT Rantai {tag}",
          str(priced["items"][0].get("cost_supplier")))
    check("...and the other two are still empty",
          priced["items"][1].get("cost_price") in (None, ""),
          str(priced["items"][1].get("cost_price")))

    # then the other one
    await c.post(f"{BASE}/{sprk_req['id']}/quote", headers=pur, json={
        "items": [{"line_no": 1, "quoted_price": 1_000_000},
                  {"line_no": 2, "quoted_price": 250_000}]})
    r = await c.post(f"{BASE}/{sprk_req['id']}/apply", headers=pur)
    res = J(r)["price_requests"][0]
    check("the second half completes it", res["applied_lines"] == 2, str(res))
    check("...and NOW it goes to the director",
          res["status"] == "pending_director", res["status"])
    check("...with nothing left uncosted", res["lines_still_uncosted"] == [],
          str(res["lines_still_uncosted"]))

    done = J(await c.get(f"/price-requests/{job['id']}", headers=pur))
    check("every line has its own supplier's price",
          [float(i["cost_price"]) for i in done["items"]]
          == [1_800_000, 1_000_000, 250_000],
          str([i.get("cost_price") for i in done["items"]]))
    check("...and the lines name different suppliers, which is the point",
          {i.get("cost_supplier") for i in done["items"]}
          == {f"PT Rantai {tag}", f"PT Sproket {tag}"},
          str({i.get("cost_supplier") for i in done["items"]}))

    check("both quotes stay marked as live — neither superseded the other",
          all(x["applied_at"] for x in
              J(await c.get(f"{BASE}/for-price-request/{job['id']}/compare",
                            headers=pur))["requests"]),
          str([(x["number"], x["applied_at"]) for x in
               J(await c.get(f"{BASE}/for-price-request/{job['id']}/compare",
                             headers=pur))["requests"]]))

    cov = J(await c.get(f"{BASE}/for-price-request/{job['id']}/coverage", headers=pur))
    check("coverage agrees it is complete", cov["fully_costed"] is True,
          str(cov["uncovered"]))

    # ══ scenario 2: three jobs, one supplier, one ask ════════════════════════
    print("\n── one vendor, three jobs, one shipment ──")
    a = await price_request("Semen", [(f"BOLT M12 {tag}", 100, "pcs")])
    b = await price_request("Kertas", [(f"NUT M12 {tag}", 100, "pcs"),
                                       (f"WASHER M12 {tag}", 200, "pcs")])
    e = await price_request("Kaca", [(f"PLATE 10MM {tag}", 5, "set")])

    r = await c.post(BASE, headers=pur, json={
        "supplier_ids": [chain_sup],
        "price_request_ids": [a["id"], b["id"], e["id"]],
        "notes": "satu pengiriman"})
    check("three jobs go out as one request", r.status_code == 201,
          f"{r.status_code} {J(r)}"[:200])
    joint = J(r)[0]
    check("...with every line on it", joint["lines_total"] == 4,
          str(joint["lines_total"]))
    check("...it knows it is joint", joint["is_joint"] is True, str(joint))
    check("...listing all three sources",
          {s["number"] for s in joint["source_price_requests"]}
          == {a["number"], b["number"], e["number"]},
          str(joint["source_price_requests"]))
    check("...and belongs to none of them on its own",
          joint["price_request_id"] is None, str(joint["price_request_id"]))
    check("each source says which of the joint lines are its own",
          next(s for s in joint["source_price_requests"]
               if s["number"] == b["number"])["lines"] == [2, 3],
          str(joint["source_price_requests"]))

    await c.post(f"{BASE}/{joint['id']}/quote", headers=pur, json={
        "items": [{"line_no": 1, "quoted_price": 5_000},
                  {"line_no": 2, "quoted_price": 3_000},
                  {"line_no": 3, "quoted_price": 1_000},
                  {"line_no": 4, "quoted_price": 900_000}],
        "quoted_lead_days": 21})
    r = await c.post(f"{BASE}/{joint['id']}/apply", headers=pur)
    check("one apply costs all three jobs", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:200])
    by_no = {x["price_request_number"]: x for x in J(r)["price_requests"]}
    check("...each getting only its own lines",
          [by_no[a["number"]]["applied_lines"],
           by_no[b["number"]]["applied_lines"],
           by_no[e["number"]]["applied_lines"]] == [1, 2, 1], str(by_no))
    check("...and all three are complete, so all three go to the director",
          all(x["status"] == "pending_director" for x in by_no.values()),
          str({k: v["status"] for k, v in by_no.items()}))

    got_b = J(await c.get(f"/price-requests/{b['id']}", headers=pur))
    check("the middle job took the right two prices",
          [float(i["cost_price"]) for i in got_b["items"]] == [3_000, 1_000],
          str([i.get("cost_price") for i in got_b["items"]]))
    got_e = J(await c.get(f"/price-requests/{e['id']}", headers=pur))
    check("...and the plate went to the job that asked for it",
          float(got_e["items"][0]["cost_price"]) == 900_000,
          str(got_e["items"][0].get("cost_price")))

    seen_in = []
    for p_ in (a, b, e):
        cmp_ = J(await c.get(f"{BASE}/for-price-request/{p_['id']}/compare",
                             headers=pur))
        seen_in.append(any(x["number"] == joint["number"]
                           for x in cmp_["requests"]))
    check("the joint request shows up under each job's comparison",
          all(seen_in), str(seen_in))

    # ══ discussion and files ═════════════════════════════════════════════════
    print("\n── the conversation and the paperwork live on the request ──")
    r = await c.post("/comments", headers=pur, json={
        "owner_type": "supplier_price_request", "owner_id": joint["id"],
        "body": f"Sudah konfirmasi via WA {tag}"})
    check("purchasing can discuss it on the request",
          r.status_code in (200, 201), f"{r.status_code} {J(r)}"[:150])
    r = await c.get("/comments", headers=d, params={
        "owner_type": "supplier_price_request", "owner_id": joint["id"]})
    rows = J(r)
    rows = rows if isinstance(rows, list) else rows.get("data", [])
    check("...and the director reads it", r.status_code == 200
          and any(f"Sudah konfirmasi via WA {tag}" in (x.get("body") or "")
                  for x in rows), f"{r.status_code} {str(rows)[:150]}")
    r = await c.post("/comments", headers=s1, json={
        "owner_type": "supplier_price_request", "owner_id": joint["id"],
        "body": "nope"})
    check("sales cannot join that conversation", r.status_code == 403,
          str(r.status_code))

    r = await c.post("/attachments", headers=pur,
                     files={"file": (f"quote-{tag}.pdf",
                                     io.BytesIO(b"%PDF-1.4 vendor quote"),
                                     "application/pdf")},
                     data={"owner_type": "supplier_price_request",
                           "owner_id": joint["id"]})
    check("the vendor's own quotation sheet can be filed on it",
          r.status_code in (200, 201), f"{r.status_code} {J(r)}"[:150])
    r = await c.get("/attachments", headers=pur, params={
        "owner_type": "supplier_price_request", "owner_id": joint["id"]})
    check("...and read back", r.status_code == 200 and len(J(r)) == 1,
          f"{r.status_code} {str(J(r))[:120]}")
    r = await c.get("/attachments", headers=s1, params={
        "owner_type": "supplier_price_request", "owner_id": joint["id"]})
    check("...but not by sales", r.status_code == 403, str(r.status_code))

    # ══ the refusals ═════════════════════════════════════════════════════════
    print("\n── what it refuses ──")
    r = await c.post(BASE, headers=pur, json={
        "price_request_id": job["id"],
        "assignments": [{"supplier_id": chain_sup, "lines": [
            {"price_request_id": job["id"], "line_no": 99}]}]})
    check("a line that does not exist is refused", r.status_code == 400,
          f"{r.status_code} {J(r)}"[:150])
    check("...naming the request and the line", job["number"] in str(J(r)),
          str(J(r))[:150])
    r = await c.post(BASE, headers=pur, json={
        "price_request_id": job["id"],
        "assignments": [{"supplier_id": chain_sup, "lines": [
            {"price_request_id": str(uuid.uuid4()), "line_no": 1}]}]})
    check("a line from a request not in scope is refused",
          r.status_code == 400, f"{r.status_code} {J(r)}"[:150])
    r = await c.post(BASE, headers=pur, json={
        "assignments": [{"supplier_id": chain_sup, "lines": []}]})
    check("splitting nothing is refused", r.status_code == 400,
          f"{r.status_code} {J(r)}"[:150])
    r = await c.post(BASE, headers=pur, json={
        "price_request_id": job["id"],
        "assignments": [
            {"supplier_id": chain_sup, "lines": [
                {"price_request_id": job["id"], "line_no": 1}]},
            {"supplier_id": chain_sup, "lines": [
                {"price_request_id": job["id"], "line_no": 1}]},
        ]})
    check("...and asking one supplier the same line twice in one click",
          r.status_code == 400, f"{r.status_code} {J(r)}"[:150])
    r = await c.post(BASE, headers=s1, json={
        "price_request_ids": [a["id"]], "supplier_ids": [chain_sup]})
    check("sales cannot raise any of this", r.status_code == 403,
          str(r.status_code))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        sys.exit(1)


asyncio.run(main())

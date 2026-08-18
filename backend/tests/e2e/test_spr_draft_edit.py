"""Fixing a supplier price request before it goes out.

Asked for, on a screenshot of a draft SPR: *"PR dari purchasing ke supplier
sebelum di kirim bisa di edit : Nomor, item, UOM"* — the sheet purchasing
sends a vendor must be correctable while it is still a draft.

The sheet is generated: the number comes off a counter, the lines are copied
from the customer's price request. Both are routinely wrong by the time
anyone looks. The customer said 40 metres and meant 40 feet; the description
came over as the salesman typed it; the UOM was never filled in at all; and
the number wants to be the one purchasing's own filing uses. Until this,
every one of those meant deleting the draft and starting again — which loses
the discussion and the vendor's attachments with it.

What this pins down beyond "the field saves":

**A draft is correctable, a sent request is not.** Once it has gone, the
vendor is holding a copy. Renumbering it would leave them quoting against a
document that no longer exists on our side, and rewording a line would mean
their answer no longer says what it appears to say. So the same two edits
that are ordinary on a draft are refused after `send`.

**Numbers stay unique.** They are what purchasing files by, and the compare
view names them.

**The line *set* is not editable on a request that costs something.** The
cross-vendor comparison and the "which lines are still uncovered" accounting
both key off `line_no`. Rewording line 2 is purchasing's business; deleting
it would silently compare two different baskets.

**An edit must not eat the parts of a line it does not know about.** A line
also carries where it came from — the source price request and line, which
is what lets a quote be applied back to the right place — and, on a draft
priced off a vendor's list, the price itself. A naive rewrite drops both.
Checked here on a joint request, where losing the source ref would break
`apply` outright.

**A standalone enquiry is nobody's copy.** With no price request behind it,
adding and dropping lines is just editing your own list.
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

    sup_a = J(await c.post("/purchasing/suppliers", headers=d, json={
        "name": f"PT Ubah Baja {tag}", "category": "raw_material"}))["id"]
    sup_b = J(await c.post("/purchasing/suppliers", headers=d, json={
        "name": f"PT Ubah Roda {tag}", "category": "raw_material"}))["id"]

    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Ubah Pembeli {tag}", "industry": "mining"}))["id"]

    async def a_price_request(desc_a, desc_b):
        pr = J(await c.post("/price-requests", headers=s1, json={
            "customer_id": cust,
            "items": [{"description": desc_a, "qty": 40, "uom": "meter"},
                      {"description": desc_b, "qty": 4, "uom": ""}]}))
        await c.post(f"/price-requests/{pr['id']}/submit", headers=s1)
        return pr

    pr = await a_price_request(f"CHAIN C-2122 {tag}", f"SPROKET 24T {tag}")

    spr = J(await c.post(BASE, headers=pur, json={
        "supplier_ids": [sup_a], "price_request_id": pr["id"]}))[0]
    sid = spr["id"]

    # ══ the number ═══════════════════════════════════════════════════════════
    print("\n── the number on a draft ──")
    check("it starts on the supplier series", spr["number"].startswith("SPR-"),
          spr["number"])
    mine = f"PR-PUR-{tag}-01"
    r = await c.patch(f"{BASE}/{sid}", headers=pur, json={"number": mine})
    check("purchasing can renumber a draft to their own reference",
          r.status_code == 200 and J(r)["number"] == mine,
          f"{r.status_code} {J(r)}"[:170])
    check("...and it is what the list shows now",
          any(x["number"] == mine for x in J(await c.get(BASE, headers=pur))),
          "not in the list")

    r = await c.patch(f"{BASE}/{sid}", headers=pur, json={"number": "   "})
    check("a blank number is refused", r.status_code == 400,
          f"{r.status_code} {J(r)}"[:140])

    other = J(await c.post(BASE, headers=pur, json={
        "supplier_ids": [sup_b], "price_request_id": pr["id"]}))[0]
    r = await c.patch(f"{BASE}/{other['id']}", headers=pur, json={"number": mine})
    check("...and so is one another request already uses", r.status_code == 409,
          f"{r.status_code} {J(r)}"[:140])
    check("...naming the number it clashed with",
          mine in str(J(r)), str(J(r))[:160])
    r = await c.patch(f"{BASE}/{sid}", headers=pur, json={"number": mine})
    check("renumbering to what it already is stays fine", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:140])

    # ══ the lines ════════════════════════════════════════════════════════════
    print("\n── the lines on a draft ──")
    before = J(await c.get(f"{BASE}/{sid}", headers=pur))["items"]
    check("the copied line has no UOM, exactly as sales left it",
          (before[1].get("uom") or "") == "", str(before[1].get("uom")))
    fixed = [
        {"line_no": 1, "description": f"CHAIN C-2122 DUPLEX {tag}",
         "qty": 40, "uom": "meter"},
        {"line_no": 2, "description": f"SPROCKET 24T {tag}", "qty": 6, "uom": "pcs"},
    ]
    r = await c.patch(f"{BASE}/{sid}", headers=pur, json={"items": fixed})
    check("the wording, the quantity and the unit all save", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:170])
    got = J(r)["items"]
    check("...the typo is corrected", got[1]["description"].startswith("SPROCKET"),
          got[1]["description"])
    check("...the revised quantity is stored", float(got[1]["qty"]) == 6.0,
          str(got[1]["qty"]))
    check("...and the missing unit is filled in", got[1]["uom"] == "pcs",
          str(got[1]["uom"]))
    check("the line's origin survived the edit",
          got[1].get("source_pr_id") == pr["id"]
          and got[1].get("source_line_no") == 2,
          str({k: got[1].get(k) for k in ("source_pr_id", "source_line_no")}))
    check("...and so did the one on the line that was not touched",
          got[0].get("source_pr_number") == pr["number"],
          str(got[0].get("source_pr_number")))

    r = await c.patch(f"{BASE}/{sid}", headers=pur, json={"items": [fixed[0]]})
    check("dropping a line the price request needs costed is refused",
          r.status_code == 409, f"{r.status_code} {J(r)}"[:140])
    r = await c.patch(f"{BASE}/{sid}", headers=pur, json={"items": fixed + [
        {"line_no": 3, "description": "BEARING", "qty": 1, "uom": "pcs"}]})
    check("...and so is inventing one", r.status_code == 409,
          f"{r.status_code} {J(r)}"[:140])
    r = await c.patch(f"{BASE}/{sid}", headers=pur, json={"items": []})
    check("...and emptying it altogether", r.status_code == 400,
          f"{r.status_code} {J(r)}"[:140])
    check("all of which left the request as it was",
          len(J(await c.get(f"{BASE}/{sid}", headers=pur))["items"]) == 2,
          "lines lost")

    # ══ a price already typed ════════════════════════════════════════════════
    print("\n── a price read off their list ──")
    priced = J(await c.post(BASE, headers=pur, json={
        "supplier_ids": [sup_b], "price_request_id": pr["id"]}))[0]
    r = await c.post(f"{BASE}/{priced['id']}/quote", headers=pur, json={
        "items": [{"line_no": 1, "quoted_price": 250000, "basis": "unit"}]})
    check("a price off a current list needed no sending", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:140])
    check("...but it does move the request past draft", J(r)["status"] == "quoted",
          J(r)["status"])
    r = await c.patch(f"{BASE}/{priced['id']}", headers=pur, json={"items": fixed})
    check("so the list it was priced against is fixed from then on",
          r.status_code == 409, f"{r.status_code} {J(r)}"[:140])

    # ══ once it has gone ═════════════════════════════════════════════════════
    print("\n── once the supplier has it ──")
    await c.post(f"{BASE}/{sid}/send", headers=pur)
    r = await c.patch(f"{BASE}/{sid}", headers=pur, json={"number": f"PR-LATE-{tag}"})
    check("renumbering a sent request is refused", r.status_code == 409,
          f"{r.status_code} {J(r)}"[:140])
    check("...saying why — they are holding the old one",
          "supplier" in str(J(r)).lower(), str(J(r))[:160])
    r = await c.patch(f"{BASE}/{sid}", headers=pur, json={"items": fixed})
    check("rewording a sent request's lines is refused too", r.status_code == 409,
          f"{r.status_code} {J(r)}"[:140])
    r = await c.patch(f"{BASE}/{sid}", headers=pur, json={
        "notes": "chased them Tuesday"})
    check("but the covering note is still purchasing's to keep",
          r.status_code == 200 and J(r)["notes"] == "chased them Tuesday",
          f"{r.status_code} {J(r)}"[:140])
    check("...and the number is untouched by all of it",
          J(await c.get(f"{BASE}/{sid}", headers=pur))["number"] == mine,
          J(await c.get(f"{BASE}/{sid}", headers=pur))["number"])

    # ══ a joint request ══════════════════════════════════════════════════════
    print("\n── a request covering two jobs at once ──")
    pr2 = await a_price_request(f"BELT B-90 {tag}", f"PULLEY {tag}")
    joint = J(await c.post(BASE, headers=pur, json={
        "supplier_ids": [sup_b],
        "price_request_ids": [pr["id"], pr2["id"]]}))[0]
    check("it is joint, with no single header link",
          joint["is_joint"] and joint["price_request_id"] is None,
          str(joint.get("price_request_id")))
    jitems = [{"line_no": i["line_no"],
               "description": i["description"] + " (rev)",
               "qty": i["qty"], "uom": i["uom"] or "pcs"} for i in joint["items"]]
    r = await c.patch(f"{BASE}/{joint['id']}", headers=pur, json={"items": jitems})
    check("its lines reword like any other draft", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:170])
    check("...every line still knows which job it belongs to",
          all(i.get("source_pr_id") for i in J(r)["items"]),
          str([i.get("source_pr_id") for i in J(r)["items"]]))
    check("...so both jobs are still listed as its sources",
          len(J(r)["source_price_requests"]) == 2,
          str(J(r)["source_price_requests"]))
    r = await c.patch(f"{BASE}/{joint['id']}", headers=pur,
                      json={"items": jitems[:-1]})
    check("and dropping one of its lines is refused, header link or not",
          r.status_code == 409, f"{r.status_code} {J(r)}"[:140])

    # the reworded joint request still applies back to the right lines
    await c.post(f"{BASE}/{joint['id']}/quote", headers=pur, json={
        "items": [{"line_no": i["line_no"], "quoted_price": 1000, "basis": "unit"}
                  for i in J(await c.get(f"{BASE}/{joint['id']}", headers=pur))["items"]]})
    r = await c.post(f"{BASE}/{joint['id']}/apply", headers=pur)
    check("a reworded joint quote still applies as the cost", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:170])
    costed = J(await c.get(f"/price-requests/{pr2['id']}", headers=pur))
    check("...landing on the job it came from",
          all(float(i.get("cost_price") or 0) == 1000.0 for i in costed["items"]),
          str([i.get("cost_price") for i in costed["items"]]))

    # ══ a standalone enquiry ═════════════════════════════════════════════════
    print("\n── a standalone enquiry ──")
    alone = J(await c.post(BASE, headers=pur, json={
        "supplier_ids": [sup_a],
        "items": [{"line_no": 1, "description": f"OIL SEAL {tag}",
                   "qty": 10, "uom": "pcs"}]}))[0]
    r = await c.patch(f"{BASE}/{alone['id']}", headers=pur, json={"items": [
        {"line_no": 1, "description": f"OIL SEAL {tag}", "qty": 10, "uom": "pcs"},
        {"line_no": 2, "description": f"GASKET {tag}", "qty": 2, "uom": "set"}]})
    check("with no job behind it, a line can simply be added",
          r.status_code == 200 and len(J(r)["items"]) == 2,
          f"{r.status_code} {J(r)}"[:170])

    # ══ who may ══════════════════════════════════════════════════════════════
    print("\n── who may correct one ──")
    draft2 = J(await c.post(BASE, headers=pur, json={
        "supplier_ids": [sup_a], "price_request_id": pr["id"]}))[0]
    r = await c.patch(f"{BASE}/{draft2['id']}", headers=s1,
                      json={"number": f"SALES-{tag}"})
    check("sales cannot reach it, here as everywhere else",
          r.status_code in (401, 403), str(r.status_code))
    r = await c.patch(f"{BASE}/{draft2['id']}", headers=d,
                      json={"number": f"DIR-{tag}"})
    check("the director can", r.status_code == 200, f"{r.status_code} {J(r)}"[:140])

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)


asyncio.run(main())

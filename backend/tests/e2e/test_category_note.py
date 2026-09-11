"""An "other" gets to say what it is.

`others` is on the six-item category list deliberately — a list without an
escape hatch gets the nearest wrong answer picked instead, and then the wrong
answer is what you filter on. The cost of having it is that it is the one value
carrying no information: purchasing costing a line marked `others` learns only
that it is none of the other five, and has to go and ask.

So a line whose category is `others` carries a note saying what the other
actually is. Three things about it are worth pinning:

* **It only exists where the question does.** Send a note on a sprocket and it
  is dropped, not stored — a screen showing a category and an explanation that
  contradict each other is worse than the blank it replaces.
* **Changing the category away from `others` clears it.** Same reason. The
  alternative is a note about an "other" sitting on a line that has since been
  called something specific.
* **It survives an edit that does not mention it.** Every line is rebuilt from
  scratch on a PATCH, so a client that does not render the field would wipe it
  — exactly how an older edit form once erased which supplier a cost came from.

And it has to reach the people it is for: the note travels with the request
through pricing and approval, which is where somebody is reading the line and
deciding what it costs.
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

NOTE = "Gearbox oil seal, SKF 25x47x7"


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

    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Lainnya {TAG}", "industry": "mining"}))["id"]

    async def get(pid, headers=None):
        return J(await c.get(f"/price-requests/{pid}", headers=headers or s1))

    # ══ saving one ═══════════════════════════════════════════════════════
    print("\n── a line marked 'others' says what the other is ──")
    r = await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [{"description": f"Seal {TAG}", "qty": 2, "uom": "pcs",
                   "category": "others", "category_note": NOTE},
                  {"description": f"Sprocket {TAG}", "qty": 1, "uom": "pcs",
                   "category": "sprocket"}]})
    check("the request saves", r.status_code == 201, f"{r.status_code} {why(r)}")
    pr = J(r)
    check("...and the note is on the 'others' line",
          pr["items"][0].get("category_note") == NOTE,
          str(pr["items"][0].get("category_note")))
    check("...while the sprocket has none, having nothing to explain",
          pr["items"][1].get("category_note") is None,
          str(pr["items"][1].get("category_note")))

    print("\n── and it is read back the same ──")
    got = await get(pr["id"])
    check("the note survives the round trip",
          got["items"][0].get("category_note") == NOTE,
          str(got["items"][0].get("category_note")))
    # Purchasing cannot open a draft, which is a separate rule and stays; the
    # section further down checks they read it once the request reaches them.

    # ══ where the question does not exist ════════════════════════════════
    print("\n── a note on anything else is dropped, not stored ──")
    r = await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [{"description": f"Chain {TAG}", "qty": 3, "uom": "pcs",
                   "category": "roller_chain",
                   "category_note": "this should not stick"}]})
    check("the line still saves", r.status_code == 201, f"{r.status_code} {why(r)}")
    check("...with no note on it", J(r)["items"][0].get("category_note") is None,
          str(J(r)["items"][0].get("category_note")))

    r = await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [{"description": f"Kosong {TAG}", "qty": 1, "uom": "pcs",
                   "category_note": "no category at all"}]})
    check("nor on a line with no category yet",
          J(r)["items"][0].get("category_note") is None,
          str(J(r)["items"][0].get("category_note")))

    # ══ editing around it ════════════════════════════════════════════════
    print("\n── an edit that never renders the field does not wipe it ──")
    r = await c.patch(f"/price-requests/{pr['id']}", headers=s1, json={
        "items": [{"line_no": 1, "description": f"Seal {TAG} rev B", "qty": 4,
                   "uom": "pcs", "category": "others"},
                  {"line_no": 2, "description": f"Sprocket {TAG}", "qty": 1,
                   "uom": "pcs", "category": "sprocket"}]})
    check("the edit lands", r.status_code == 200, f"{r.status_code} {why(r)}")
    after = await get(pr["id"])
    check("...and the note is still there",
          after["items"][0].get("category_note") == NOTE,
          str(after["items"][0].get("category_note")))
    check("...on a line that was genuinely reworded",
          after["items"][0]["description"] == f"Seal {TAG} rev B",
          after["items"][0]["description"])

    print("\n── sending it blank clears it, because that is somebody clearing it ──")
    r = await c.patch(f"/price-requests/{pr['id']}", headers=s1, json={
        "items": [{"line_no": 1, "description": f"Seal {TAG} rev B", "qty": 4,
                   "uom": "pcs", "category": "others", "category_note": ""}]})
    check("the edit lands", r.status_code == 200, f"{r.status_code} {why(r)}")
    check("...and the note is gone",
          (await get(pr["id"]))["items"][0].get("category_note") is None,
          str((await get(pr['id']))["items"][0].get("category_note")))

    print("\n── and naming the part properly takes the note with it ──")
    await c.patch(f"/price-requests/{pr['id']}", headers=s1, json={
        "items": [{"line_no": 1, "description": f"Seal {TAG}", "qty": 4,
                   "uom": "pcs", "category": "others", "category_note": NOTE}]})
    check("the note is back", (await get(pr["id"]))["items"][0].get("category_note") == NOTE,
          str((await get(pr['id']))["items"][0].get("category_note")))
    r = await c.patch(f"/price-requests/{pr['id']}", headers=s1, json={
        "items": [{"line_no": 1, "description": f"Seal {TAG}", "qty": 4,
                   "uom": "pcs", "category": "sprocket",
                   "category_note": NOTE}]})
    check("...and once the line is called a sprocket", r.status_code == 200,
          f"{r.status_code} {why(r)}")
    line = (await get(pr["id"]))["items"][0]
    check("...the note explaining the 'other' is cleared with it",
          line.get("category_note") is None and line.get("category") == "sprocket",
          str(line)[:180])

    # ══ it reaches the desk that costs the line ══════════════════════════
    print("\n── and it is still there when the line is being priced ──")
    pr2 = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [{"description": f"Other Part {TAG}", "qty": 5, "uom": "pcs",
                   "category": "others", "category_note": NOTE}]}))
    await c.post(f"/price-requests/{pr2['id']}/submit", headers=s1)
    check("purchasing reads the note on the line they are costing",
          (await get(pr2["id"], pur))["items"][0].get("category_note") == NOTE,
          str((await get(pr2['id'], pur))["items"][0].get("category_note")))
    await c.post(f"/price-requests/{pr2['id']}/price", headers=pur,
                 json={"items": [{"line_no": 1, "cost_price": 90_000, "basis": "unit"}]})
    check("...and pricing it does not drop the note",
          (await get(pr2["id"], pur))["items"][0].get("category_note") == NOTE,
          str((await get(pr2['id'], pur))["items"][0].get("category_note")))
    await c.post(f"/price-requests/{pr2['id']}/approve", headers=d,
                 json={"items": [{"line_no": 1, "sell_price": 180_000, "basis": "unit"}]})
    check("...nor does approving it",
          (await get(pr2["id"], d))["items"][0].get("category_note") == NOTE,
          str((await get(pr2['id'], d))["items"][0].get("category_note")))

    print("\n── a note longer than the box is trimmed, not refused ──")
    r = await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [{"description": f"Panjang {TAG}", "qty": 1, "uom": "pcs",
                   "category": "others", "category_note": "x" * 400}]})
    check("it saves", r.status_code == 201, f"{r.status_code} {why(r)}")
    check("...at the stored length", len(J(r)["items"][0]["category_note"]) == 200,
          str(len(J(r)["items"][0].get("category_note") or "")))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)


asyncio.run(main())

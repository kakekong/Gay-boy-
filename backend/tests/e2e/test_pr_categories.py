"""The category of a line is a list, not a text box.

It was free text, which produced "sprocket", "Sprockets", "gear sprocket" and
"SPROCKET 12T" for one kind of thing — so nothing could be counted or filtered
by it, which is the only reason to record a category at all.

Six values now: conveyor chain, roller chain, connecting link, sprocket,
roller conveyor, others. `others` is part of the list rather than an escape
hatch bolted on, because a list without one gets the nearest wrong answer
picked instead, and then the wrong answer is what you filter on.

Two things matter beyond "it saves". Spellings that obviously mean one of the
six are mapped rather than refused, in both languages, for the same reason the
unit box maps "EA" and "buah". And a line written before the list existed
carries free text that is not on it: re-sending that value unchanged has to be
allowed through, or correcting a typo elsewhere on an old request would be
refused because of a field nobody was touching.
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

SIX = ["conveyor_chain", "roller_chain", "connecting_link",
       "sprocket", "roller_conveyor", "others"]


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

    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Kategori {TAG}", "industry": "mining"}))["id"]

    # ══ the list itself ══════════════════════════════════════════════════
    print("\n── what the form is allowed to offer ──")
    cat = J(await c.get("/price-requests/catalog", headers=s1))
    values = [x["value"] for x in cat.get("categories", [])]
    check("the six categories are served, in order", values == SIX, str(values))
    check("...each with the words a person reads",
          [x["label"] for x in cat["categories"]]
          == ["Conveyor chain", "Roller chain", "Connecting link",
              "Sprocket", "Roller conveyor", "Others"],
          str([x.get("label") for x in cat.get("categories", [])]))
    check("...and the units come with them, from the same place",
          cat.get("units") == ["pcs", "meter", "set", "roll", "link"],
          str(cat.get("units")))

    # ══ saving one ═══════════════════════════════════════════════════════
    print("\n── a request is raised ──")
    r = await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [{"description": f"Chain {TAG}", "qty": 4, "uom": "pcs",
                   "category": "conveyor_chain"},
                  {"description": f"Gear {TAG}", "qty": 2, "uom": "pcs",
                   "category": "Sprocket"},
                  {"description": f"Link {TAG}", "qty": 8, "uom": "pcs",
                   "category": "connecting link"},
                  {"description": f"Lain {TAG}", "qty": 1, "uom": "set",
                   "category": "lainnya"}]})
    check("a request saves with categories on its lines", r.status_code == 201,
          f"{r.status_code} {why(r)}")
    pr = J(r)
    got = [i.get("category") for i in pr["items"]]
    check("...the canonical value kept as it is", got[0] == "conveyor_chain", str(got))
    check("...a different casing mapped onto it", got[1] == "sprocket", str(got))
    check("...the spaced spelling mapped too", got[2] == "connecting_link", str(got))
    check("...and the Indonesian one", got[3] == "others", str(got))

    # ══ what it will not take ════════════════════════════════════════════
    print("\n── and what it refuses ──")
    r = await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [{"description": f"Bebas {TAG}", "qty": 1, "uom": "pcs",
                   "category": "gear sprocket 12T"}]})
    check("free text is refused", r.status_code == 400, str(r.status_code))
    check("...and the refusal lists what to use instead",
          "conveyor chain" in why(r) and "others" in why(r), why(r)[:220])

    r = await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [{"description": f"Kosong {TAG}", "qty": 1, "uom": "pcs"}]})
    check("a line with no category at all still saves — a draft is half-written",
          r.status_code == 201, f"{r.status_code} {why(r)}")
    blank_pr = J(r)
    check("...and holds nothing rather than a guess",
          blank_pr["items"][0].get("category") in (None, ""),
          str(blank_pr["items"][0].get("category")))

    # ══ it survives an edit ══════════════════════════════════════════════
    print("\n── editing the line around it ──")
    r = await c.patch(f"/price-requests/{pr['id']}", headers=s1, json={
        "items": [{"line_no": 1, "description": f"Chain {TAG} rev B",
                   "qty": 4, "uom": "pcs", "category": "conveyor_chain"}]})
    check("a reworded line keeps its category", r.status_code == 200,
          f"{r.status_code} {why(r)}")
    pr2 = J(await c.get(f"/price-requests/{pr['id']}", headers=s1))
    check("...still the same one", pr2["items"][0].get("category") == "conveyor_chain",
          str(pr2["items"][0].get("category")))

    # A client that does not send the field at all must not erase it.
    r = await c.patch(f"/price-requests/{pr['id']}", headers=s1, json={
        "items": [{"line_no": 1, "description": f"Chain {TAG} rev C",
                   "qty": 4, "uom": "pcs"}]})
    pr3 = J(await c.get(f"/price-requests/{pr['id']}", headers=s1))
    check("a form that never renders the field does not wipe it",
          pr3["items"][0].get("category") == "conveyor_chain",
          str(pr3["items"][0].get("category")))

    # ══ lines older than the list ════════════════════════════════════════
    print("\n── a line written before the list existed ──")
    from app.core.db import SessionLocal
    from app.models.price_request import PriceRequest as _PR
    legacy_pr = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [{"description": f"Lama {TAG}", "qty": 3, "uom": "pcs"}]}))
    async with SessionLocal() as db:
        row = await db.get(_PR, uuid.UUID(legacy_pr["id"]))
        items = [dict(i) for i in row.items]
        items[0]["category"] = "Gear Sprocket 12T"      # free text, as it was
        row.items = items
        await db.commit()

    got = J(await c.get(f"/price-requests/{legacy_pr['id']}", headers=s1))
    check("the old free text is still there to read",
          got["items"][0]["category"] == "Gear Sprocket 12T",
          str(got["items"][0].get("category")))

    r = await c.patch(f"/price-requests/{legacy_pr['id']}", headers=s1, json={
        "items": [{"line_no": 1, "description": f"Lama {TAG} fixed", "qty": 3,
                   "uom": "pcs", "category": "Gear Sprocket 12T"}]})
    check("sending it back unchanged is allowed — the edit was about the name",
          r.status_code == 200, f"{r.status_code} {why(r)}")
    got = J(await c.get(f"/price-requests/{legacy_pr['id']}", headers=s1))
    check("...and it is neither refused nor quietly rewritten",
          got["items"][0]["category"] == "Gear Sprocket 12T"
          and got["items"][0]["description"] == f"Lama {TAG} fixed",
          str(got["items"][0])[:200])

    r = await c.patch(f"/price-requests/{legacy_pr['id']}", headers=s1, json={
        "items": [{"line_no": 1, "description": f"Lama {TAG} fixed", "qty": 3,
                   "uom": "pcs", "category": "sprocket"}]})
    check("...but changing it means choosing from the list", r.status_code == 200,
          f"{r.status_code} {why(r)}")
    got = J(await c.get(f"/price-requests/{legacy_pr['id']}", headers=s1))
    check("...and then it is one of the six", got["items"][0]["category"] == "sprocket",
          str(got["items"][0].get("category")))

    r = await c.patch(f"/price-requests/{legacy_pr['id']}", headers=s1, json={
        "items": [{"line_no": 1, "description": f"Lama {TAG} fixed", "qty": 3,
                   "uom": "pcs", "category": "Some Other Thing"}]})
    check("...and once it is, free text is refused like anywhere else",
          r.status_code == 400, f"{r.status_code} {why(r)}")

    # ══ it reaches the catalogue ═════════════════════════════════════════
    print("\n── and follows the part into stock ──")
    r = await c.post(f"/price-requests/{pr['id']}/submit", headers=s1)
    check("the request submits", r.status_code == 200, f"{r.status_code} {why(r)}")
    items = J(await c.get("/inventory", headers=d, params={"limit": 300}))
    rows = items if isinstance(items, list) else items.get("items", [])
    mine = [x for x in rows if TAG in (x.get("name") or "")]
    check("the catalogue row carries the category, not free text",
          mine and all(x.get("category") in SIX + [None] for x in mine),
          str([(x.get("name"), x.get("category")) for x in mine])[:250])

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)


asyncio.run(main())

"""Chain is counted in links, so `link` is a unit.

The company sells conveyor chain, roller chain and connecting links — three
of the six categories — and none of it is counted in pieces. A length of
chain quoted "4 pcs" leaves the reader with no idea how much chain is meant:
one piece of a hundred links, or four links. The unit list had pcs, meter,
set and roll, so the quantity on the document could not say what it meant.

Not to be confused with the URL field also called `link` on a price-request
line. They share a word and nothing else, and this checks the two do not
interfere — a line can carry both at once, which is the ordinary case: a
length of chain with the supplier's product page pasted next to it.

The list is served from one place, so what the form offers and what the
server accepts are the same list. That is checked too, because a unit the
screen offers and the server refuses is a dead end you only find by hitting
it.
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

UNITS = ["pcs", "meter", "set", "roll", "link"]


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

    # ══ the list ═════════════════════════════════════════════════════════
    print("\n── what a quantity may be counted in ──")
    cat = J(await c.get("/price-requests/catalog", headers=s1))
    check("the served list carries link", cat.get("units") == UNITS,
          str(cat.get("units")))

    # ══ a chain, in links, with its product page ═════════════════════════
    print("\n── a length of chain ──")
    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Rantai {TAG}", "industry": "mining"}))["id"]
    URL = "https://example.com/conveyor-chain-c2060h"
    r = await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [{"description": f"Conveyor Chain C2060H {TAG}", "qty": 240,
                   "uom": "link", "category": "conveyor_chain", "link": URL},
                  {"description": f"Connecting Link {TAG}", "qty": 8,
                   "uom": "pcs", "category": "connecting_link"}]})
    check("a line can be counted in links", r.status_code == 201,
          f"{r.status_code} {why(r)}")
    pr = J(r)
    check("...and says so", pr["items"][0]["uom"] == "link",
          str(pr["items"][0].get("uom")))
    # The two things called "link" have to coexist on one line.
    check("...while the URL beside it is untouched",
          pr["items"][0]["link"] == URL, str(pr["items"][0].get("link")))
    check("...and the unit did not become the URL, or the other way round",
          pr["items"][0]["uom"] == "link" and pr["items"][0]["link"] == URL
          and pr["items"][1]["uom"] == "pcs"
          and pr["items"][1].get("link") in (None, ""),
          str(pr["items"])[:260])

    # ══ the spellings people use ═════════════════════════════════════════
    print("\n── written the way anybody would write it ──")
    r = await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [{"description": f"A {TAG}", "qty": 10, "uom": "Links"},
                  {"description": f"B {TAG}", "qty": 10, "uom": "mata rantai"},
                  {"description": f"C {TAG}", "qty": 10, "uom": "PITCH"}]})
    check("the plural, the Indonesian and the trade word all map",
          r.status_code == 201, f"{r.status_code} {why(r)}")
    check("...onto the one value", [i["uom"] for i in J(r)["items"]]
          == ["link", "link", "link"], str([i["uom"] for i in J(r)["items"]]))

    r = await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [{"description": f"D {TAG}", "qty": 1, "uom": "lusin"}]})
    check("something nobody counts in is still refused", r.status_code == 400,
          str(r.status_code))
    check("...and the refusal now names link too", "link" in why(r), why(r)[:200])

    # ══ it survives the whole way through ════════════════════════════════
    print("\n── and reaches every document made from it ──")
    await c.post(f"/price-requests/{pr['id']}/submit", headers=s1)
    await c.post(f"/price-requests/{pr['id']}/price", headers=pur, json={
        "items": [{"line_no": 1, "cost_price": 25_000, "basis": "unit"},
                  {"line_no": 2, "cost_price": 60_000, "basis": "unit"}]})
    await c.post(f"/price-requests/{pr['id']}/approve", headers=d, json={
        "items": [{"line_no": 1, "sell_price": 50_000, "basis": "unit"},
                  {"line_no": 2, "sell_price": 120_000, "basis": "unit"}]})
    q = J(await c.post(f"/quotations/from-price-request/{pr['id']}", headers=s1))
    check("the quotation is quoted in links too",
          q["items"][0]["uom"] == "link", str(q["items"][0].get("uom")))

    r = await c.get(f"/quotations/{q['id']}/export.pdf", headers=s1)
    check("the customer's PDF builds", r.status_code == 200, str(r.status_code))
    from io import BytesIO
    from pypdf import PdfReader
    text = "\n".join((p.extract_text() or "")
                     for p in PdfReader(BytesIO(r.content)).pages)
    check("...and prints the unit, so 240 means 240 links",
          "LINK" in text.upper(), text[:400])

    items = J(await c.get("/inventory", headers=d, params={"limit": 300}))
    rows = items if isinstance(items, list) else items.get("items", [])
    chain = next((x for x in rows
                  if f"Conveyor Chain C2060H {TAG}" in (x.get("name") or "")), None)
    check("the catalogue row it created is counted in links too",
          chain and chain.get("uom") == "link", str(chain)[:200])
    check("...and kept the product page beside it",
          chain and chain.get("link") == URL, str(chain and chain.get("link")))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)


asyncio.run(main())

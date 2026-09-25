"""A price request leads straight to its quotation — every version of it.

The request page had one "View quotation" button, driven by
`pr.quotation_id`, which names only the FIRST quotation built from the
request. Revising a quotation makes a new row (R2) carrying the same
`price_request_id`, so after one revision the button opened the superseded R1
and the live quote had no road back from the request at all; the list showed
no quotation whatsoever.

Pinned here: the detail lists every quotation made from the request, newest
version first; the list carries them too (one query, not one per row); a
request with no quotation yet says so with an empty list; and purchasing —
customer-blind, with no quotations page — is given no links.
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
        "company_name": f"PT Jejak {TAG}", "industry": "mining"}))["id"]
    pr = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [{"description": f"SHACKLE {TAG}", "qty": 4, "uom": "pcs"}]}))["id"]
    await c.post(f"/price-requests/{pr}/submit", headers=s1)

    print("\n── before any quotation ──")
    det = J(await c.get(f"/price-requests/{pr}", headers=s1))
    check("a request with no quotation yet says so with an empty list",
          det.get("linked_quotations") == [], str(det.get("linked_quotations")))

    await c.post(f"/price-requests/{pr}/price", headers=d, json={
        "items": [{"line_no": 1, "cost_price": 100_000, "basis": "unit"}]})
    await c.post(f"/price-requests/{pr}/approve", headers=d, json={
        "items": [{"line_no": 1, "sell_price": 150_000, "basis": "unit"}]})
    q1 = J(await c.post(f"/quotations/from-price-request/{pr}", headers=s1))
    await c.post(f"/quotations/{q1['id']}/submit", headers=s1)
    await c.post(f"/quotations/{q1['id']}/approve", headers=d, json={"notes": ""})

    print("\n── one quotation ──")
    det = J(await c.get(f"/price-requests/{pr}", headers=s1))
    links = det.get("linked_quotations") or []
    check("the request lists the quotation made from it",
          [x["id"] for x in links] == [q1["id"]], str(links))
    if links:
        check("...by its number, status and total",
              links[0]["number"] == q1["number"] and links[0]["status"] == "approved"
              and links[0]["total"] > 0, str(links[0]))

    r = await c.post(f"/quotations/{q1['id']}/revise", headers=s1)
    check("sales revises the quotation", r.status_code == 201, f"{r.status_code} {J(r)}"[:160])
    q2 = J(r)

    print("\n── after a revision ──")
    det = J(await c.get(f"/price-requests/{pr}", headers=s1))
    links = det.get("linked_quotations") or []
    check("the revision is reachable from the request — it was not before",
          q2.get("id") in [x["id"] for x in links], str(links))
    check("...listed first, newest version on top, so the live one is the obvious click",
          bool(links) and links[0]["id"] == q2.get("id")
          and links[0]["version"] > links[-1]["version"],
          str([(x["number"], x["version"]) for x in links]))
    check("...and the original is still there, not forgotten",
          q1["id"] in [x["id"] for x in links])
    check("the old single link is untouched, for anything still reading it",
          det.get("quotation_id") == q1["id"], str(det.get("quotation_id")))

    print("\n── the list ──")
    rows = J(await c.get("/price-requests", headers=s1))
    row = next((x for x in rows if x["id"] == pr), None)
    check("the list row carries the quotations too",
          row is not None and [x["id"] for x in row.get("linked_quotations") or []]
          == [x["id"] for x in links],
          str(row and row.get("linked_quotations")))
    other = [x for x in rows if x["id"] != pr]
    check("...and every other row has the key, empty or not, so the column never guesses",
          all("linked_quotations" in x for x in other), "")

    rows = J(await c.get("/price-requests", headers=d))
    check("the director sees them as well",
          any(x["id"] == pr and x.get("linked_quotations") for x in rows))

    print("\n── purchasing ──")
    det = J(await c.get(f"/price-requests/{pr}", headers=pur))
    check("purchasing is not given quotation links — customer-blind, no quotations page",
          "linked_quotations" not in det, str(det.get("linked_quotations")))
    rows = J(await c.get("/price-requests", headers=pur))
    check("...on the list either",
          isinstance(rows, list) and all("linked_quotations" not in x for x in rows))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        sys.exit(1)

asyncio.run(main())

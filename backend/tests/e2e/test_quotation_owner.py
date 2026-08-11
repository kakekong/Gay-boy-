"""Who is answerable for one quotation, and what the rep can do with it.

Two things asked for together.

**The director can move a single quotation.** Handing over a whole customer
already moves every document on the account; this is the finer instrument —
one deal covered while its rep is away, or a quotation raised under the wrong
name. It changes who *owns* the document, which is what grants the right to
submit it, mark it won and edit it. It is not visibility: the rep who runs
the account can always read it either way.

**A quotation the director writes is fully workable by the rep.** Ownership
now lands on the customer's rep at creation, so every action the rep normally
has is available on it. The checks below walk the actions rather than the
column, because "can they interact with it" means the buttons, not the field:
submit it, withdraw it, edit it, print it, mark it won.

The refusal that has to survive: a closed quotation keeps its owner. Won and
lost are the record of who closed the deal, and rewriting that is falsifying
the sales history.
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
    s1 = await login("sales1@demo.local")
    s2 = await login("sales2@demo.local")
    pur = await login("purchasing@demo.local")
    me1 = J(await c.get("/auth/me", headers=s1))
    me2 = J(await c.get("/auth/me", headers=s2))

    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Pemilik {tag}", "industry": "mining"}))["id"]

    def director_quote(name: str) -> dict:
        return {"customer_id": cust, "variant": "detailed",
                "items": [{"line_no": 1, "description": name, "qty": 2,
                           "uom": "pcs", "unit_price": 1_000_000}]}

    # ══ the director's quotation is the rep's to work ════════════════════════
    print("\n── a quotation the director writes on somebody's customer ──")
    q = J(await c.post("/quotations", headers=d, json=director_quote(f"Sprocket {tag}")))
    check("it lands in the account rep's name", q["sales_pic_id"] == me1["id"],
          str(q.get("sales_pic_id")))

    r = await c.get(f"/quotations/{q['id']}", headers=s1)
    check("the rep can open it", r.status_code == 200, str(r.status_code))
    r = await c.patch(f"/quotations/{q['id']}", headers=s1,
                      json={"notes": f"customer wants delivery in 3 weeks {tag}"})
    check("...edit it", r.status_code == 200, f"{r.status_code} {J(r)}"[:140])
    r = await c.patch(f"/quotations/{q['id']}", headers=s1, json={
        "items": [{"line_no": 1, "description": f"Sprocket {tag}", "qty": 5,
                   "uom": "pcs", "unit_price": 1_100_000}]})
    check("...change its lines", r.status_code == 200, f"{r.status_code} {J(r)}"[:140])
    check("...and the change stuck",
          float(J(await c.get(f"/quotations/{q['id']}", headers=s1))
                ["items"][0]["qty"]) == 5)
    r = await c.get(f"/quotations/{q['id']}/export.pdf", headers=s1)
    check("...print it", r.status_code == 200 and r.content[:4] == b"%PDF",
          str(r.status_code))
    r = await c.post(f"/quotations/{q['id']}/submit", headers=s1)
    check("...submit it", r.status_code == 200, f"{r.status_code} {J(r)}"[:140])
    r = await c.post(f"/quotations/{q['id']}/unsubmit", headers=s1)
    check("...and withdraw it again", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:140])
    await c.post(f"/quotations/{q['id']}/submit", headers=s1)
    await c.post(f"/quotations/{q['id']}/approve", headers=d, json={})
    # Won needs the customer's own PO behind it.
    _po = J(await c.post("/customer-pos", headers=s1, json={
        "customer_id": cust, "quotation_id": q["id"], "number": f"PO-OWN-{tag}",
        "items": [{"description": f"Sprocket {tag}", "qty": 5, "unit_price": 1_100_000}],
        "is_downpayment": False}))
    if _po.get("id"):
        await c.post(f"/customer-pos/{_po['id']}/approve", headers=d, json={"notes": ""})
    r = await c.post(f"/quotations/{q['id']}/won", headers=s1)
    check("...and mark it won (which files the director's approval)",
          r.status_code in (200, 202), f"{r.status_code} {J(r)}"[:140])

    r = await c.get(f"/quotations/{q['id']}", headers=s2)
    check("a rep who does not own the customer still cannot open it",
          r.status_code == 403, str(r.status_code))

    # ══ moving one quotation ═════════════════════════════════════════════════
    print("\n── the director moves a single quotation ──")
    q2 = J(await c.post("/quotations", headers=d, json=director_quote(f"Chain {tag}")))
    check("it starts with the account's rep", q2["sales_pic_id"] == me1["id"],
          str(q2.get("sales_pic_id")))
    r = await c.post(f"/quotations/{q2['id']}/reassign", headers=d,
                     json={"sales_pic_id": me2["id"], "note": "Sales One is on leave"})
    check("the director can move it", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:150])
    got = J(await c.get(f"/quotations/{q2['id']}", headers=d))
    check("...the name changed", got["sales_pic_id"] == me2["id"],
          str(got["sales_pic_id"]))
    check("...and the customer did not move with it",
          J(await c.get(f"/customers/{cust}", headers=d))["sales_pic_id"] == me1["id"])

    r = await c.post(f"/quotations/{q2['id']}/submit", headers=s2)
    check("the new owner can act on it", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:140])
    r = await c.get(f"/quotations/{q2['id']}", headers=s1)
    check("...and the account's rep can still read it, because the customer "
          "is theirs", r.status_code == 200, str(r.status_code))
    await c.post(f"/quotations/{q2['id']}/unsubmit", headers=s2)

    acts = J(await c.get(f"/customers/{cust}/activities", headers=d))
    moved = next((a for a in acts if a["type"] == "assignment"
                  and q2["number"] in (a["notes"] or "")), None)
    check("the move is on the customer's timeline", moved is not None,
          str(len(acts)))
    check("...naming both reps and the reason",
          moved and "Sales One" in moved["notes"] and "Sales Two" in moved["notes"]
          and "on leave" in moved["notes"], moved and moved["notes"])

    # ══ who may, and what it refuses ═════════════════════════════════════════
    print("\n── the refusals ──")
    for who, hh in [("sales", s1), ("the account's own rep", s2)]:
        r = await c.post(f"/quotations/{q2['id']}/reassign", headers=hh,
                         json={"sales_pic_id": me1["id"]})
        check(f"{who} cannot move a quotation", r.status_code == 403,
              str(r.status_code))
    fin = J(await c.get("/users", headers=d, params={"role": "finance"}))
    if isinstance(fin, list) and fin:
        r = await c.post(f"/quotations/{q2['id']}/reassign", headers=d,
                         json={"sales_pic_id": fin[0]["id"]})
        check("finance cannot be put on a quotation", r.status_code == 400,
              f"{r.status_code} {J(r)}"[:140])
    r = await c.post(f"/quotations/{q2['id']}/reassign", headers=d,
                     json={"sales_pic_id": str(uuid.uuid4())})
    check("neither can somebody who does not exist", r.status_code == 404,
          str(r.status_code))
    same = await c.post(f"/quotations/{q2['id']}/reassign", headers=d,
                        json={"sales_pic_id": me2["id"]})
    check("re-stating the current owner is a no-op, not an error",
          same.status_code == 200, str(same.status_code))

    print("\n── a closed quotation keeps the name of whoever closed it ──")
    q3 = J(await c.post("/quotations", headers=d, json=director_quote(f"Belt {tag}")))
    await c.post(f"/quotations/{q3['id']}/submit", headers=s1)
    await c.post(f"/quotations/{q3['id']}/approve", headers=d, json={})
    _po3 = J(await c.post("/customer-pos", headers=s1, json={
        "customer_id": cust, "quotation_id": q3["id"], "number": f"PO-BELT-{tag}",
        "items": [{"description": f"Belt {tag}", "qty": 2, "unit_price": 1_000_000}],
        "is_downpayment": False}))
    if _po3.get("id"):
        await c.post(f"/customer-pos/{_po3['id']}/approve", headers=d, json={"notes": ""})
    await c.post(f"/quotations/{q3['id']}/won", headers=d)
    closed = J(await c.get(f"/quotations/{q3['id']}", headers=d))
    check("it is won", closed["status"] == "won", closed["status"])
    r = await c.post(f"/quotations/{q3['id']}/reassign", headers=d,
                     json={"sales_pic_id": me2["id"]})
    check("...and cannot be moved", r.status_code == 409, str(r.status_code))
    check("...with the reason said plainly", "closed" in str(J(r)).lower(),
          str(J(r))[:140])
    check("...the owner is untouched",
          J(await c.get(f"/quotations/{q3['id']}", headers=d))["sales_pic_id"]
          == me1["id"])

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        sys.exit(1)


asyncio.run(main())

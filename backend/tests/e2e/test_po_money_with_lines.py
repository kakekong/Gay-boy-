"""The currency and the rate belong to the lines, and travel with them.

A supplier PO's money is its lines: what was ordered, how many, at what price
each. The total is their sum. But the currency and the exchange rate were
edited in the header, a long way up the page from the figures they apply to —
and on an order with several lines that is the wrong end of the document.
Switching the currency up there re-labels every price further down, out of
sight, and the total typed up there could disagree with the lines that add up
to something else. It did: a PO could read "TOTAL (CNY) 355" over lines
summing to CNY 115,259,228.

So the editor for the lines now owns the money — currency, rate and the lines
go up in one save, and the header reads back what they say. Which puts two
things in the same request that were never in the same request before, and
that is what this checks.

The rate is only meaningful against the currency it was quoted for. Applying a
rate immediately (as the old code did, because a rate is not a decision anyone
has to approve) while queuing the currency for the director would leave the PO
reading the *new* rate against the *old* currency for as long as the approval
sat in the queue — the one combination that is certainly wrong. Submitted
together they now queue together and land together. Submitted alone, each keeps
the behaviour it had: a rate applies on the spot, a currency waits for the
director, and switching currency without saying what it is worth drops the old
rate rather than carrying a yuan rate onto a dollar order.
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
    pur = await login("purchasing@demo.local")
    fin = await login("finance@demo.local")

    sup = J(await c.post("/purchasing/suppliers", headers=pur, json={
        "name": f"PT Kurs {TAG}", "category": "fabrication"}))["id"]
    projects = J(await c.get("/operation/projects", headers=d))
    projects = projects if isinstance(projects, list) else projects.get("data", [])
    check("there is a project to raise POs against", bool(projects), str(projects)[:120])
    proj = projects[0]["id"]

    n = [0]
    async def a_po(**over):
        n[0] += 1
        body = {"supplier_id": sup, "project_id": proj, "po_date": "2026-05-20",
                "items": [{"description": f"Chain {TAG}-{n[0]}", "qty": 2,
                           "uom": "pcs", "unit_price": 100, "amount": 200}],
                "total": 200}
        body.update(over)
        return J(await c.post("/purchasing/po", headers=d, json=body))["id"]

    async def get(po_id, hdr=None):
        return J(await c.get(f"/purchasing/po/{po_id}", headers=hdr or d))

    async def approve_queued(po_id):
        """Clear whatever is waiting on the director for this PO."""
        rows = J(await c.get("/approvals", headers=d))
        rows = rows if isinstance(rows, list) else (rows.get("items") or rows.get("data") or [])
        # The inbox lists only what is still waiting, so there is no status
        # field to filter on — everything here for this PO is pending.
        done = 0
        for r in rows:
            if str(r.get("target_id")) == str(po_id):
                await c.post(f"/approvals/{r['id']}/approve", headers=d)
                done += 1
        return done

    # ══ one save carries the lines and the money they are priced in ══════
    print("\n── lines, currency and rate in a single save ──")
    po1 = await a_po()
    r = await c.patch(f"/purchasing/po/{po1}", headers=d, json={
        "items": [{"description": f"Chain {TAG}", "qty": 94, "uom": "m",
                   "unit_price": 1_226_162, "amount": 94 * 1_226_162},
                  {"description": f"Sprocket {TAG}", "qty": 4, "uom": "pcs",
                   "unit_price": 500_000, "amount": 2_000_000}],
        "total": 94 * 1_226_162 + 2_000_000,
        "currency": "CNY", "fx_rate": 3000})
    check("the director's single save is accepted", r.status_code == 200,
          f"{r.status_code} {why(r)}")
    got = await get(po1)
    check("...the currency lands", got.get("currency") == "CNY", str(got.get("currency")))
    check("...the rate lands with it — not wiped by the currency change",
          float(got.get("fx_rate") or 0) == 3000, str(got.get("fx_rate")))
    check("...the total is what the lines add up to",
          abs(float(got.get("total") or 0) - (94 * 1_226_162 + 2_000_000)) < 0.5,
          str(got.get("total")))
    check("...and the rupiah figure follows from both",
          abs(float(got.get("total_idr") or 0)
              - (94 * 1_226_162 + 2_000_000) * 3000) < 1,
          str(got.get("total_idr")))
    check("...with both lines still on it", len(got.get("items") or []) == 2,
          str(len(got.get("items") or [])))

    # ══ the rule that survives: a rate belongs to its currency ═══════════
    print("\n── switching currency without saying what it is worth ──")
    r = await c.patch(f"/purchasing/po/{po1}", headers=d, json={"currency": "USD"})
    check("the currency changes", r.status_code == 200, f"{r.status_code} {why(r)}")
    got = await get(po1)
    check("...and the yuan rate does not follow it onto a dollar order",
          got.get("fx_rate") is None, str(got.get("fx_rate")))
    check("...so the rupiah total goes quiet rather than lying",
          got.get("total_idr") is None, str(got.get("total_idr")))

    r = await c.patch(f"/purchasing/po/{po1}", headers=d,
                      json={"currency": "USD", "fx_rate": 16_200})
    check("saying both at once keeps the rate", r.status_code == 200,
          f"{r.status_code} {why(r)}")
    check("...on the order", float((await get(po1)).get("fx_rate") or 0) == 16_200,
          str((await get(po1)).get("fx_rate")))

    r = await c.patch(f"/purchasing/po/{po1}", headers=d,
                      json={"currency": "IDR"})
    check("back to rupiah sets the rate to 1, not to nothing",
          float((await get(po1)).get("fx_rate") or 0) == 1,
          str((await get(po1)).get("fx_rate")))

    r = await c.patch(f"/purchasing/po/{po1}", headers=d,
                      json={"currency": "CNY", "fx_rate": 0})
    check("a rate of zero is refused — it would make the order worth nothing",
          r.status_code == 400, f"{r.status_code} {why(r)}")

    # ══ purchasing: the pair queues as a pair ════════════════════════════
    print("\n── from purchasing, the pair goes to the director together ──")
    po2 = await a_po()
    r = await c.patch(f"/purchasing/po/{po2}", headers=pur, json={
        "items": [{"description": f"Belt {TAG}", "qty": 10, "uom": "pcs",
                   "unit_price": 40, "amount": 400}],
        "total": 400, "currency": "cny", "fx_rate": 2250})
    check("purchasing's save is taken", r.status_code == 200,
          f"{r.status_code} {why(r)}")
    check("...as something queued, not applied", J(r).get("pending_approval") is True,
          str(J(r))[:160])
    got = await get(po2)
    check("...the PO still reads the old currency",
          (got.get("currency") or "IDR") == "IDR", str(got.get("currency")))
    check("...and crucially NOT the new rate against the old currency — "
          "that pairing is the bug this guards",
          got.get("fx_rate") in (None, 1) and float(got.get("fx_rate") or 1) != 2250,
          str(got.get("fx_rate")))

    check("the director has it waiting", await approve_queued(po2) >= 1, "nothing queued")
    got = await get(po2)
    check("...and approving lands both at once",
          got.get("currency") == "CNY" and float(got.get("fx_rate") or 0) == 2250,
          f"{got.get('currency')} @ {got.get('fx_rate')}")
    check("...the currency normalised on the way through the queue",
          got.get("currency") == "CNY", str(got.get("currency")))
    check("...with the lines that were priced in it",
          abs(float(got.get("total") or 0) - 400) < 0.5, str(got.get("total")))

    print("\n── and each still behaves alone as it did ──")
    po3 = await a_po()
    r = await c.patch(f"/purchasing/po/{po3}", headers=pur, json={"fx_rate": 15_500})
    check("a rate on its own still applies on the spot — no queue",
          r.status_code == 200 and not J(r).get("pending_approval"),
          f"{r.status_code} {str(J(r))[:120]}")
    check("...and is on the order", float((await get(po3)).get("fx_rate") or 0) == 15_500,
          str((await get(po3)).get("fx_rate")))

    r = await c.patch(f"/purchasing/po/{po3}", headers=pur, json={"currency": "USD"})
    check("a currency on its own still waits for the director",
          J(r).get("pending_approval") is True, str(J(r))[:140])
    await approve_queued(po3)
    got = await get(po3)
    check("...and on approval the rate that belonged to rupiah is dropped",
          got.get("currency") == "USD" and got.get("fx_rate") is None,
          f"{got.get('currency')} @ {got.get('fx_rate')}")

    # ══ finance: the price, never the currency ═══════════════════════════
    print("\n── finance may price it, not re-denominate it ──")
    po4 = await a_po()
    r = await c.patch(f"/purchasing/po/{po4}", headers=fin, json={"currency": "USD"})
    check("finance cannot change the currency", r.status_code == 403,
          f"{r.status_code} {why(r)}")
    check("...and is told what they may do instead", "rate" in why(r) or "price" in why(r),
          why(r)[:160])
    r = await c.patch(f"/purchasing/po/{po4}", headers=fin, json={"fx_rate": 16_000})
    check("the rate is still theirs, and still immediate",
          r.status_code == 200 and float((await get(po4)).get("fx_rate") or 0) == 16_000,
          f"{r.status_code} {why(r)}")
    r = await c.patch(f"/purchasing/po/{po4}", headers=fin, json={
        "items": [{"description": f"Chain {TAG}-4", "qty": 2, "uom": "pcs",
                   "unit_price": 130}],
        "total": 260})
    check("...as is correcting a price", r.status_code == 200, f"{r.status_code} {why(r)}")
    check("...which still queues for the director",
          J(r).get("pending_approval") is True, str(J(r))[:140])

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)


asyncio.run(main())

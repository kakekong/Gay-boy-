"""A closed supplier request can catch up with the job it was raised for.

The case that was reported: a supplier was asked about a job's 12 lines,
answered, and the request was closed. Then the customer added 2 items. The
price request said 14, the supplier request still said 12, and there was no
way to fix it — a closed request refused the refresh, and the drift warning
never mentioned the new lines at all, because it only ever walked the lines
the supplier request already held. A line that isn't on it can't be seen that
way.

Now the warning reports lines the job has gained, the refresh accepts a
closed request, and doing so reopens it — it holds lines the vendor has never
priced, and a closed request refuses a quote, so leaving it closed would strand
them. What the vendor already quoted is kept.

The part that has to stay exactly as it was is WHICH requests take new lines.
Asking a vendor "about the job" means the job's new items are theirs to price.
Splitting a job — this vendor lines 1–3, that vendor the rest — or picking
particular lines means a new item is nobody's until somebody assigns it. The
shape is now recorded when a request is made; requests made before that are
inferred conservatively, and both paths are pinned here.
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

    async def a_job(tag, n):
        cust = J(await c.post("/customers", headers=s1, json={
            "company_name": f"PT Tambah {tag}", "industry": "mining"}))["id"]
        pr = J(await c.post("/price-requests", headers=s1, json={
            "customer_id": cust,
            "items": [{"description": f"PART {k} {tag}", "qty": k, "uom": "pcs"}
                      for k in range(1, n + 1)]}))
        await c.post(f"/price-requests/{pr['id']}/submit", headers=s1)
        return pr["id"], pr["number"]

    async def grow(pr_id, extra):
        """The customer adds items to the job."""
        cur = J(await c.get(f"/price-requests/{pr_id}", headers=d))
        items = [{k: it.get(k) for k in ("line_no", "description", "qty", "uom")}
                 for it in (cur.get("items") or [])]
        top = max([it["line_no"] or 0 for it in items] or [0])
        for k, desc in enumerate(extra, start=1):
            items.append({"line_no": top + k, "description": desc,
                          "qty": 1, "uom": "pcs"})
        return await c.patch(f"/price-requests/{pr_id}", headers=d,
                             json={"items": items})

    async def spr(spr_id):
        return J(await c.get(f"/purchasing/price-requests/{spr_id}", headers=pur))

    def added(s):
        return [x for x in (s.get("source_drift") or []) if x.get("change") == "added"]

    sup = J(await c.post("/purchasing/suppliers", headers=d, json={
        "name": f"PT Vendor {TAG}", "category": "chain"}))["id"]
    sup2 = J(await c.post("/purchasing/suppliers", headers=d, json={
        "name": f"PT Vendor Dua {TAG}", "category": "chain"}))["id"]

    # ══ the reported case ════════════════════════════════════════════════
    print("\n── asked about the whole job, answered, closed — then the job grows ──")
    pr_id, pr_no = await a_job(TAG, 12)
    made = J(await c.post("/purchasing/price-requests", headers=pur, json={
        "price_request_id": pr_id, "supplier_ids": [sup]}))
    s0 = (made if isinstance(made, list) else [made])[0]
    await c.post(f"/purchasing/price-requests/{s0['id']}/send", headers=pur)
    r = await c.post(f"/purchasing/price-requests/{s0['id']}/quote", headers=pur, json={
        "items": [{"line_no": k, "quoted_price": 100.0 * k} for k in range(1, 13)]})
    check("the vendor prices all 12 lines", r.status_code == 200, f"{r.status_code} {why(r)}")
    r = await c.post(f"/purchasing/price-requests/{s0['id']}/close", headers=pur,
                     json={"reason": "done for now"})
    check("...and the request is closed", r.status_code == 200 and
          (await spr(s0["id"])).get("status") == "closed", f"{r.status_code} {why(r)}")

    r = await grow(pr_id, [f"EXTRA A {TAG}", f"EXTRA B {TAG}"])
    check("the customer adds 2 items to the job", r.status_code == 200,
          f"{r.status_code} {why(r)}")
    pr_now = J(await c.get(f"/price-requests/{pr_id}", headers=d))
    check("...so the price request has 14 lines", len(pr_now.get("items") or []) == 14,
          str(len(pr_now.get("items") or [])))

    s = await spr(s0["id"])
    check("the supplier request still has 12 — nothing rewrites it on its own",
          s.get("lines_total") == 12, str(s.get("lines_total")))
    check("...but it now SAYS the job gained 2 lines — before, a line not on "
          "it could never be reported",
          len(added(s)) == 2, str(s.get("source_drift"))[:200])
    check("...naming them", {x.get("description") for x in added(s)}
          == {f"EXTRA A {TAG}", f"EXTRA B {TAG}"}, str(added(s)))
    check("...and a closed request can be brought up to date",
          s.get("may_refresh") is True, str(s.get("may_refresh")))

    r = await c.post(f"/purchasing/price-requests/{s0['id']}/refresh-from-source",
                     headers=pur, json={})
    body = J(r)
    check("refreshing the closed request is accepted", r.status_code == 200,
          f"{r.status_code} {why(r)}")
    check("...it pulls in the 2 new lines", len(body.get("added") or []) == 2,
          str(body.get("added")))
    check("...and says it reopened from closed", body.get("reopened_from") == "closed",
          str(body.get("reopened_from")))

    s = await spr(s0["id"])
    check("the supplier request now has 14 lines", s.get("lines_total") == 14,
          str(s.get("lines_total")))
    check("...the 12 the vendor priced keep their prices",
          s.get("lines_quoted") == 12, str(s.get("lines_quoted")))
    check("...and it is open again as 'quoted', since the vendor had answered",
          s.get("status") == "quoted", str(s.get("status")))
    check("...with nothing left to report", not (s.get("source_drift") or []),
          str(s.get("source_drift")))
    check("...and a note saying what happened",
          "reopened" in (s.get("notes") or "").lower(), str(s.get("notes"))[-160:])

    new_nos = sorted(i["line_no"] for i in (s.get("items") or [])
                     if i.get("quoted_price") is None)
    r = await c.post(f"/purchasing/price-requests/{s0['id']}/quote", headers=pur, json={
        "items": [{"line_no": k, "quoted_price": 55.0} for k in new_nos]})
    check("the vendor's price for the 2 new lines can now be recorded — a closed "
          "request refuses a quote, which is why it had to reopen",
          r.status_code == 200, f"{r.status_code} {why(r)}")
    s = await spr(s0["id"])
    check("...and every one of the 14 is answered", s.get("lines_quoted") == 14,
          str(s.get("lines_quoted")))

    # ══ closed, nothing changed ══════════════════════════════════════════
    print("\n── a closed request with nothing to catch up on ──")
    pr2, _ = await a_job(f"N{TAG}", 3)
    m = J(await c.post("/purchasing/price-requests", headers=pur, json={
        "price_request_id": pr2, "supplier_ids": [sup]}))
    s2 = (m if isinstance(m, list) else [m])[0]
    await c.post(f"/purchasing/price-requests/{s2['id']}/close", headers=pur,
                 json={"reason": "no"})
    r = await c.post(f"/purchasing/price-requests/{s2['id']}/refresh-from-source",
                     headers=pur, json={})
    check("refreshing it is harmless", r.status_code == 200, f"{r.status_code} {why(r)}")
    check("...and it stays closed, because nothing changed",
          (await spr(s2["id"])).get("status") == "closed",
          str((await spr(s2["id"])).get("status")))

    # ══ a split job ══════════════════════════════════════════════════════
    print("\n── a job split between two vendors ──")
    pr3, _ = await a_job(f"S{TAG}", 6)
    m = J(await c.post("/purchasing/price-requests", headers=pur, json={
        "price_request_id": pr3,
        "assignments": [
            {"supplier_id": sup, "lines": [{"price_request_id": pr3, "line_no": k}
                                           for k in (1, 2, 3)]},
            {"supplier_id": sup2, "lines": [{"price_request_id": pr3, "line_no": k}
                                            for k in (4, 5, 6)]},
        ]}))
    rows = m if isinstance(m, list) else [m]
    a = next((x for x in rows if x.get("supplier_id") == sup), {})
    b = next((x for x in rows if x.get("supplier_id") == sup2), {})
    check("the job is split: 3 lines each", a.get("lines_total") == 3
          and b.get("lines_total") == 3, str([x.get("lines_total") for x in rows]))
    await grow(pr3, [f"SPLIT NEW {TAG}"])
    check("when the job grows, NEITHER half claims the new line — it is nobody's "
          "until somebody assigns it",
          not added(await spr(a["id"])) and not added(await spr(b["id"])),
          f"{added(await spr(a['id']))} / {added(await spr(b['id']))}")
    await c.post(f"/purchasing/price-requests/{a['id']}/refresh-from-source",
                 headers=pur, json={})
    check("...and refreshing a half does not pull it in",
          (await spr(a["id"])).get("lines_total") == 3,
          str((await spr(a["id"])).get("lines_total")))

    # ══ hand-picked lines ════════════════════════════════════════════════
    print("\n── a vendor asked about particular lines only ──")
    pr4, _ = await a_job(f"P{TAG}", 5)
    m = J(await c.post("/purchasing/price-requests", headers=pur, json={
        "price_request_id": pr4, "supplier_ids": [sup],
        "lines": [{"price_request_id": pr4, "line_no": k} for k in (1, 2)]}))
    s4 = (m if isinstance(m, list) else [m])[0]
    await grow(pr4, [f"PICK NEW {TAG}"])
    check("a request for hand-picked lines does not claim the job's new ones",
          not added(await spr(s4["id"])), str(added(await spr(s4["id"]))))

    # ══ requests made before the shape was recorded ══════════════════════
    print("\n── requests from before the shape was recorded ──")
    from app.core.db import SessionLocal
    from app.models.purchasing import SupplierPriceRequest as SPR
    async def forget_shape(ids):
        async with SessionLocal() as db:
            for i in ids:
                row = await db.get(SPR, uuid.UUID(i))
                row.meta = {}
            await db.commit()

    pr5, _ = await a_job(f"L{TAG}", 4)
    m = J(await c.post("/purchasing/price-requests", headers=pur, json={
        "price_request_id": pr5, "supplier_ids": [sup, sup2]}))
    old_whole = m if isinstance(m, list) else [m]
    await forget_shape([x["id"] for x in old_whole])
    await grow(pr5, [f"OLD WHOLE {TAG}"])
    counts = [len(added(await spr(x["id"]))) for x in old_whole]
    check("an old 'ask everyone' request is recognised as the whole job and "
          "reports the new line",
          counts == [1] * len(old_whole), str(counts))

    pr6, _ = await a_job(f"M{TAG}", 6)
    m = J(await c.post("/purchasing/price-requests", headers=pur, json={
        "price_request_id": pr6,
        "assignments": [
            {"supplier_id": sup, "lines": [{"price_request_id": pr6, "line_no": k}
                                           for k in (1, 2, 3)]},
            {"supplier_id": sup2, "lines": [{"price_request_id": pr6, "line_no": k}
                                            for k in (4, 5, 6)]},
        ]}))
    old_split = m if isinstance(m, list) else [m]
    await forget_shape([x["id"] for x in old_split])
    await grow(pr6, [f"OLD SPLIT {TAG}"])
    reports = [added(await spr(x["id"])) for x in old_split]
    check("an old split is still recognised as a split — including the half "
          "holding lines 1–3, which looks like a whole job on its own",
          all(not r for r in reports), str(reports))

    # ══ cancelled stays void ═════════════════════════════════════════════
    print("\n── a cancelled request ──")
    pr7, _ = await a_job(f"C{TAG}", 2)
    m = J(await c.post("/purchasing/price-requests", headers=pur, json={
        "price_request_id": pr7, "supplier_ids": [sup]}))
    s7 = (m if isinstance(m, list) else [m])[0]
    from app.core.db import SessionLocal as _SL
    async with _SL() as db:
        row = await db.get(SPR, uuid.UUID(s7["id"]))
        row.status = "cancelled"
        await db.commit()
    await grow(pr7, [f"VOID {TAG}"])
    r = await c.post(f"/purchasing/price-requests/{s7['id']}/refresh-from-source",
                     headers=pur, json={})
    check("a cancelled request is still refused — it was voided, not finished",
          r.status_code == 409, f"{r.status_code} {why(r)}")

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    for f in FAIL:
        print("  ✗", f)


asyncio.run(main())

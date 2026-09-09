"""A work order added by mistake can be taken off the board.

A work order is a task card — receiving, warehousing, QC, packaging, delivery —
not a record that something happened. One filed by accident (wrong stage, wrong
project, added twice) was clutter with no way to remove it, and the thing people
reach for instead is ticking it complete. That is worse than the mistake: the
board then says work was done that nobody did, and the QC card doing it also
unlocks invoicing.

So it can be deleted, by the same roles that file one. Two boundaries:

* **A completed card is a claim that the work happened.** Removing that is
  editing history rather than tidying a mistake, so only the director may —
  they are the one who can weigh whether the tick was itself the accident.
* **Deleting is not undoing.** The project's stage does not walk backwards and
  stock is not un-received. Filing the card may have advanced the job, but the
  stage records the furthest point reached and logistics, invoice gates and the
  ops board are already resting on it; the goods that arrived were recorded by
  a goods receipt and its movements, not by the card that reminded somebody to
  go and count. Both are checked here, because "delete" invites the assumption
  that everything it touched comes back.
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
    s1 = await login("sales1@demo.local")
    pur = await login("purchasing@demo.local")
    adm = await login("admin@demo.local")

    # ── a job at production, so ops work orders are allowed ──────────────
    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Hapus {TAG}", "industry": "mining"}))["id"]
    pr = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [{"description": f"Chain {TAG}", "qty": 6, "uom": "pcs",
                   "category": "roller_chain"}]}))
    await c.post(f"/price-requests/{pr['id']}/submit", headers=s1)
    await c.post(f"/price-requests/{pr['id']}/price", headers=pur,
                 json={"items": [{"line_no": 1, "cost_price": 100, "basis": "unit"}]})
    await c.post(f"/price-requests/{pr['id']}/approve", headers=d,
                 json={"items": [{"line_no": 1, "sell_price": 200, "basis": "unit"}]})
    q = J(await c.post(f"/quotations/from-price-request/{pr['id']}", headers=s1))
    await c.post(f"/quotations/{q['id']}/submit", headers=s1)
    await c.post(f"/quotations/{q['id']}/approve", headers=d, json={"decision": "approve"})
    cpo = J(await c.post("/customer-pos", headers=s1, json={
        "customer_id": cust, "quotation_id": q["id"], "number": f"CPO-{TAG}",
        "po_date": "2026-09-08",
        "items": [{"description": f"Chain {TAG}", "qty": 6, "unit_price": 200}]}))
    await c.post(f"/customer-pos/{cpo['id']}/approve", headers=d, json={"decision": "approve"})
    proj = J(await c.get(f"/customer-pos/{cpo['id']}", headers=d))["project_id"]

    await c.post(f"/operation/projects/{proj}/skip-drawing", headers=d,
                 json={"reason": "catalogue part"})
    await c.patch(f"/operation/projects/{proj}/logistics", headers=pur,
                  json={"delivery_mode": "local", "est_delivery_date": "2026-10-01"})
    for key in ("invoice", "packing_list"):
        await c.post(f"/operation/projects/{proj}/import-docs/{key}/upload", headers=pur,
                     files={"file": (f"{key}.pdf", b"%PDF-1.4 d", "application/pdf")},
                     data={"note": "x"})
        await c.post(f"/operation/projects/{proj}/import-docs/{key}/decide", headers=d,
                     json={"decision": "approve"})
    await c.post(f"/operation/projects/{proj}/confirm-delivery", headers=pur)

    async def wos():
        full = J(await c.get(f"/operation/projects/{proj}/full", headers=d))
        return full.get("work_orders") or []

    async def status():
        full = J(await c.get(f"/operation/projects/{proj}/full", headers=d))
        return full["project"]["status"]

    check("the job has its receiving work order", len(await wos()) == 1,
          str([w["code"] for w in await wos()]))

    # ══ the accident ═════════════════════════════════════════════════════
    print("\n── a work order is filed by mistake ──")
    r = await c.post(f"/operation/projects/{proj}/work-orders", headers=pur, json={
        "code": f"WO-OOPS-{TAG}", "stage": "warehousing", "notes": "wrong project"})
    check("it is filed", r.status_code == 201, f"{r.status_code} {why(r)}")
    oops = J(r)["id"]
    check("...and shows on the board", len(await wos()) == 2, str(len(await wos())))

    print("\n── and it can be taken off ──")
    r = await c.delete(f"/operation/work-orders/{oops}", headers=s1)
    check("sales cannot remove one", r.status_code == 403, str(r.status_code))
    r = await c.delete(f"/operation/work-orders/{oops}", headers=pur)
    check("whoever files one can remove it", r.status_code == 204,
          f"{r.status_code} {why(r)}")
    check("...and it is gone from the board", len(await wos()) == 1,
          str([w["code"] for w in await wos()]))
    r = await c.delete(f"/operation/work-orders/{oops}", headers=pur)
    check("removing it twice says it is not there", r.status_code == 404,
          str(r.status_code))

    print("\n── admin can too, since admin can file them ──")
    r = await c.post(f"/operation/projects/{proj}/work-orders", headers=adm, json={
        "code": f"WO-ADM-{TAG}", "stage": "warehousing"})
    wo_adm = J(r).get("id")
    r = await c.delete(f"/operation/work-orders/{wo_adm}", headers=adm)
    check("admin removes their own", r.status_code == 204, f"{r.status_code} {why(r)}")

    # ══ a completed card is a claim about work done ══════════════════════
    print("\n── but a completed one is somebody saying the work happened ──")
    r = await c.post(f"/operation/projects/{proj}/work-orders", headers=pur, json={
        "code": f"WO-DONE-{TAG}", "stage": "warehousing"})
    done_id = J(r)["id"]
    r = await c.patch(f"/operation/work-orders/{done_id}", headers=adm,
                      params={"completed": True})
    check("it is marked complete", r.status_code == 200, f"{r.status_code} {why(r)}")
    r = await c.delete(f"/operation/work-orders/{done_id}", headers=pur)
    check("purchasing may not remove a completed one", r.status_code == 409,
          f"{r.status_code} {why(r)}")
    check("...and is told why", "complete" in why(r), why(r)[:160])
    r = await c.delete(f"/operation/work-orders/{done_id}", headers=adm)
    check("nor admin", r.status_code == 409, str(r.status_code))
    r = await c.delete(f"/operation/work-orders/{done_id}", headers=d)
    check("the director may — the tick might have been the accident",
          r.status_code == 204, f"{r.status_code} {why(r)}")

    # ══ deleting is not undoing ══════════════════════════════════════════
    print("\n── deleting a card does not walk the job backwards ──")
    before = await status()
    r = await c.post(f"/operation/projects/{proj}/work-orders", headers=pur, json={
        "code": f"WO-QC-{TAG}", "stage": "qc"})
    qc_id = J(r)["id"]
    check("filing a QC card advanced the job", await status() == "qc",
          f"{before} -> {await status()}")
    await c.delete(f"/operation/work-orders/{qc_id}", headers=pur)
    check("...and removing it leaves the job where it got to",
          await status() == "qc", await status())

    print("\n── nor does it un-receive the goods ──")
    sup = J(await c.post("/purchasing/suppliers", headers=pur, json={
        "name": f"PT Vendor {TAG}", "country": "ID"}))["id"]
    po = J(await c.post("/purchasing/po", headers=d, json={
        "supplier_id": sup, "project_id": proj, "po_date": "2026-09-08",
        "items": [{"description": f"Chain {TAG}", "qty": 6, "unit_price": 100,
                   "uom": "pcs"}]}))
    await c.post(f"/operation/projects/{proj}/receiving", headers=pur, json={
        "po_id": po["id"], "lines": [{"line_no": 1, "qty": 4}]})

    async def stock():
        rows = J(await c.get("/inventory", headers=d, params={"limit": 500}))
        rows = rows if isinstance(rows, list) else rows.get("items", [])
        it = next((x for x in rows if f"Chain {TAG}" in (x.get("name") or "")), None)
        return float(it["current_stock"]) if it else None

    check("four of the six were counted in", await stock() == 4, str(await stock()))
    rcv = next(w for w in await wos() if w["stage"] == "receiving")
    r = await c.delete(f"/operation/work-orders/{rcv['id']}", headers=d)
    check("the receiving card is removed", r.status_code == 204,
          f"{r.status_code} {why(r)}")
    check("...and the goods are still on the shelf — a receipt recorded them, "
          "not the card", await stock() == 4, str(await stock()))
    grs = J(await c.get("/purchasing/gr", headers=pur, params={"po_id": po["id"]}))
    check("...with the goods receipt still on file", len(grs) == 1, str(len(grs)))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)


asyncio.run(main())

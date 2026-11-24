"""Ten lines quoted, the customer orders three: only the three go through.

* The customer PO and the project come to the three lines.
* The invoice defaults to the three lines (it used to take the quotation's
  ten), with the quotation's discount applied in proportion.
* The project's order card shows all ten, the seven not ordered marked.
* A supplier price request from the price request asks about the three; a
  line not ordered can still be picked by hand.
* The supplier PO form offers the seven unticked and leaves them out of
  the total.
* No customer PO yet: nothing is held back, as before.
"""
import asyncio, os, sys, uuid
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123",
    STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import httpx, logging; logging.disable(logging.INFO)
TAG = uuid.uuid4().hex[:5].upper()
PASS, FAIL = [], []
def check(n, c, d=""):
    (PASS if c else FAIL).append(n); print(("  PASS " if c else "  FAIL ")+n+(f"  [{d}]" if d and not c else ""))
def J(r):
    try: return r.json()
    except Exception: return {"_": r.text[:200]}


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    from app.core.db import SessionLocal
    from sqlalchemy import select
    from app.models.finance import Invoice
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t/api/v1", timeout=180)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d, s1, pur, adm = [await login(f"{x}@demo.local") for x in ("director", "sales1", "purchasing", "admin")]
    sup = J(await c.post("/purchasing/suppliers", headers=d, json={"name": f"PT PARSIAL {TAG}"}))["id"]

    async def quoted_job(discount_pct=0):
        cust = J(await c.post("/customers", headers=s1, json={"company_name": f"PT SEBAGIAN {TAG}{discount_pct}", "industry": "mining"}))["id"]
        pr = J(await c.post("/price-requests", headers=s1, json={"customer_id": cust, "items": [
            {"description": f"ITEM {n} {TAG}", "qty": 2, "uom": "pcs"} for n in range(1, 11)]}))["id"]
        await c.post(f"/price-requests/{pr}/submit", headers=s1)
        await c.post(f"/price-requests/{pr}/price", headers=d, json={"items": [{"line_no": n, "cost_price": 100_000, "basis": "unit"} for n in range(1, 11)]})
        await c.post(f"/price-requests/{pr}/approve", headers=d, json={"items": [{"line_no": n, "sell_price": 150_000, "basis": "unit"} for n in range(1, 11)]})
        qid = J(await c.post(f"/quotations/from-price-request/{pr}", headers=s1))["id"]
        if discount_pct:
            await c.patch(f"/quotations/{qid}", headers=s1, json={"discount_pct": discount_pct})
        await c.post(f"/quotations/{qid}/submit", headers=s1)
        await c.post(f"/quotations/{qid}/approve", headers=d, json={"notes": ""})
        return cust, pr, qid

    print("\n── a supplier request before any customer PO: all ten, as before ──")
    cust, pr, qid = await quoted_job()
    r = J(await c.post("/purchasing/price-requests", headers=pur, json={"supplier_ids": [sup], "price_request_id": pr}))
    early = r[0] if isinstance(r, list) else r
    check("no customer PO yet: all ten lines asked about", len(early.get("items", [])) == 10, str(len(early.get("items", []))))

    print("\n── the customer orders lines 2, 5 and 9 ──")
    qi = J(await c.get(f"/quotations/{qid}", headers=s1))["items"]
    picked = [i for i in qi if i.get("line_no") in (2, 5, 9)]
    cpo = J(await c.post("/customer-pos", headers=s1, json={"customer_id": cust, "quotation_id": qid, "number": f"PO-PART-{TAG}",
        "items": [{"description": i["description"], "qty": i["qty"], "unit_price": i["unit_price"], "uom": i.get("uom"),
                   "line_no": i.get("line_no")} for i in picked], "is_downpayment": False}))
    check("the PO holds the three lines: Rp 900.000", len(cpo.get("items", [])) == 3 and cpo.get("total") == 900_000, str(cpo.get("total")))
    await c.post(f"/quotations/{qid}/won", headers=d)
    proj = J(await c.post(f"/customer-pos/{cpo['id']}/approve", headers=d, json={"notes": ""}))["project_id"]
    full = J(await c.get(f"/operation/projects/{proj}/full", headers=pur))
    card = (full.get("price_request") or {})
    flags = {i["line_no"]: i.get("ordered") for i in card.get("items", [])}
    check("the order card keeps all ten lines", len(flags) == 10, str(len(flags)))
    check("...lines 2, 5, 9 ordered; the other seven marked not ordered",
          [n for n, f in flags.items() if f] == [2, 5, 9] and card.get("not_ordered") == 7, str(flags))

    print("\n── purchasing ──")
    r = J(await c.post("/purchasing/price-requests", headers=pur, json={"supplier_ids": [sup], "price_request_id": pr}))
    spr = r[0] if isinstance(r, list) else r
    src = sorted(int(i.get("source_line_no")) for i in spr.get("items", []))
    check("a supplier request now asks about the three ordered lines only", src == [2, 5, 9], str(src))
    r = J(await c.post("/purchasing/price-requests", headers=pur, json={"supplier_ids": [sup], "price_request_id": pr,
        "lines": [{"price_request_id": pr, "line_no": 7}]}))
    spr2 = r[0] if isinstance(r, list) else r
    check("...a line not ordered can still be picked by hand",
          [int(i.get("source_line_no")) for i in spr2.get("items", [])] == [7], str(spr2)[:160])
    pf = J(await c.get("/purchasing/po/prefill", headers=pur, params={"price_request_id": pr}))
    items = pf.get("items", [])
    check("the supplier PO form marks the seven as not on the customer's PO",
          len(items) == 10 and sorted(i["line_no"] for i in items if i.get("customer_ordered")) == [2, 5, 9], str(items)[:200])
    check("...and its total is the three ordered lines: Rp 600.000 at cost", pf.get("total") == 600_000, str(pf.get("total")))

    print("\n── the invoice ──")
    await c.post(f"/operation/projects/{proj}/qc", headers=adm, json={"decision": "pass"})
    r = await c.post(f"/operation/projects/{proj}/issue-invoice", headers=d, data={"invoice_type": "single"})
    async with SessionLocal() as db:
        inv = await db.scalar(select(Invoice).where(Invoice.project_id == proj).order_by(Invoice.created_at.desc()))
    check("the invoice is for the three ordered lines: Rp 900.000 before PPN (was Rp 3.000.000)",
          r.status_code in (200, 201) and inv and float(inv.amount) == 900_000, f"{r.status_code} {inv and float(inv.amount)}")
    check("...PPN 11% on that", inv and abs(float(inv.tax_amount) - 99_000) < 0.01, str(inv and float(inv.tax_amount)))

    print("\n── with a discount on the quotation ──")
    cust2, pr2, qid2 = await quoted_job(discount_pct=10)
    qi2 = J(await c.get(f"/quotations/{qid2}", headers=s1))["items"]
    pk2 = [i for i in qi2 if i.get("line_no") in (1, 2)]
    cpo2 = J(await c.post("/customer-pos", headers=s1, json={"customer_id": cust2, "quotation_id": qid2, "number": f"PO-DISC-{TAG}",
        "items": [{"description": i["description"], "qty": i["qty"], "unit_price": i["unit_price"], "uom": i.get("uom"),
                   "line_no": i.get("line_no")} for i in pk2], "is_downpayment": False}))
    await c.post(f"/quotations/{qid2}/won", headers=d)
    proj2 = J(await c.post(f"/customer-pos/{cpo2['id']}/approve", headers=d, json={"notes": ""}))["project_id"]
    await c.post(f"/operation/projects/{proj2}/qc", headers=adm, json={"decision": "pass"})
    await c.post(f"/operation/projects/{proj2}/issue-invoice", headers=d, data={"invoice_type": "single"})
    async with SessionLocal() as db:
        inv2 = await db.scalar(select(Invoice).where(Invoice.project_id == proj2).order_by(Invoice.created_at.desc()))
    q2 = J(await c.get(f"/quotations/{qid2}", headers=d))
    check("10% off: two lines of Rp 300.000 → Rp 540.000 before PPN",
          inv2 and abs(float(inv2.amount) - 540_000) < 0.01, f"{inv2 and float(inv2.amount)} (quote discount {q2.get('discount_amount')})")

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

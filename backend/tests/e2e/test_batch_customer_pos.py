"""A quotation ordered in batches: each PO its own project, Partially won.

* Quotation of 10 lines (line 1: 100 m). Batch 1 orders lines 2, 5, 9 and
  60 m of line 1. Approved: its own project. Won → "partially_won"; the
  books carry batch 1 only.
* Over-ordering a line (50 m when 40 m is open) is refused, naming what's
  left; a further batch with lines typed in by hand is refused.
* Batch 2 orders the rest (40 m of line 1, lines 3, 4, 6, 7, 8, 10).
  Approved: a second, different project; the quotation is "won" and the
  books carry the whole quotation, as a single Won always did.
* Each project's order card, supplier PO form and invoice are its own batch.
* Deleting batch 2 takes the quotation back to Partially won and its share
  off the books; filing it again reuses the project it left behind.
* Sales figures count a partially won quotation by what was ordered.
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
def why(r):
    b = J(r)
    return str(b.get("detail") or (b.get("errors") or [{}])[0].get("message", "")) if isinstance(b, dict) else str(b)

# description, qty, uom, sell
LINES = [("CHAIN", 100, "meter", 100_000), ("SPROCKET", 2, "pcs", 3_000_000), ("PIN", 50, "pcs", 10_000),
         ("ROLLER", 30, "pcs", 200_000), ("SHACKLE", 40, "pcs", 100_000), ("PULLEY", 1, "pcs", 10_000_000),
         ("PAD", 50, "pcs", 40_000), ("BEARING", 8, "pcs", 600_000), ("COTTER", 5, "pcs", 200_000),
         ("TAKEUP", 2, "set", 5_000_000)]


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    from app.core.db import SessionLocal
    from sqlalchemy import select
    from app.models.finance import Invoice
    from app.models.quotation import Quotation
    from app.models.account import Account
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t/api/v1", timeout=180)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d, s1, pur, adm = [await login(f"{x}@demo.local") for x in ("director", "sales1", "purchasing", "admin")]

    async def bal(no):
        async with SessionLocal() as db:
            a = await db.scalar(select(Account).where(Account.account_no == no))
            return float(a.balance or 0) if a else 0.0
    async def quote_row(qid):
        async with SessionLocal() as db:
            return await db.get(Quotation, qid)

    cust = J(await c.post("/customers", headers=s1, json={"company_name": f"PT BERTAHAP {TAG}", "industry": "mining"}))["id"]
    pr = J(await c.post("/price-requests", headers=s1, json={"customer_id": cust, "items": [
        {"description": f"{n} {TAG}", "qty": q, "uom": u} for n, q, u, _ in LINES]}))["id"]
    await c.post(f"/price-requests/{pr}/submit", headers=s1)
    await c.post(f"/price-requests/{pr}/price", headers=d, json={"items": [{"line_no": i + 1, "cost_price": l[3] // 2, "basis": "unit"} for i, l in enumerate(LINES)]})
    await c.post(f"/price-requests/{pr}/approve", headers=d, json={"items": [{"line_no": i + 1, "sell_price": l[3], "basis": "unit"} for i, l in enumerate(LINES)]})
    qid = J(await c.post(f"/quotations/from-price-request/{pr}", headers=s1))["id"]
    await c.post(f"/quotations/{qid}/submit", headers=s1)
    await c.post(f"/quotations/{qid}/approve", headers=d, json={"notes": ""})
    qi = {i["line_no"]: i for i in J(await c.get(f"/quotations/{qid}", headers=s1))["items"]}
    def po_lines(spec):
        return [{"description": qi[n]["description"], "qty": q, "unit_price": qi[n]["unit_price"],
                 "uom": qi[n].get("uom"), "line_no": n} for n, q in spec]
    full_net = sum(q * p for _, q, _, p in LINES)

    print("\n── batch 1: lines 2, 5, 9 and 60 m of line 1 ──")
    b1_spec = [(1, 60), (2, 2), (5, 40), (9, 5)]
    b1_net = 60 * 100_000 + 2 * 3_000_000 + 40 * 100_000 + 5 * 200_000      # 17.000.000
    r = await c.post("/customer-pos", headers=s1, json={"customer_id": cust, "quotation_id": qid,
        "number": f"PO-B1-{TAG}", "items": po_lines(b1_spec), "is_downpayment": False})
    po1 = J(r)
    check("batch 1 filed", r.status_code == 201 and po1.get("total") == b1_net, f"{r.status_code} {why(r)}")
    rec0, rev0 = await bal("110301"), await bal("400001")
    await c.post(f"/quotations/{qid}/won", headers=d)
    p1 = J(await c.post(f"/customer-pos/{po1['id']}/approve", headers=d, json={"notes": ""})).get("project_id")
    check("batch 1 approved: its own project", bool(p1), str(p1))
    q = await quote_row(qid)
    check("the quotation is Partially won", q.status == "partially_won", q.status)
    check("...its ordered value is batch 1 with PPN: Rp 18.870.000",
          abs(float(q.ordered_total) - b1_net * 1.11) < 0.01, str(q.ordered_total))
    check("...and the books carry batch 1 only: Penjualan +Rp 17.000.000, Piutang +Rp 18.870.000",
          abs((await bal("400001")) - rev0 - b1_net) < 0.01 and abs((await bal("110301")) - rec0 - b1_net * 1.11) < 0.01,
          f"rev {await bal('400001') - rev0} rec {await bal('110301') - rec0}")
    o = J(await c.get(f"/quotations/{qid}/orders", headers=s1))
    L = {x["line_no"]: x for x in o.get("lines", [])}
    check("the order status shows line 1: 60 ordered, 40 open; line 3 all open",
          L[1]["ordered"] == 60 and L[1]["open"] == 40 and L[3]["open"] == 50 and len(o["pos"]) == 1, str(L.get(1)))

    print("\n── what a second batch may not do ──")
    r = await c.post("/customer-pos", headers=s1, json={"customer_id": cust, "quotation_id": qid,
        "number": f"PO-BAD-{TAG}", "items": po_lines([(1, 50)]), "is_downpayment": False})
    check("50 m of line 1 when 40 m is open: refused, naming what's left",
          r.status_code == 409 and "40" in why(r) and "left" in why(r), f"{r.status_code} {why(r)}")
    r = await c.post("/customer-pos", headers=s1, json={"customer_id": cust, "quotation_id": qid,
        "number": f"PO-TYPED-{TAG}", "items": [{"description": "something", "qty": 1, "unit_price": 1}], "is_downpayment": False})
    check("a further batch with lines typed in by hand: refused", r.status_code == 400, f"{r.status_code} {why(r)}")

    print("\n── batch 2: the rest ──")
    b2_spec = [(1, 40), (3, 50), (4, 30), (6, 1), (7, 50), (8, 8), (10, 2)]
    b2_net = full_net - b1_net
    r = await c.post("/customer-pos", headers=s1, json={"customer_id": cust, "quotation_id": qid,
        "number": f"PO-B2-{TAG}", "items": po_lines(b2_spec), "is_downpayment": False})
    po2 = J(r)
    check("batch 2 filed against the same quotation", r.status_code == 201, f"{r.status_code} {why(r)}")
    p2 = J(await c.post(f"/customer-pos/{po2['id']}/approve", headers=d, json={"notes": ""})).get("project_id")
    check("batch 2 approved: a second, different project", p2 and p2 != p1, f"{p1} / {p2}")
    q = await quote_row(qid)
    check("everything ordered: the quotation is Won", q.status == "won", q.status)
    check("...ordered value = the whole quotation", abs(float(q.ordered_total) - float(q.total)) < 0.01,
          f"{q.ordered_total} vs {q.total}")
    check("...and the books carry the whole of it: Penjualan +Rp %s" % f"{full_net:,}",
          abs((await bal("400001")) - rev0 - full_net) < 0.01, f"{await bal('400001') - rev0}")

    print("\n── each project is its own batch ──")
    for name, pid, spec in (("project 1", p1, dict(b1_spec)), ("project 2", p2, dict(b2_spec))):
        card = (J(await c.get(f"/operation/projects/{pid}/full", headers=pur)).get("price_request") or {})
        active = sorted(i["line_no"] for i in card.get("items", []) if i.get("ordered"))
        l1 = next((i for i in card.get("items", []) if i["line_no"] == 1), {})
        check(f"{name}: order card has its own lines, line 1 at {spec[1]:g} m",
              active == sorted(spec) and l1.get("ordered_qty") == spec[1], f"{active} {l1.get('ordered_qty')}")
        pf = J(await c.get("/purchasing/po/prefill", headers=pur, params={"project_id": pid}))
        ticked = {i["line_no"]: i["qty"] for i in pf.get("items", []) if i.get("customer_ordered")}
        check(f"{name}: supplier PO form ticks its lines at its quantities",
              sorted(ticked) == sorted(spec) and ticked.get(1) == spec[1], str(ticked))

    print("\n── a batch deleted, and filed again ──")
    r = await c.delete(f"/customer-pos/{po2['id']}", headers=d)
    q = await quote_row(qid)
    check("deleting batch 2: back to Partially won", r.status_code == 200 and q.status == "partially_won",
          f"{r.status_code} {q.status} {why(r)}")
    check("...and its share comes off the books", abs((await bal("400001")) - rev0 - b1_net) < 0.01,
          f"{await bal('400001') - rev0}")
    r = await c.post("/customer-pos", headers=s1, json={"customer_id": cust, "quotation_id": qid,
        "number": f"PO-B2B-{TAG}", "items": po_lines(b2_spec), "is_downpayment": False})
    po2b = J(r)
    p2b = J(await c.post(f"/customer-pos/{po2b['id']}/approve", headers=d, json={"notes": ""})).get("project_id")
    check("filed again: Won again, on the project batch 2 left behind",
          p2b == p2 and (await quote_row(qid)).status == "won", f"{p2b} vs {p2}")

    print("\n── invoices ──")
    for pid, net in ((p1, b1_net), (p2, b2_net)):
        await c.post(f"/operation/projects/{pid}/qc", headers=adm, json={"decision": "pass"})
        await c.post(f"/operation/projects/{pid}/issue-invoice", headers=d, data={"invoice_type": "single"})
    async with SessionLocal() as db:
        i1 = await db.scalar(select(Invoice).where(Invoice.project_id == p1))
        i2 = await db.scalar(select(Invoice).where(Invoice.project_id == p2))
    check("each project invoices its own batch: Rp 17.000.000 and the rest",
          i1 and i2 and float(i1.amount) == b1_net and float(i2.amount) == b2_net,
          f"{i1 and float(i1.amount)} / {i2 and float(i2.amount)}")

    print("\n── sales figures ──")
    cust2 = J(await c.post("/customers", headers=s1, json={"company_name": f"PT SEPARUH {TAG}", "industry": "mining"}))["id"]
    pr2 = J(await c.post("/price-requests", headers=s1, json={"customer_id": cust2, "items": [
        {"description": f"A {TAG}", "qty": 10, "uom": "pcs"}, {"description": f"B {TAG}", "qty": 10, "uom": "pcs"}]}))["id"]
    await c.post(f"/price-requests/{pr2}/submit", headers=s1)
    await c.post(f"/price-requests/{pr2}/price", headers=d, json={"items": [{"line_no": n, "cost_price": 50_000, "basis": "unit"} for n in (1, 2)]})
    await c.post(f"/price-requests/{pr2}/approve", headers=d, json={"items": [{"line_no": n, "sell_price": 100_000, "basis": "unit"} for n in (1, 2)]})
    q2 = J(await c.post(f"/quotations/from-price-request/{pr2}", headers=s1))["id"]
    await c.post(f"/quotations/{q2}/submit", headers=s1); await c.post(f"/quotations/{q2}/approve", headers=d, json={"notes": ""})
    qi2 = J(await c.get(f"/quotations/{q2}", headers=s1))["items"]
    r = J(await c.post("/customer-pos", headers=s1, json={"customer_id": cust2, "quotation_id": q2, "number": f"PO-H-{TAG}",
        "items": [{"description": qi2[0]["description"], "qty": 10, "unit_price": 100_000, "line_no": 1}], "is_downpayment": False}))
    await c.post(f"/quotations/{q2}/won", headers=d)
    await c.post(f"/customer-pos/{r['id']}/approve", headers=d, json={"notes": ""})
    cd = J(await c.get(f"/customers/{cust2}/summary", headers=s1))
    def find(o, key):
        if isinstance(o, dict):
            if key in o: return o[key]
            for v in o.values():
                x = find(v, key)
                if x is not None: return x
        return None
    check("a half-ordered quotation counts as won for what was ordered: Rp 1.110.000",
          abs(float(find(cd, "won_revenue") or 0) - 1_110_000) < 0.01, str(find(cd, "won_revenue")))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

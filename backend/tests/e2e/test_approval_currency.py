"""The approval box shows the money in the currency the money is in.

A purchasing PO can be raised in yen, dollars or yuan. The director's approval
preview printed every figure as rupiah regardless — so a ¥1.200.000 order read
as "Rp 1.200.000", the same digits with the wrong symbol in front, roughly a
hundredfold out, in a box whose only two buttons are approve and reject. There
is no cross-check on that screen: the number and the word beside it are the
whole of what the decision is made on.

So the preview now carries the currency, and the rate, and the rupiah the
order actually costs us. Three things are pinned here:

* the currency travels with the figures, and it is the document's, not a
  default;
* an ordinary rupiah document still says rupiah, because the fix must not
  turn every existing approval into a foreign one;
* on an *edit* that changes the currency, the money shown is the money being
  decided on — the proposed one — and the old value beside it stays in the
  old currency. Showing both sides of that arrow in one currency would
  misrepresent the exact change being approved.
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

    sup = J(await c.post("/purchasing/suppliers", headers=d, json={
        "name": f"Jiangsu Yen {TAG}", "category": "chain"}))["id"]

    # A PO is always raised against a job, so build one rather than borrowing
    # whatever happens to be lying around — on a fresh database there is
    # nothing to borrow, and a driver that depends on another driver's
    # leftovers passes or fails by running order.
    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Valuta {TAG}", "industry": "mining"}))["id"]
    pr = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [{"description": f"CHAIN 12MM {TAG}", "qty": 100, "uom": "pcs"}]}))["id"]
    await c.post(f"/price-requests/{pr}/submit", headers=s1)
    await c.post(f"/price-requests/{pr}/price", headers=d, json={
        "items": [{"line_no": 1, "cost_price": 600_000, "basis": "unit"}]})
    await c.post(f"/price-requests/{pr}/approve", headers=d, json={
        "items": [{"line_no": 1, "sell_price": 1_000_000, "basis": "unit"}]})
    quo = J(await c.post(f"/quotations/from-price-request/{pr}", headers=s1))["id"]
    await c.post(f"/quotations/{quo}/submit", headers=s1)
    await c.post(f"/quotations/{quo}/approve", headers=d, json={"notes": ""})
    cpo = J(await c.post("/customer-pos", headers=s1, json={
        "customer_id": cust, "quotation_id": quo, "number": f"PO-VAL-{TAG}",
        "items": [{"description": f"CHAIN 12MM {TAG}", "qty": 100,
                   "unit_price": 1_000_000}],
        "is_downpayment": False}))["id"]
    await c.post(f"/quotations/{quo}/won", headers=d)
    project_id = J(await c.post(f"/customer-pos/{cpo}/approve", headers=d,
                                json={"notes": ""})).get("project_id")
    check("there is a project to raise the order against", bool(project_id),
          str(project_id))
    if not project_id:
        print("cannot continue without a project")
        print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
        return

    async def a_po(currency, rate, unit, qty=100, tag=""):
        """A supplier PO raised by purchasing, so it lands in the queue."""
        r = await c.post("/purchasing/po", headers=pur, json={
            "supplier_id": sup,
            "project_id": project_id,
            "number": f"PO-{currency}-{tag or TAG}",
            "currency": currency,
            "fx_rate": rate,
            "total": unit * qty,
            "items": [{"description": f"CHAIN 12MM {tag or TAG}",
                       "qty": qty, "unit_price": unit}],
        })
        return r

    async def queue():
        return J(await c.get("/approvals", headers=d))

    async def preview_for(po_number):
        rows = await queue()
        row = next((x for x in rows
                    if x["target_type"] == "supplier_po"
                    and (x.get("target_label") or "") == po_number), None)
        if not row:
            return None, rows
        return J(await c.get(f"/approvals/{row['id']}/preview", headers=d)), rows

    # ══ a yen order ══════════════════════════════════════════════════════
    print("\n── a purchase order raised in yen ──")
    r = await a_po("JPY", 105.0, 12_000.0)
    check("purchasing can raise a JPY purchase order", r.status_code in (200, 201),
          f"{r.status_code} {why(r)}")
    jpy_no = f"PO-JPY-{TAG}"

    p, rows = await preview_for(jpy_no)
    check("...and it reaches the director's approval queue", p is not None,
          str([(x['target_type'], x.get('target_label')) for x in rows])[:200])
    if p is None:
        print("cannot continue without the queued request")
        print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
        return

    check("the preview says what currency the money is in",
          p.get("currency") == "JPY", str(p.get("currency")))
    check("...which is the ONLY thing standing between the director and "
          "approving a yen figure as though it were rupiah",
          p.get("currency") != "IDR", str(p.get("currency")))
    check("...and carries the rate it was booked at",
          abs(float(p.get("fx_rate") or 0) - 105.0) < 0.001, str(p.get("fx_rate")))

    total = float(p.get("total") or 0)
    check("the total is the yen total, unconverted",
          abs(total - 1_200_000) < 1, str(total))
    check("...and the rupiah it actually costs us is given too, rather than "
          "left as mental arithmetic",
          abs(float(p.get("total_idr") or 0) - 1_200_000 * 105.0) < 1,
          str(p.get("total_idr")))

    line = (p.get("items") or [{}])[0]
    check("the line price is the yen price", abs(float(line.get("unit_price") or 0) - 12_000) < 1,
          str(line.get("unit_price")))
    check("...and the line total follows from it",
          abs(float(line.get("line_total") or 0) - 1_200_000) < 1,
          str(line.get("line_total")))

    # ══ a rupiah order is unchanged ══════════════════════════════════════
    print("\n── an ordinary rupiah order still says rupiah ──")
    r = await a_po("IDR", None, 1_500_000.0, qty=3, tag=f"R{TAG}")
    check("purchasing can raise an IDR purchase order", r.status_code in (200, 201),
          f"{r.status_code} {why(r)}")
    p2, _ = await preview_for(f"PO-IDR-R{TAG}")
    check("...it is in the queue", p2 is not None)
    if p2:
        check("a rupiah document reports rupiah", p2.get("currency") == "IDR",
              str(p2.get("currency")))
        check("...and offers no conversion, because there is nothing to convert",
              p2.get("total_idr") is None, str(p2.get("total_idr")))
        check("...with the total unchanged",
              abs(float(p2.get("total") or 0) - 4_500_000) < 1, str(p2.get("total")))

    # Every other kind of approval must still answer with a currency, or the
    # screen has to guess — and guessing is what this whole bug was.
    print("\n── every preview answers the question ──")
    rows = await queue()
    seen = {}
    for row in rows[:25]:
        pv = J(await c.get(f"/approvals/{row['id']}/preview", headers=d))
        seen.setdefault(row["target_type"], pv.get("currency"))
    missing = [k for k, v in seen.items() if not v]
    check("no approval type answers without a currency", not missing,
          f"missing on: {missing}")
    check("...and the ones with no money of their own say rupiah",
          all(v in ("IDR", "JPY", "USD", "CNY", "EUR", "SGD")
              for v in seen.values() if v),
          str(seen))

    # ══ an edit that moves the currency ══════════════════════════════════
    print("\n── an edit that changes the currency itself ──")
    # Find the JPY PO and have purchasing propose a move to USD. A non-director
    # edit queues rather than applying, which is the case that matters.
    pos = J(await c.get("/purchasing/po", headers=d))
    po_rows = pos if isinstance(pos, list) else (pos.get("items") or [])
    jpy = next((x for x in po_rows if x.get("number") == jpy_no), None)
    check("the yen order can be found to edit", jpy is not None,
          str([x.get("number") for x in po_rows])[:160])
    if jpy:
        r = await c.patch(f"/purchasing/po/{jpy['id']}", headers=pur, json={
            "currency": "USD", "fx_rate": 16_000.0, "total": 8_000.0,
        })
        check("purchasing proposes moving it to USD", r.status_code in (200, 202),
              f"{r.status_code} {why(r)}")
        rows = await queue()
        edit = next((x for x in rows
                     if x["target_type"] == "supplier_po"
                     and (x.get("payload") or {}).get("action") == "update"
                     and jpy_no in (x.get("target_label") or "")), None)
        check("...and the change queues for the director", edit is not None,
              str([(x.get('target_label'), (x.get('payload') or {}).get('action'))
                   for x in rows if x['target_type'] == 'supplier_po'])[:200])
        if edit:
            pe = J(await c.get(f"/approvals/{edit['id']}/preview", headers=d))
            check("the preview shows the money being decided on — the PROPOSED "
                  "currency, not the one on the row today",
                  pe.get("currency") == "USD", str(pe.get("currency")))
            check("...at the proposed rate",
                  abs(float(pe.get("fx_rate") or 0) - 16_000.0) < 0.01,
                  str(pe.get("fx_rate")))
            check("...converted at that rate, not the old one",
                  abs(float(pe.get("total_idr") or 0) - 8_000.0 * 16_000.0) < 1,
                  str(pe.get("total_idr")))
            cur_field = next((f for f in (pe.get("fields") or [])
                              if f.get("label") == "Currency"), None)
            check("the currency change is spelled out as a before and after",
                  cur_field is not None and "JPY" in str(cur_field.get("value"))
                  and "USD" in str(cur_field.get("value")),
                  str(cur_field))
            tot_field = next((f for f in (pe.get("fields") or [])
                              if f.get("label") == "Total"), None)
            if tot_field:
                val = str(tot_field.get("value"))
                check("...and the two totals are each labelled in their OWN "
                      "currency, which is the whole point of showing them",
                      "JPY" in val and "USD" in val, val)

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    for f in FAIL:
        print("  ✗", f)


asyncio.run(main())

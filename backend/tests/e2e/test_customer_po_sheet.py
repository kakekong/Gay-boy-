"""The customer-PO order confirmation sheet.

The keterangan is an ordinary editable note, but two things on this sheet are
chosen at *download* time rather than stored on the PO, and that is the part
worth pinning:

* **Ship-to.** Office or delivery address. They are routinely different — goods
  go to a site, paperwork goes to head office — and a sheet sent to the wrong
  one costs a truck. When the delivery address is blank the sheet falls back to
  the office rather than printing an empty destination block.
* **The PIC.** Any of the customer's own contacts, not just the primary on the
  customer record, because who owns an order changes order to order. A contact
  belonging to some *other* customer must be refused outright — that would
  print one customer's staff on another's paperwork.
"""
import asyncio, os, sys, uuid
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123", STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import httpx, logging; logging.disable(logging.INFO)
PASS, FAIL = [], []
def check(n,c,d=""):
    (PASS if c else FAIL).append(n); print(("  PASS " if c else "  FAIL ")+n+(f"  [{d}]" if d and not c else ""))
def J(r):
    try: return r.json()
    except: return {"_":r.text[:200]}
async def login(c,e):
    r=await c.post("/auth/login",json={"email":e,"password":"test-pass-123"})
    return {"Authorization":f"Bearer {r.json()['access_token']}"}


def pdf_text(raw: bytes) -> str:
    import fitz
    with fitz.open(stream=raw, filetype="pdf") as d:
        return "\n".join(p.get_text() for p in d)


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=90)
    d = await login(c, "director@demo.local");  s1 = await login(c, "sales1@demo.local")
    s2 = await login(c, "sales2@demo.local");   pu = await login(c, "purchasing@demo.local")
    tag = uuid.uuid4().hex[:5]

    OFFICE = f"Jl. Sudirman Kav 45, Jakarta Pusat [{tag}]"
    SITE = f"Site Satui KM 142, Kalimantan Selatan [{tag}]"

    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Kirim {tag}", "industry": "mining",
        "pic_name": f"Primary Pic {tag}", "pic_position": "Purchasing Manager",
        "phone": "021-555", "email": f"primary-{tag}@x.co.id",
        "company_address": OFFICE, "delivery_address": SITE}))["id"]
    contact = J(await c.post(f"/customers/{cust}/contacts", headers=s1, json={
        "name": f"Site Pic {tag}", "position": "Site Supervisor",
        "phone": "0812-999", "email": f"site-{tag}@x.co.id"}))
    contact_id = contact.get("id")
    check("added a second contact on the customer", bool(contact_id), str(contact)[:140])

    pr = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust, "items": [{"description": f"Gearbox {tag}", "qty": 2, "uom": "pcs"}]}))["id"]
    await c.post(f"/price-requests/{pr}/submit", headers=s1)
    await c.post(f"/price-requests/{pr}/price", headers=pu,
                 json={"items": [{"line_no": 1, "cost_price": 5_000_000, "basis": "unit"}]})
    await c.post(f"/price-requests/{pr}/approve", headers=d,
                 json={"items": [{"line_no": 1, "sell_price": 9_000_000, "basis": "unit"}]})
    quo = J(await c.post(f"/quotations/from-price-request/{pr}", headers=s1))["id"]
    quo_no = J(await c.get(f"/quotations/{quo}", headers=s1)).get("number")
    await c.post(f"/quotations/{quo}/submit", headers=d)
    await c.post(f"/quotations/{quo}/won", headers=d)
    po = J(await c.post("/customer-pos", headers=s1, json={
        "customer_id": cust, "quotation_id": quo, "number": f"PO-SHEET-{tag}",
        "po_date": "2026-07-30",
        "items": [{"description": f"Gearbox {tag}", "qty": 2, "uom": "pcs",
                   "unit_price": 9_000_000}],
        "is_downpayment": False}))
    po_id = po.get("id")
    check("the customer PO was filed", bool(po_id), str(po)[:160])

    # ── 1. keterangan ────────────────────────────────────────────────────────
    KET = f"Kirim bertahap, konfirmasi unloading H-2 [{tag}]"
    r = await c.patch(f"/customer-pos/{po_id}", headers=s1, json={"notes": KET})
    check("the keterangan can be written", r.status_code == 200, J(r))
    check("...and read back", J(await c.get(f"/customer-pos/{po_id}", headers=s1)).get("notes") == KET)

    # ── 2. the options the picker offers ─────────────────────────────────────
    opts = J(await c.get(f"/customer-pos/{po_id}/pdf-options", headers=s1))
    keys = {s["key"]: s for s in opts.get("ship_to", [])}
    check("both addresses are offered", {"office", "delivery"} <= set(keys), str(list(keys)))
    check("the office address is the customer's", keys.get("office", {}).get("address") == OFFICE)
    check("the delivery address is the customer's", keys.get("delivery", {}).get("address") == SITE)
    names = [p["name"] for p in opts.get("pics", [])]
    check("the primary PIC is offered", f"Primary Pic {tag}" in names, str(names))
    check("...and so is the extra contact", f"Site Pic {tag}" in names, str(names))

    # ── 3. the sheet itself ──────────────────────────────────────────────────
    r = await c.get(f"/customer-pos/{po_id}/export.pdf", headers=s1,
                    params={"ship_to": "delivery", "contact_id": contact_id})
    check("the sheet downloads", r.status_code == 200 and r.content[:4] == b"%PDF",
          f"{r.status_code} {r.content[:12]}")
    txt = pdf_text(r.content)
    check("it is the order confirmation", "KONFIRMASI PESANAN" in txt, txt[:120])
    check("it prints the chosen delivery address", "Site Satui" in txt, txt[:400])
    check("...and NOT the office address", "Sudirman" not in txt, txt[:400])
    check("it names the chosen PIC", f"Site Pic {tag}" in txt, txt[:500])
    check("...and not the primary one", f"Primary Pic {tag}" not in txt, txt[:500])
    check("the keterangan is on the sheet", "konfirmasi unloading" in txt.lower(), txt[:600])
    check("the PO number is on it", f"PO-SHEET-{tag}" in txt, txt[:300])
    check("the quotation it came from is referenced", (quo_no or "?") in txt, txt[:300])
    check("the money is on it", "18.000.000" in txt, txt[:600])

    # Switch both choices — the sheet must actually change.
    r2 = await c.get(f"/customer-pos/{po_id}/export.pdf", headers=s1,
                     params={"ship_to": "office"})
    t2 = pdf_text(r2.content)
    check("choosing the office prints the office address", "Sudirman" in t2, t2[:400])
    check("...and drops the site address", "Site Satui" not in t2, t2[:400])
    check("with no contact chosen it falls back to the primary PIC",
          f"Primary Pic {tag}" in t2, t2[:500])

    # ── 4. the guards ────────────────────────────────────────────────────────
    r = await c.get(f"/customer-pos/{po_id}/export.pdf", headers=s1,
                    params={"ship_to": "warehouse"})
    check("an unknown ship_to is rejected", r.status_code == 400, str(r.status_code))

    other = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Lain {tag}", "industry": "mining"}))["id"]
    foreign = J(await c.post(f"/customers/{other}/contacts", headers=s1, json={
        "name": "Someone Else", "position": "Manager"})).get("id")
    if foreign:
        r = await c.get(f"/customer-pos/{po_id}/export.pdf", headers=s1,
                        params={"ship_to": "office", "contact_id": foreign})
        check("a contact from another customer is refused", r.status_code == 400,
              str(r.status_code))

    r = await c.get(f"/customer-pos/{po_id}/export.pdf", headers=s2, params={"ship_to": "office"})
    check("another rep cannot print someone else's order", r.status_code in (403, 404),
          str(r.status_code))
    r = await c.get(f"/customer-pos/{po_id}/pdf-options", headers=s2)
    check("...nor read its options", r.status_code in (403, 404), str(r.status_code))

    # ── 5. an empty delivery address falls back rather than printing blank ───
    # Clear it on the customer we already have, rather than building a second
    # PO — fewer moving parts, and it exercises the same code path.
    r = await c.patch(f"/customers/{cust}", headers=s1, json={"delivery_address": ""})
    check("cleared the delivery address on the customer", r.status_code == 200,
          f"{r.status_code} {str(J(r))[:120]}")
    r = await c.get(f"/customer-pos/{po_id}/export.pdf", headers=s1,
                    params={"ship_to": "delivery"})
    t3 = pdf_text(r.content)
    check("a missing delivery address falls back to the office address",
          "Sudirman" in t3, t3[:400])
    check("...and the heading says so, rather than claiming a delivery address",
          "KIRIM KE — KANTOR" in t3.upper(), t3[:400])

    # Leave no pending approval behind. The drivers share one database and
    # `e2e_dp_flow.py` runs last asserting the customer-PO queue is empty, so a
    # PO filed here and never decided reads to it as a product bug.
    r = await c.post(f"/customer-pos/{po_id}/reject", headers=d,
                     json={"notes": "test fixture — not a real order"})
    check("the driver clears the PO it filed out of the approval queue",
          r.status_code == 200, f"{r.status_code} {str(J(r))[:120]}")

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")


asyncio.run(main())

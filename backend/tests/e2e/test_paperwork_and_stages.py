"""The paperwork reads like the company's own — and the job moves when it should.

From one request, several fixes that all come back to the documents:

* **The invoice lists the goods, with their codes.** Not "1 LOT Pekerjaan
  PRJ-…": each line with its KODE BARANG. A quotation discount prints as
  POTONGAN HARGA down to the billed net, the way the faktur pajak does it.
  KEPADA carries the whole customer record — office address, NPWP and its
  address, phone.
* **The delivery order goes where it is sent.** The ship-to address is picked
  when the sheet is raised (the prefill offers the customer's addresses), with
  a U/P contact; the sheet is made out to it, prints the part code before the
  description, names whoever raised it as "Prepared by" (not the approver),
  and page two is the Surat Jalan Ekspedisi.
* **One work order per stage.**
* **A job at Delivered moves to Invoiced when its invoice is approved.**
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
        return str(b)[:200]
    return str(b.get("detail") or (b.get("errors") or [{}])[0].get("message", ""))
def pdf_text(blob: bytes) -> str:
    import fitz
    with fitz.open(stream=blob, filetype="pdf") as doc:
        return " ".join(p.get_text() for p in doc)


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    from app.core.db import SessionLocal
    from app.models.operation import Project
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)

    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    adm = await login("admin@demo.local")
    fin = await login("finance@demo.local")
    s1 = await login("sales1@demo.local")

    SITE = f"SITE INDO {TAG}\nJL. GERBANG DAYAKU, BAKUNGAN, KUTAI KARTANEGARA 75391"
    OFFICE = f"MENARA PRIMA {TAG}, KAWASAN MEGA KUNINGAN, JAKARTA"
    NPWP_ADDR = f"JALAN GERBANG DAYAKU NO.000 {TAG}, LOA JANAN, KALIMANTAN TIMUR 75591"
    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Kertas {TAG}", "industry": "mining",
        "company_address": OFFICE, "delivery_address": SITE,
        "tax_address": NPWP_ADDR, "tax_id": "0021959952725000",
        "phone": "+622157948028"}))["id"]
    await c.post(f"/customers/{cust}/contacts", headers=s1, json={
        "name": f"Bapak Agus {TAG}", "phone": "082239684603", "is_primary": True})
    pr = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [{"description": f"CHAIN FEEDER VOLER {TAG}", "qty": 100, "uom": "meter"}]}))["id"]
    await c.post(f"/price-requests/{pr}/submit", headers=s1)
    await c.post(f"/price-requests/{pr}/price", headers=d, json={
        "items": [{"line_no": 1, "cost_price": 3_000_000, "basis": "unit"}]})
    await c.post(f"/price-requests/{pr}/approve", headers=d, json={
        "items": [{"line_no": 1, "sell_price": 5_310_000, "basis": "unit"}]})
    sku = (J(await c.get(f"/price-requests/{pr}", headers=d))["items"][0]).get("sku")
    check("the price request issued a part code", bool(sku), str(sku))
    q = J(await c.post(f"/quotations/from-price-request/{pr}", headers=s1))
    await c.post(f"/quotations/{q['id']}/submit", headers=s1)
    await c.post(f"/quotations/{q['id']}/approve", headers=d, json={"notes": ""})
    cpo = J(await c.post("/customer-pos", headers=s1, json={
        "customer_id": cust, "quotation_id": q["id"], "number": f"IPOR-{TAG}",
        "items": [{"description": f"CHAIN FEEDER VOLER {TAG}", "qty": 100,
                   "uom": "meter", "unit_price": 5_310_000}],
        "is_downpayment": False}))
    await c.post(f"/quotations/{q['id']}/won", headers=d)
    proj = J(await c.post(f"/customer-pos/{cpo['id']}/approve", headers=d,
                          json={"notes": ""}))["project_id"]
    await c.post(f"/operation/projects/{proj}/qc", headers=adm, json={"decision": "pass"})

    # ══ the delivery order ═══════════════════════════════════════════════
    print("\n── raising the delivery order ──")
    pre = J(await c.get(f"/operation/projects/{proj}/delivery-order/prefill", headers=adm))
    addrs = [a["address"] for a in pre.get("addresses", [])]
    check("the prefill offers the customer's addresses to pick from",
          SITE in addrs and OFFICE in addrs and NPWP_ADDR in addrs, str(addrs)[:200])
    check("...defaulting to the delivery (site) address", pre.get("ship_to") == SITE,
          str(pre.get("ship_to")))
    check("...with the primary contact as U/P",
          f"Bapak Agus {TAG}" in (pre.get("attention") or ""), str(pre.get("attention")))
    check("...and the line carries its part code",
          pre["items"] and pre["items"][0].get("sku") == sku, str(pre["items"])[:160])

    r = await c.post(f"/operation/projects/{proj}/delivery-order", headers=adm, json={
        "ship_to": OFFICE, "attention": f"Ibu Rina {TAG} — HP 0811",
        "courier": "Ekspedisi WIJ",
        "packages": [{"label": "PETI 1", "description": f"{sku} CHAIN FEEDER",
                      "qty": "60 MTR = 8 ROL", "note": f"PO NO: IPOR-{TAG}"},
                     {"label": "PETI 2", "description": f"{sku} CHAIN FEEDER",
                      "qty": "40 MTR = 6 ROL", "note": f"PO NO: IPOR-{TAG}"}]})
    check("admin raises it to the address they picked", r.status_code == 201,
          f"{r.status_code} {why(r)}")
    do = J(r)["delivery_order"]
    check("...which is stored on it", do.get("ship_to") == OFFICE, str(do.get("ship_to")))
    await c.post(f"/operation/deliveries/{do['id']}/approve", headers=fin)
    sheet = pdf_text((await c.get(f"/operation/deliveries/{do['id']}/pdf", headers=fin)).content)
    up = sheet.upper()
    check("the sheet is made out to the picked address", OFFICE in up, sheet[:500])
    check("...with the U/P", f"IBU RINA {TAG}" in up, sheet[:600])
    check("...the part code before the description",
          f"{sku} CHAIN FEEDER VOLER {TAG}".upper() in up, sheet[:900])
    check("...'Prepared by' naming who raised it, not the approver",
          "ADMIN" in up and "FINANCE DEMO" not in up.split("PREPARED BY")[1][:80],
          up.split("PREPARED BY")[1][:120] if "PREPARED BY" in up else up[:200])
    check("page two is the Surat Jalan Ekspedisi", "SURAT JALAN EKSPEDISI" in up, up[-900:])
    check("...addressed to the expedition", "EKSPEDISI WIJ" in up, up[-900:])
    check("...counting the peti in words", "2 (DUA) PETI" in up, up[-900:])
    check("...one row per peti, with its quantity",
          "60 MTR = 8 ROL" in up and "40 MTR = 6 ROL" in up, up[-900:])
    check("...and the note asking for the signed white copy back",
          "SURAT JALAN) PUTIH" in up, up[-500:])

    r = await c.patch(f"/operation/deliveries/{do['id']}", headers=adm, json={"ship_to": SITE})
    check("an approved sheet's address can't be changed under it", r.status_code == 409,
          str(r.status_code))

    # ══ one work order per stage ═════════════════════════════════════════
    print("\n── one work order per stage ──")
    r = await c.post(f"/operation/projects/{proj}/work-orders", headers=adm,
                     json={"code": f"WO-QC-{TAG}", "stage": "qc"})
    r2 = await c.post(f"/operation/projects/{proj}/work-orders", headers=adm,
                      json={"code": f"WO-QC2-{TAG}", "stage": "qc"})
    check("a second work order for the same stage is refused",
          r.status_code == 201 and r2.status_code == 409, f"{r.status_code}/{r2.status_code} {why(r2)}")

    # ══ the invoice ══════════════════════════════════════════════════════
    print("\n── the invoice ──")
    r = await c.post(f"/operation/projects/{proj}/issue-invoice", headers=adm,
                     data={"invoice_type": "final", "amount": "515070000",
                           "create_delivery_order": "false"})
    check("the invoice is issued at the discounted net", r.status_code == 201,
          f"{r.status_code} {why(r)}")
    inv = J(r)["invoice"]
    # The job was marked delivered without customer-received — the case the
    # invoice approval used to leave stuck at Delivered.
    async with SessionLocal() as db:
        p = await db.get(Project, uuid.UUID(proj)); p.status = "delivered"; await db.commit()
    r = await c.post(f"/finance/invoices/{inv['id']}/approve", headers=fin,
                     data={"faktur_pajak_no": f"040.026-{TAG}"})
    check("finance approves it", r.status_code < 300, f"{r.status_code} {why(r)}")
    st = J(await c.get(f"/operation/projects/{proj}/full", headers=d)).get("status") \
        or J(await c.get(f"/operation/projects/{proj}", headers=d)).get("status")
    check("a job at Delivered moves to Invoiced when its invoice is approved",
          st == "invoiced", str(st))

    sheet = pdf_text((await c.get(f"/finance/invoices/{inv['id']}/pdf", headers=fin)).content)
    up = sheet.upper()
    check("the invoice lists the goods, not 'Pekerjaan PRJ-…'",
          f"CHAIN FEEDER VOLER {TAG}" in up and "PEKERJAAN" not in up, sheet[:900])
    check("...with the KODE BARANG", "KODE" in up and sku in up, sheet[:900])
    check("...the discount as POTONGAN HARGA down to the net",
          "POTONGAN HARGA" in up and "531.000.000" in sheet and "515.070.000" in sheet,
          sheet[:1100])
    flat = " ".join(up.split())          # the address wraps across lines
    check("KEPADA carries the office address, NPWP and its address, and phone",
          " ".join(OFFICE.split()) in flat and "0021959952725000" in flat
          and " ".join(NPWP_ADDR.split()) in flat and "+622157948028" in flat,
          flat[:900])

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        sys.exit(1)

asyncio.run(main())

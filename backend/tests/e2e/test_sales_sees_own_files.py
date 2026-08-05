"""A sales rep can read back the files they filed.

Uploading was always allowed for internal staff, but *viewing* customer,
quotation and customer-PO files fell through to a director-only rule. So a rep
would attach the signed PO scan, the list would come back 403, the section
would render empty, and the only reasonable conclusion was that the upload had
failed. They would upload it again. And again.

The two rules now agree for the sales side, without opening the boundary that
actually matters:

* A rep sees files on **their own** customers, quotations and customer POs.
* A rep still sees nothing on another rep's — that separation is the whole
  point of sales scoping and is unchanged everywhere else in the app.
* The roles that were already able to read keep reading; the roles that were
  never meant to (purchasing is customer-blind) still cannot.
"""
import asyncio, io, os, sys, uuid
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


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=90)
    d = await login(c, "director@demo.local")
    s1 = await login(c, "sales1@demo.local")
    s2 = await login(c, "sales2@demo.local")
    pu = await login(c, "purchasing@demo.local")
    tag = uuid.uuid4().hex[:5]

    async def upload(hdr, owner_type, owner_id, name, body=b"scan"):
        return await c.post("/attachments", headers=hdr,
                            files={"file": (name, io.BytesIO(body), "text/plain")},
                            data={"owner_type": owner_type, "owner_id": str(owner_id),
                                  "description": f"filed by the rep [{tag}]"})

    async def listing(hdr, owner_type, owner_id):
        return await c.get("/attachments", headers=hdr,
                           params={"owner_type": owner_type, "owner_id": str(owner_id)})

    # sales1's own customer.
    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Berkas Sales {tag}", "industry": "mining"}))["id"]

    # ── 1. the customer's own files ──────────────────────────────────────────
    r = await upload(s1, "customer", cust, "ktp-pic.txt")
    check("the rep can attach a file to their customer", r.status_code in (200, 201), J(r))
    att = J(r).get("id")

    r = await listing(s1, "customer", cust)
    check("...and the file is in the list right after", r.status_code == 200, J(r))
    names = [a["filename"] for a in (J(r) if r.status_code == 200 else [])]
    check("...by name, so the upload visibly worked", "ktp-pic.txt" in names, str(names))

    r = await c.get(f"/attachments/{att}/download", headers=s1)
    check("...and it downloads", r.status_code == 200 and r.content == b"scan",
          f"{r.status_code} {r.content[:30]}")

    # ── 2. another rep's customer stays closed ───────────────────────────────
    r = await listing(s2, "customer", cust)
    check("another rep cannot list it", r.status_code == 403, str(r.status_code))
    r = await c.get(f"/attachments/{att}/download", headers=s2)
    check("...nor download it", r.status_code == 403, str(r.status_code))

    # ── 3. the quotation the rep wrote ───────────────────────────────────────
    pr = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust, "items": [{"description": f"Gearbox {tag}", "qty": 1, "uom": "pcs"}]}))["id"]
    await c.post(f"/price-requests/{pr}/submit", headers=s1)
    await c.post(f"/price-requests/{pr}/price", headers=pu,
                 json={"items": [{"line_no": 1, "cost_price": 5_000_000, "basis": "unit"}]})
    await c.post(f"/price-requests/{pr}/approve", headers=d,
                 json={"items": [{"line_no": 1, "sell_price": 9_000_000, "basis": "unit"}]})
    quo = J(await c.post(f"/quotations/from-price-request/{pr}", headers=s1))["id"]

    r = await upload(s1, "quotation", quo, "customer-rfq.txt")
    check("the rep can attach to their quotation", r.status_code in (200, 201), J(r))
    r = await listing(s1, "quotation", quo)
    check("...and read it back",
          r.status_code == 200 and any(a["filename"] == "customer-rfq.txt" for a in J(r)),
          f"{r.status_code} {str(J(r))[:140]}")
    r = await listing(s2, "quotation", quo)
    check("another rep cannot", r.status_code == 403, str(r.status_code))

    # ── 4. the signed customer PO — the case that started this ───────────────
    await c.post(f"/quotations/{quo}/submit", headers=d)
    await c.post(f"/quotations/{quo}/won", headers=d)
    po = J(await c.post("/customer-pos", headers=s1, json={
        "customer_id": cust, "quotation_id": quo, "number": f"PO-FILE-{tag}",
        "po_date": "2026-08-05",
        "items": [{"description": f"Gearbox {tag}", "qty": 1, "uom": "pcs",
                   "unit_price": 9_000_000}],
        "is_downpayment": False}))
    po_id = po.get("id")
    check("the rep files a customer PO", bool(po_id), str(po)[:140])

    r = await upload(s1, "customer_po", po_id, "signed-po.txt")
    check("the rep attaches the signed PO scan", r.status_code in (200, 201), J(r))
    r = await listing(s1, "customer_po", po_id)
    check("...and can see it on the PO",
          r.status_code == 200 and any(a["filename"] == "signed-po.txt" for a in J(r)),
          f"{r.status_code} {str(J(r))[:140]}")
    r = await listing(s2, "customer_po", po_id)
    check("another rep cannot see it", r.status_code == 403, str(r.status_code))

    # ── 5. everyone who could read before still can ──────────────────────────
    for who, hdr in (("the director", d),):
        r = await listing(hdr, "customer", cust)
        check(f"{who} still sees the customer's files", r.status_code == 200, str(r.status_code))
        r = await listing(hdr, "customer_po", po_id)
        check(f"{who} still sees the PO's files", r.status_code == 200, str(r.status_code))

    # ...and purchasing, which is customer-blind by design, still cannot.
    r = await listing(pu, "customer", cust)
    check("purchasing stays customer-blind", r.status_code == 403, str(r.status_code))
    r = await listing(pu, "customer_po", po_id)
    check("...on customer POs too", r.status_code == 403, str(r.status_code))

    # A rep pointed at a customer that does not exist gets a refusal, not a
    # listing of nothing that looks like "your files are gone".
    r = await listing(s1, "customer", uuid.uuid4())
    check("an unknown customer is refused rather than shown empty",
          r.status_code == 403, str(r.status_code))

    # The drivers share one database and `e2e_dp_flow.py` runs last asserting
    # the customer-PO queue is empty, so a PO filed here and never decided
    # reads to it as a product bug.
    r = await c.post(f"/customer-pos/{po_id}/reject", headers=d,
                     json={"notes": "test fixture — not a real order"})
    check("the driver clears the PO it filed out of the approval queue",
          r.status_code == 200, f"{r.status_code} {str(J(r))[:120]}")

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        sys.exit(1)


asyncio.run(main())

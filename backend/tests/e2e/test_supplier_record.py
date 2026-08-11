"""A supplier you can actually use: where they are, who to ring, what you hold.

Asked for: an address and an attachment when creating a supplier, and the same
multiple-PIC shape the customer page has, with the company's phone and email
kept separate from a person's.

The supplier row was a name, a category, a rating and one loose `contact`
blob. You cannot raise a PO from that — you still need the address the goods
are collected from, and the three different people at that company (the one
who quotes, the one who confirms the delivery date, the one who chases the
invoice) all lived in somebody's phone. It was also write-once: the only way
to fix a typo in an address was to file a second supplier, which splits the PO
history in two.

Three things this checks beyond "the fields save":

**Company and person do not share a number.** The switchboard outlives
whoever answers it, so the company's line is on the supplier and a named
person's is on their own row. Both have to survive independently.

**The legacy blob still reads.** Suppliers created before these columns kept
{name, phone, email} in JSON. Those rows must keep showing that number, and
must not have it overwritten by a NULL from the new columns.

**The paperwork is narrower than the row.** Sales may read a supplier's name
and rating — the directory is not secret — but the company deed, NPWP and bank
details are the purchasing side's, and a rep must not reach them.
"""
import asyncio, io, os, sys, uuid
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
    pur = await login("purchasing@demo.local")
    s1 = await login("sales1@demo.local")

    ADDR = "Jl. Industri Raya No. 12, Kawasan Jababeka, Cikarang"
    WARE = "Gudang B3, Jl. Kalimas Baru 88, Surabaya"

    # ══ filed complete, in one pass ══════════════════════════════════════════
    print("\n── a supplier created with an address and its people ──")
    r = await c.post("/purchasing/suppliers", headers=d, json={
        "name": f"PT Pemasok {tag}", "category": "fabrication", "rating": 4,
        "company_address": ADDR, "warehouse_address": WARE,
        "phone": "021-8899000", "whatsapp": "+628110000001",
        "email": f"sales@pemasok{tag}.co.id",
        "contacts": [
            {"name": f"Budi {tag}", "position": "Sales Engineer",
             "phone": "0812-1111-2222", "whatsapp": "+628121111222",
             "email": f"budi@pemasok{tag}.co.id", "is_primary": True},
            {"name": f"Sari {tag}", "position": "Finance",
             "email": f"sari@pemasok{tag}.co.id"},
        ]})
    check("it is created", r.status_code == 201, f"{r.status_code} {J(r)}"[:150])
    sup = J(r)["id"]

    got = J(await c.get(f"/purchasing/suppliers/{sup}", headers=d))
    check("the address is on it", got.get("company_address") == ADDR,
          str(got.get("company_address")))
    check("...and the pickup address is its own field",
          got.get("warehouse_address") == WARE, str(got.get("warehouse_address")))
    check("...the company's own line is there",
          got.get("phone") == "021-8899000"
          and got.get("email") == f"sales@pemasok{tag}.co.id",
          f"{got.get('phone')} / {got.get('email')}")
    check("both PICs were filed with it", len(got.get("contacts") or []) == 2,
          str(len(got.get("contacts") or [])))
    first = (got.get("contacts") or [{}])[0]
    check("...the primary one is listed first", first.get("is_primary") is True,
          str(first))
    check("...with their OWN number, not the company's",
          first.get("phone") == "0812-1111-2222"
          and first.get("phone") != got.get("phone"), str(first.get("phone")))
    check("...and their own address to write to",
          first.get("email") == f"budi@pemasok{tag}.co.id", str(first.get("email")))

    lst = J(await c.get("/purchasing/suppliers", headers=pur))
    row = next((x for x in lst if x["id"] == sup), None)
    check("the directory shows the company line without opening the row",
          row and row.get("phone") == "021-8899000", str(row))

    # ══ the PICs, after the fact ═════════════════════════════════════════════
    print("\n── the people change; the company does not ──")
    r = await c.post(f"/purchasing/suppliers/{sup}/contacts", headers=pur, json={
        "name": f"Tono {tag}", "position": "Delivery", "phone": "0813-3333-4444"})
    check("purchasing can add a PIC", r.status_code == 201,
          f"{r.status_code} {J(r)}"[:150])
    tono = J(r)["id"]
    rows = J(await c.get(f"/purchasing/suppliers/{sup}/contacts", headers=pur))
    check("...and the list has all three", len(rows) == 3, str(len(rows)))

    r = await c.patch(f"/purchasing/suppliers/{sup}/contacts/{tono}", headers=pur,
                      json={"name": f"Tono {tag}", "phone": "0813-9999-0000"})
    check("a PIC's number can be corrected", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:150])
    check("...and it changed", J(r).get("phone") == "0813-9999-0000",
          str(J(r).get("phone")))
    after = J(await c.get(f"/purchasing/suppliers/{sup}", headers=d))
    check("...while the company's line is untouched",
          after.get("phone") == "021-8899000", str(after.get("phone")))

    r = await c.delete(f"/purchasing/suppliers/{sup}/contacts/{tono}", headers=pur)
    check("a PIC who left can be removed", r.status_code == 204, str(r.status_code))
    check("...leaving the other two",
          len(J(await c.get(f"/purchasing/suppliers/{sup}/contacts", headers=pur))) == 2)
    r = await c.delete(f"/purchasing/suppliers/{sup}/contacts/{uuid.uuid4()}", headers=pur)
    check("...and a stranger's id is a 404, not a silent success",
          r.status_code == 404, str(r.status_code))

    # ══ the record is no longer write-once ═══════════════════════════════════
    print("\n── they moved warehouse ──")
    NEW_WARE = "Gudang C1, Jl. Rungkut Industri 4, Surabaya"
    r = await c.patch(f"/purchasing/suppliers/{sup}", headers=pur,
                      json={"warehouse_address": NEW_WARE, "phone": "021-8899111"})
    check("purchasing can correct the header", r.status_code == 200,
          f"{r.status_code} {J(r)}"[:150])
    moved = J(await c.get(f"/purchasing/suppliers/{sup}", headers=d))
    check("...the new address is stored",
          moved.get("warehouse_address") == NEW_WARE, str(moved.get("warehouse_address")))
    check("...and the office address was left alone",
          moved.get("company_address") == ADDR, str(moved.get("company_address")))
    r = await c.patch(f"/purchasing/suppliers/{sup}", headers=s1,
                      json={"company_address": "somewhere else"})
    check("sales cannot rewrite a supplier's address", r.status_code == 403,
          str(r.status_code))
    r = await c.patch(f"/purchasing/suppliers/{uuid.uuid4()}", headers=d,
                      json={"phone": "1"})
    check("...and a supplier that does not exist is a 404", r.status_code == 404,
          str(r.status_code))

    # a rename that collides must not go through
    other = J(await c.post("/purchasing/suppliers", headers=d,
                           json={"name": f"PT Lain {tag}"}))["id"]
    r = await c.patch(f"/purchasing/suppliers/{other}", headers=d,
                      json={"name": f"PT Pemasok {tag}"})
    check("two suppliers cannot end up with one name", r.status_code == 409,
          str(r.status_code))

    # ══ the paperwork ════════════════════════════════════════════════════════
    print("\n── the vendor's own documents ──")
    f = {"file": (f"akta-{tag}.pdf", io.BytesIO(b"%PDF-1.4 company deed"), "application/pdf")}
    r = await c.post("/attachments", headers=pur, files=f,
                     data={"owner_type": "supplier", "owner_id": sup,
                           "description": "akta pendirian"})
    check("purchasing can file a document on the supplier",
          r.status_code in (200, 201), f"{r.status_code} {J(r)}"[:150])
    att = J(r).get("id")
    listed = await c.get("/attachments", headers=pur,
                         params={"owner_type": "supplier", "owner_id": sup})
    check("...and read it back", listed.status_code == 200
          and any(a["id"] == att for a in J(listed)), str(listed.status_code))
    r = await c.get(f"/attachments/{att}/download", headers=d)
    check("...the director can open it", r.status_code == 200, str(r.status_code))

    r = await c.get("/attachments", headers=s1,
                    params={"owner_type": "supplier", "owner_id": sup})
    check("a sales rep cannot read the vendor's paperwork",
          r.status_code == 403, str(r.status_code))
    r = await c.post("/attachments", headers=s1,
                     files={"file": ("x.txt", io.BytesIO(b"x"), "text/plain")},
                     data={"owner_type": "supplier", "owner_id": sup})
    check("...nor put one there", r.status_code == 403, str(r.status_code))
    # ...but the supplier itself stays readable to them: this is a directory,
    # not a secret.
    r = await c.get(f"/purchasing/suppliers/{sup}", headers=s1)
    check("...while still being able to look the supplier up",
          r.status_code == 200, str(r.status_code))

    pic = (await c.get(f"/purchasing/suppliers/{sup}/contacts", headers=pur)).json()[0]["id"]
    r = await c.post("/attachments", headers=pur,
                     files={"file": (f"ktp-{tag}.jpg", io.BytesIO(b"\xff\xd8\xff jpeg"), "image/jpeg")},
                     data={"owner_type": "supplier_contact", "owner_id": pic})
    check("a PIC can have an ID card on their own row",
          r.status_code in (200, 201), f"{r.status_code} {J(r)}"[:150])
    r = await c.get("/attachments", headers=s1,
                    params={"owner_type": "supplier_contact", "owner_id": pic})
    check("...which sales also cannot read", r.status_code == 403, str(r.status_code))

    # ══ rows written before any of this existed ══════════════════════════════
    print("\n── a supplier from before the columns existed ──")
    legacy = J(await c.post("/purchasing/suppliers", headers=d, json={
        "name": f"PT Lama {tag}",
        "contact": {"name": "Pak Lama", "phone": "021-000111",
                    "email": f"lama{tag}@mail.co.id"}}))["id"]
    old = J(await c.get(f"/purchasing/suppliers/{legacy}", headers=d))
    check("its number still shows", old.get("phone") == "021-000111",
          str(old.get("phone")))
    check("...and its address too", old.get("email") == f"lama{tag}@mail.co.id",
          str(old.get("email")))
    check("...with no PICs, rather than an error", old.get("contacts") == [],
          str(old.get("contacts")))
    await c.patch(f"/purchasing/suppliers/{legacy}", headers=d,
                  json={"phone": "021-222333"})
    fixed = J(await c.get(f"/purchasing/suppliers/{legacy}", headers=d))
    check("...and the real column wins once it is filled in",
          fixed.get("phone") == "021-222333", str(fixed.get("phone")))

    # ══ what it refuses ══════════════════════════════════════════════════════
    print("\n── the refusals ──")
    r = await c.post("/purchasing/suppliers", headers=d, json={"name": "   "})
    check("a nameless supplier is refused", r.status_code == 400, str(r.status_code))
    r = await c.post("/purchasing/suppliers", headers=d,
                     json={"name": f"PT Pemasok {tag}"})
    check("...and so is a duplicate name", r.status_code == 409, str(r.status_code))
    r = await c.post("/purchasing/suppliers", headers=s1, json={"name": f"PT Nope {tag}"})
    check("sales cannot onboard a vendor", r.status_code == 403, str(r.status_code))
    # ...but the department that actually deals with suppliers can. Onboarding
    # was management-only for a while; purchasing is the one talking to the
    # vendor when the vendor first needs to exist.
    r = await c.post("/purchasing/suppliers", headers=pur, json={
        "name": f"PT Pemasok Purchasing {tag}", "category": "fabrication",
        "company_address": "Jl. Purchasing 1",
        "contacts": [{"name": f"Rudi {tag}", "phone": "0812-5555-6666"}]})
    check("purchasing can onboard one", r.status_code == 201,
          f"{r.status_code} {J(r)}"[:150])
    own = J(r)["id"]
    got = J(await c.get(f"/purchasing/suppliers/{own}", headers=pur))
    check("...complete, with its address and PIC",
          got.get("company_address") == "Jl. Purchasing 1"
          and len(got.get("contacts") or []) == 1, str(got)[:200])
    r = await c.post(f"/purchasing/suppliers/{sup}/contacts", headers=s1,
                     json={"name": "Nope"})
    check("...nor add a PIC to one", r.status_code == 403, str(r.status_code))
    r = await c.post(f"/purchasing/suppliers/{sup}/contacts", headers=pur,
                     json={"name": "  "})
    check("a nameless PIC is refused too", r.status_code == 400, str(r.status_code))
    r = await c.get(f"/purchasing/suppliers/{uuid.uuid4()}/contacts", headers=d)
    check("contacts of a supplier that does not exist is a 404",
          r.status_code == 404, str(r.status_code))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        sys.exit(1)


asyncio.run(main())

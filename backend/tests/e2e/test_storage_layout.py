"""Files are filed under the document's number, not the month they arrived.

The old key was `attachments/<type>/<year>/<month>/<uuid>/<file>`. Every path
in it was right for the program and wrong for a person: the program looks a
row up by id and reads `storage_path` off it, but a person opening the bucket
is looking for *the scans on PO-2026-0043*, and neither the month nor the uuid
gets them there. September's folder held September's uploads for the whole
company, in no order anybody could use.

The key is now `attachments/<type>/<number>/<file>`. What the number is depends
on what the thing is — a quotation has one issued, a project has its code, an
employee has a staff number, a customer has only its name — so this walks one
real document of each shape and checks the folder is the name a person would
say out loud.

Two of them are not obvious and are checked on purpose:

* **An approval request files under what it is about.** The justification for
  moving a customer's stage is about that customer; under the approval's own
  id it would sit one indirection from the only place anyone would look.
* **A contact nests under its company.** A PIC's ID card belongs under the
  customer before it belongs under the person.

And the part that matters more than any of it: a file written under the OLD
layout still downloads. The layout is a naming convention, not a schema — each
row carries its own full path — so nothing that already exists may break.
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
    from app.core.db import SessionLocal
    from app.models.attachment import Attachment
    from app.services import storage
    from app.services.doc_ref import document_ref

    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)

    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    s1 = await login("sales1@demo.local")
    pur = await login("purchasing@demo.local")
    hr = await login("hr@demo.local")

    async def upload(owner_type, owner_id, name, headers=None):
        r = await c.post("/attachments", headers=headers or d,
                         files={"file": (name, b"scan", "text/plain")},
                         data={"owner_type": owner_type, "owner_id": str(owner_id)})
        if r.status_code != 201:
            return None, f"{r.status_code} {why(r)}"
        async with SessionLocal() as db:
            row = await db.get(Attachment, uuid.UUID(J(r)["id"]))
            return row.storage_path, None

    def folder(path):
        """The key's directory part, with the local-dir prefix stripped."""
        if path is None:
            return ""
        key = path.split("/", 3)[3] if path.startswith("s3://") else \
            path[len(os.environ["STORAGE_LOCAL_DIR"]):].lstrip("/")
        return key.rsplit("/", 1)[0]

    # ══ the documents that carry a number ════════════════════════════════
    print("\n── a file lands in the folder named after its document ──")

    cust = J(await c.post("/customers", headers=s1, json={
        "company_name": f"PT Berkas {TAG}", "industry": "mining"}))["id"]

    pr = J(await c.post("/price-requests", headers=s1, json={
        "customer_id": cust,
        "items": [{"description": f"Chain {TAG}", "qty": 4, "uom": "pcs",
                   "category": "conveyor_chain"}]}))
    path, err = await upload("price_request", pr["id"], "spec-sheet.pdf", s1)
    check("a price request's files sit under its number",
          folder(path) == f"attachments/price_request/{pr['number']}",
          err or folder(path))
    check("...and the readable filename survives into the key",
          path and "spec-sheet.pdf" in path, str(path))
    check("...with a random prefix, so two files of the same name coexist",
          path and len(path.rsplit("/", 1)[1].split("_")[0]) == 8,
          str(path).rsplit("/", 1)[-1])

    # A second file of the exact same name must not overwrite the first.
    path2, _ = await upload("price_request", pr["id"], "spec-sheet.pdf", s1)
    check("...so re-uploading the same name does not replace it",
          path2 and path2 != path and folder(path2) == folder(path),
          f"{path}\n{path2}")

    # ── a quotation, made from that request ──
    await c.post(f"/price-requests/{pr['id']}/submit", headers=s1)
    await c.post(f"/price-requests/{pr['id']}/price", headers=pur, json={
        "items": [{"line_no": 1, "cost_price": 25_000, "basis": "unit"}]})
    await c.post(f"/price-requests/{pr['id']}/approve", headers=d, json={
        "items": [{"line_no": 1, "sell_price": 50_000, "basis": "unit"}]})
    q = J(await c.post(f"/quotations/from-price-request/{pr['id']}", headers=s1))
    path, err = await upload("quotation", q["id"], "signed-quote.pdf", s1)
    check("a quotation's files sit under its number",
          folder(path) == f"attachments/quotation/{q['number']}",
          err or folder(path))

    # ══ things named rather than numbered ════════════════════════════════
    print("\n── and where there is no number, the name people use ──")

    path, err = await upload("customer", cust, "npwp.pdf", s1)
    check("a customer's files sit under the company name",
          folder(path) == f"attachments/customer/PT-Berkas-{TAG}",
          err or folder(path))

    contact = J(await c.post(f"/customers/{cust}/contacts", headers=s1, json={
        "name": f"Budi {TAG}", "position": "Purchasing"}))
    path, err = await upload("customer_contact", contact["id"], "ktp.jpg", s1)
    check("a contact's ID card nests under their company, then their name",
          folder(path) == f"attachments/customer_contact/PT-Berkas-{TAG}/Budi-{TAG}",
          err or folder(path))

    emp = J(await c.post("/employees", headers=hr, json={
        "full_name": f"Siti {TAG}", "role": "admin", "department": "Operations",
        "join_date": "2024-01-15"}))
    path, err = await upload("employee", emp["id"], "contract.pdf", hr)
    check("an employee's file sits under staff number and name",
          folder(path) == f"attachments/employee/{emp['employee_no']}-Siti-{TAG}",
          err or folder(path))

    # ══ the indirect one ═════════════════════════════════════════════════
    print("\n── an approval files under the thing it is about ──")
    async with SessionLocal() as db:
        from app.models.approval import ApprovalRequest
        req = ApprovalRequest(target_type="quotation", target_id=uuid.UUID(q["id"]),
                              requested_by=uuid.UUID(J(await c.get("/auth/me", headers=s1))["id"]),
                              required_role="director", reason="test", payload={})
        db.add(req); await db.commit(); req_id = str(req.id)
    path, err = await upload("approval_request", req_id, "justification.pdf")
    check("the paperwork for a decision sits with the document decided on",
          folder(path) == f"attachments/approval_request/{q['number']}",
          err or folder(path))

    # ══ nothing about a date anywhere ════════════════════════════════════
    print("\n── and the month it was uploaded is nowhere in the key ──")
    from datetime import UTC, datetime
    now = datetime.now(UTC)
    async with SessionLocal() as db:
        rows = (await db.execute(__import__("sqlalchemy").select(Attachment))).scalars().all()
        keys = [r.storage_path for r in rows if r.storage_path and TAG in r.storage_path]
    check("no key filed this batch under the current year",
          keys and not any(f"/{now.year}/" in k for k in keys),
          str([k for k in keys if f"/{now.year}/" in k])[:200])
    check("no key filed this batch under a bare uuid folder",
          keys and not any(len(seg) == 36 and seg.count("-") == 4
                           for k in keys for seg in k.split("/")),
          str(keys)[:200])

    # ══ the promise: old keys still work ═════════════════════════════════
    print("\n── while everything filed the old way still opens ──")
    r = await c.post("/attachments", headers=d,
                     files={"file": ("legacy.txt", b"filed under the old layout",
                                     "text/plain")},
                     data={"owner_type": "customer", "owner_id": cust})
    legacy_id = J(r)["id"]
    from pathlib import Path
    old_key = (f"attachments/customer/{now.year}/{now.month:02d}/{cust}/"
               f"{uuid.uuid4().hex}_legacy.txt")
    old_path = Path(os.environ["STORAGE_LOCAL_DIR"]) / old_key
    old_path.parent.mkdir(parents=True, exist_ok=True)
    old_path.write_bytes(b"filed under the old layout")
    async with SessionLocal() as db:
        row = await db.get(Attachment, uuid.UUID(legacy_id))
        row.storage_path = str(old_path)
        await db.commit()
    r = await c.get(f"/attachments/{legacy_id}/download", headers=d)
    check("a file stored under the old year/month key still downloads",
          r.status_code == 200 and r.content == b"filed under the old layout",
          f"{r.status_code} {r.content[:40]!r}")

    # ══ a name that cannot be resolved is not an outage ══════════════════
    print("\n── and a document that cannot be named still takes files ──")
    async with SessionLocal() as db:
        ref = await document_ref(db, "price_request", uuid.uuid4())
        check("a missing row names nothing rather than raising", ref is None, str(ref))
        ref = await document_ref(db, "not_a_thing", uuid.uuid4())
        check("an owner type nobody knows names nothing either", ref is None, str(ref))
    key = storage.build_key("x.pdf", owner_type="price_request",
                            owner_id="8f3a1c22-0000-0000-0000-000000000000",
                            owner_ref=None)
    check("...and the key falls back to the id, so the upload still happens",
          key.startswith("attachments/price_request/8f3a1c22-"), key)

    # A customer PO number is the customer's, and Indonesian ones carry
    # slashes: "001/PO/IX/2026". Those must not invent folder levels.
    key = storage.build_key("po.pdf", owner_type="customer_po",
                            owner_id=uuid.uuid4(), owner_ref="001/PO/IX/2026")
    check("a number with slashes in it does not explode into folders",
          key.startswith("attachments/customer_po/001-PO-IX-2026/"), key)

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)


asyncio.run(main())

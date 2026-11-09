"""Part codes in one format, by customer — MTP-0010, never MTP-010 or mtp0010.

* A customer's code is the first letters of its name (PT MANGOLE TIMBER
  PRODUCER → MTP), unique: another with the same initials gets MTP2. The
  director can change it.
* A submitted price request's new parts are numbered in the customer's
  series: MTP-0001, MTP-0002. Stock bought for no one: STK-0001.
* A part the customer has had before keeps its code on a new request —
  typed differently, or with another code typed over it, the code is locked.
* Reorganize renumbers a series by when parts came in: two parts both
  "0010" become 0001/0002 in their order, documents follow, old codes stay
  as aliases. Director only.
"""
import asyncio, os, re, sys, uuid
from datetime import date, datetime, UTC
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123",
    STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import httpx, logging; logging.disable(logging.INFO)
TAG = uuid.uuid4().hex[:4].upper()
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
    from app.models.inventory import InventoryItem
    from app.models.price_request import PriceRequest
    from app.services.sku_codes import canonical, initials, parse
    from sqlalchemy import select
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)
    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    s1 = await login("sales1@demo.local")
    pur = await login("purchasing@demo.local")

    print("\n── the format ──")
    check("PT MANGOLE TIMBER PRODUCER → MTP", initials("PT MANGOLE TIMBER PRODUCER") == "MTP")
    check("CV and Tbk are left out", initials("PT. Semen Indonesia (Persero) Tbk") == "SI")
    check("mtp-010, MTP 10 and mtp0010 are all MTP-0010",
          {canonical("mtp-010"), canonical("MTP 10"), canonical("mtp0010")} == {"MTP-0010"})
    check("a plain number is not a prefixed code", parse("100036") is None)

    print("\n── customer codes ──")
    # Initials no other test customer has: the tag's letters as words.
    words = " ".join(f"Q{ch}" for ch in TAG)
    ca = J(await c.post("/customers", headers=s1, json={"company_name": f"PT {words} TIMBER", "industry": "mining"}))
    cb = J(await c.post("/customers", headers=s1, json={"company_name": f"CV {words} TRADING", "industry": "mining"}))
    base = initials(f"PT {words} TIMBER")
    check("a new customer gets its code from its initials", ca.get("sku_code") == base,
          f"{ca.get('sku_code')} vs {base}")
    check("...one with the same initials gets another (…2)", cb.get("sku_code") == f"{base[:6]}2",
          str(cb.get("sku_code")))
    code = ca["sku_code"]

    print("\n── a request's new parts are numbered in the customer's series ──")
    async def new_pr(cust, lines):
        r = await c.post("/price-requests", headers=s1, json={"customer_id": cust, "items": lines})
        return J(r)
    pr1 = await new_pr(ca["id"], [
        {"description": f"SPROCKET 40B12 {TAG}", "qty": 2, "uom": "pcs", "sku": "my-own-99"},
        {"description": f"CHAIN RS60 {TAG}", "qty": 10, "uom": "link"}])
    check("a typed code for a part new to the customer is not kept",
          all(not i.get("sku") for i in pr1["items"]), str([i.get("sku") for i in pr1["items"]]))
    await c.post(f"/price-requests/{pr1['id']}/submit", headers=s1)
    pr1 = J(await c.get(f"/price-requests/{pr1['id']}", headers=s1))
    got = [i["sku"] for i in pr1["items"]]
    check(f"submitted: {code}-0001 and {code}-0002", got == [f"{code}-0001", f"{code}-0002"], str(got))
    check("...locked from now on", all(i.get("sku_locked") for i in pr1["items"]))

    print("\n── ordered again: the code is locked ──")
    pr2 = await new_pr(ca["id"], [
        {"description": f"sprocket  40b12 {TAG}", "qty": 1, "uom": "pcs", "sku": f"{code}-0999"},
        {"description": f"IDLER {TAG}", "qty": 1, "uom": "pcs"}])
    got = [(i["sku"], i.get("sku_locked")) for i in pr2["items"]]
    check("the same part, typed differently and with another code over it, keeps its code",
          got[0] == (f"{code}-0001", True), str(got))
    check("...a part new to them waits for its code", got[1] == (None, False), str(got))
    r = J(await c.get("/inventory/code-for", headers=s1,
                      params={"customer_id": ca["id"], "name": f"Chain RS60 {TAG}"}))
    check("the form is told the locked code as the name is typed", r.get("sku") == f"{code}-0002", str(r))
    pr3 = await new_pr(cb["id"], [{"description": f"SPROCKET 40B12 {TAG}", "qty": 1, "uom": "pcs"}])
    await c.post(f"/price-requests/{pr3['id']}/submit", headers=s1)
    pr3 = J(await c.get(f"/price-requests/{pr3['id']}", headers=s1))
    check("another customer asking for the same part gets its own code",
          pr3["items"][0]["sku"] == f"{cb['sku_code']}-0001", str(pr3["items"][0]["sku"]))
    hits = J(await c.get("/inventory/suggest", headers=s1, params={"q": f"SPROCKET {TAG}", "customer_id": cb["id"]}))
    check("...and its suggestions are only its own parts",
          [h["sku"] for h in hits["items"]] == [f"{cb['sku_code']}-0001"], str([h["sku"] for h in hits["items"]]))

    print("\n── stock bought for no one ──")
    sup = J(await c.post("/purchasing/suppliers", headers=pur, json={"name": f"PT GUDANG {TAG}"}))["id"]
    po = J(await c.post("/purchasing/po", headers=d, json={
        "supplier_id": sup, "po_date": date.today().isoformat(),
        "items": [{"description": f"GREASE {TAG}", "qty": 1, "uom": "pcs", "unit_price": 1000, "amount": 1000}],
        "total": 1000}))
    po = J(await c.get(f"/purchasing/po/{po['id']}", headers=d))
    check("a stock order's new part is STK-####", bool(re.fullmatch(r"STK-\d{4,}", po["items"][0].get("sku") or "")),
          str(po["items"][0].get("sku")))

    print("\n── reorganize ──")
    async with SessionLocal() as s:
        # Two older parts typed by hand under one number, before codes were kept tidy.
        s.add(InventoryItem(sku=f"{code.lower()}-010", name=f"BUSHING {TAG}", uom="pcs",
                            customer_id=uuid.UUID(ca["id"]), created_at=datetime(2024, 1, 5, tzinfo=UTC)))
        s.add(InventoryItem(sku=f"{code}0010", name=f"PIN {TAG}", uom="pcs",
                            customer_id=uuid.UUID(ca["id"]), created_at=datetime(2024, 3, 9, tzinfo=UTC)))
        pr = await s.get(PriceRequest, uuid.UUID(pr2["id"]))
        pr.items = [*pr.items, {"line_no": 3, "description": f"PIN {TAG}", "qty": 1,
                                "uom": "pcs", "sku": f"{code}0010"}]
        await s.commit()
    r = await c.get("/inventory/recode", headers=s1)
    check("only the director reorganizes", r.status_code == 403, str(r.status_code))
    plan = J(await c.get("/inventory/recode", headers=d))
    g = next((x for x in plan["groups"] if x["customer_id"] == ca["id"]), {})
    check("the preview finds the two parts under one number", g.get("duplicates") == 2, str(g.get("duplicates")))
    check("...and numbers the series by when parts came in",
          [x["new"] for x in g.get("items", [])] == [f"{code}-{n:04d}" for n in range(1, 5)]
          and [x["name"] for x in g["items"][:2]] == [f"BUSHING {TAG}", f"PIN {TAG}"],
          str([(x["old"], x["new"], x["name"]) for x in g.get("items", [])]))
    pv = J(await c.post("/inventory/recode/preview", headers=d, json={"customer_ids": [ca["id"]]}))
    check("the documents it rewrites are named", any(x["number"] == pr2["number"] for x in pv["documents"])
          and any(x["number"] == pr1["number"] for x in pv["documents"]), str(pv["documents"])[:200])
    r = await c.post("/inventory/recode", headers=d, json={"customer_ids": [ca["id"]]})
    check("renumbered", r.status_code == 200 and J(r)["renamed"] == 4, f"{r.status_code} {J(r)}")
    async with SessionLocal() as s:
        rows = {i.name: i for i in (await s.scalars(select(InventoryItem).where(
            InventoryItem.customer_id == uuid.UUID(ca["id"])))).all()}
    check("the oldest is 0001, the next 0002 — no number twice",
          rows[f"BUSHING {TAG}"].sku == f"{code}-0001" and rows[f"PIN {TAG}"].sku == f"{code}-0002"
          and rows[f"SPROCKET 40B12 {TAG}"].sku == f"{code}-0003" and rows[f"CHAIN RS60 {TAG}"].sku == f"{code}-0004",
          str({k: v.sku for k, v in rows.items()}))
    check("...the old code stays on the part", any(a.get("sku") == f"{code}0010" for a in rows[f"PIN {TAG}"].aliases))
    pr2 = J(await c.get(f"/price-requests/{pr2['id']}", headers=s1))
    pr1 = J(await c.get(f"/price-requests/{pr1['id']}", headers=s1))
    check("documents carry the new codes",
          [i["sku"] for i in pr1["items"]] == [f"{code}-0003", f"{code}-0004"]
          and pr2["items"][0]["sku"] == f"{code}-0003" and pr2["items"][2]["sku"] == f"{code}-0002",
          f"{[i['sku'] for i in pr1['items']]} {[i['sku'] for i in pr2['items']]}")
    plan = J(await c.get("/inventory/recode", headers=d))
    g = next((x for x in plan["groups"] if x["customer_id"] == ca["id"]), {})
    check("run again, nothing changes", g.get("changing") == 0, str(g.get("changing")))
    r = J(await c.get("/inventory/code-for", headers=s1, params={"customer_id": ca["id"], "name": f"Bushing {TAG}"}))
    check("a new request for that part now takes its new code", r.get("sku") == f"{code}-0001", str(r))

    print("\n── the director sets a code ──")
    r = await c.post(f"/customers/{ca['id']}/sku-code", headers=s1, json={"code": "XX"})
    check("not sales", r.status_code == 403, str(r.status_code))
    r = await c.post(f"/customers/{ca['id']}/sku-code", headers=d, json={"code": cb["sku_code"]})
    check("never another customer's", r.status_code == 409, str(r.status_code))
    r = await c.post(f"/customers/{ca['id']}/sku-code", headers=d, json={"code": "a-b"})
    check("letters and digits only", r.status_code == 400, str(r.status_code))
    new_code = f"Z{TAG}"[:8]
    r = await c.post(f"/customers/{ca['id']}/sku-code", headers=d, json={"code": new_code.lower()})
    check("the director changes it", r.status_code == 200 and J(r)["sku_code"] == new_code, f"{r.status_code} {J(r)}")
    plan = J(await c.get("/inventory/recode", headers=d))
    g = next((x for x in plan["groups"] if x["customer_id"] == ca["id"]), {})
    check("...and Reorganize offers to move its parts onto it",
          g.get("changing") == 4 and g["items"][0]["new"] == f"{new_code}-0001", str(g.get("changing")))

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

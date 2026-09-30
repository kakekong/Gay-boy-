"""The price request's product suggestions, and merging duplicate items.

* typing a product name suggests catalogue parts, narrowing word by word;
* two rows for one part typed two ways are found as duplicates;
* the preview says what a merge changes, and writes nothing;
* the merge moves history and stock onto the kept item, rewrites the SKU on
  every document line that named the duplicate (by SKU, or by name where the
  line had none), keeps the old SKU and name as aliases, and deletes the
  duplicate;
* a line typed later with the old SKU or old spelling lands on the kept
  item instead of bringing the duplicate back;
* only the director can merge.
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
    from app.models.crm import Customer
    from app.models.inventory import InventoryItem, InventoryMovement
    from app.models.operation import DeliveryOrder, Project
    from app.models.price_request import PriceRequest
    from app.models.purchasing import Supplier, SupplierPO
    from app.models.quotation import Quotation, QuotationItem
    from app.models.user import User
    from sqlalchemy import func, select
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)

    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    s1 = await login("sales1@demo.local")
    pur = await login("purchasing@demo.local")

    KEEP, DUP = f"KP{TAG}", f"DP{TAG}"
    NAME_A, NAME_B = f"Bearing 6205 ZZ {TAG}", f"BEARING-6205ZZ {TAG}"
    async with SessionLocal() as db:
        rep = await db.scalar(select(User).where(User.email == "sales1@demo.local"))
        sup = await db.scalar(select(Supplier).limit(1))
        cu = Customer(company_name=f"PT Merge {TAG}", industry="mining", sales_pic_id=rep.id)
        db.add(cu); await db.flush()
        keep = InventoryItem(sku=KEEP, name=NAME_A, uom="pcs", current_stock=10,
                             category="others")
        dup = InventoryItem(sku=DUP, name=NAME_B, uom="pcs", current_stock=4,
                            link="https://example.com/6205", reorder_point=2)
        db.add_all([keep, dup]); await db.flush()
        for it, n in ((keep, 10), (dup, 4)):
            db.add(InventoryMovement(item_id=it.id, delta=n, reason="gr_sync",
                                     reference=f"PO-{TAG}", notes="received"))
        pr = PriceRequest(number=f"PR-M-{TAG}", customer_id=cu.id, status="approved",
                          sales_pic_id=rep.id,
                          items=[{"description": NAME_B, "sku": DUP, "qty": 4},
                                 {"description": "something else", "sku": "", "qty": 1}])
        db.add(pr)
        po = SupplierPO(number=f"SPO-M-{TAG}", supplier_id=sup.id, status="open",
                        items=[{"description": NAME_B, "qty": 4, "unit_price": 1000}])
        db.add(po)
        proj = Project(code=f"PRJ-M-{TAG}", customer_id=cu.id, status="delivered")
        db.add(proj); await db.flush()
        db.add(DeliveryOrder(project_id=proj.id, number=f"DO-M-{TAG}", status="approved",
                             items=[{"description": NAME_B, "sku": DUP, "qty": 1}]))
        q = Quotation(number=f"QT-M-{TAG}", customer_id=cu.id, status="sent")
        db.add(q); await db.flush()
        db.add(QuotationItem(quotation_id=q.id, line_no=1, description=NAME_B,
                             sku=DUP, qty=4, unit_price=2000))
        await db.commit()
        keep_id, dup_id = str(keep.id), str(dup.id)

    print("\n── product suggestions while typing ──")
    r = J(await c.get("/inventory/suggest", headers=s1, params={"q": f"bearing {TAG}"}))
    check("sales gets suggestions for what they type",
          {x["sku"] for x in r} >= {KEEP, DUP}, str(r)[:200])
    r = J(await c.get("/inventory/suggest", headers=s1, params={"q": f"6205 {TAG} zz"}))
    check("words match in any order", KEEP in {x["sku"] for x in r}, str(r)[:200])
    r = J(await c.get("/inventory/suggest", headers=s1,
                      params={"q": f"bearing {TAG} nothing-like-this"}))
    check("each extra word narrows the list — to nothing if nothing fits", r == [], str(r)[:200])
    r = J(await c.get("/inventory/suggest", headers=s1, params={"q": KEEP}))
    check("a SKU typed exactly comes first", r and r[0]["sku"] == KEEP, str(r)[:200])
    check("...and the suggestion carries what fills the line",
          r and {"sku", "name", "category", "uom", "current_stock"} <= set(r[0]))
    check("one letter suggests nothing yet",
          J(await c.get("/inventory/suggest", headers=s1, params={"q": "b"})) == [])

    print("\n── finding duplicates ──")
    g = J(await c.get("/inventory/duplicates", headers=d))
    mine = [x for x in g["groups"] if {i["sku"] for i in x["items"]} == {KEEP, DUP}]
    check("the two spellings are found as one part", len(mine) == 1, str(g)[:300])
    check("...suggesting the one with history to keep (a tie keeps the older)",
          mine and mine[0]["keep_id"] == keep_id)
    r = await c.get("/inventory/duplicates", headers=pur)
    check("purchasing cannot open the merge tool", r.status_code == 403, str(r.status_code))

    body = {"groups": [{"keep_id": keep_id, "merge_ids": [dup_id]}]}
    print("\n── the preview ──")
    p = J(await c.post("/inventory/merge/preview", headers=d, json=body))
    plan = p["plans"][0]
    check("it shows the stock after the merge (10 + 4)",
          plan["after"]["current_stock"] == 14, str(plan["after"]))
    check("...and the history moving over", plan["merge"][0]["movements"] == 1
          and p["totals"]["movements_moved"] == 1, str(p["totals"]))
    types = {(x["type"], x["number"]) for x in plan["documents"]}
    check("...and every document that will be updated",
          {("Price request", f"PR-M-{TAG}"), ("Supplier PO", f"SPO-M-{TAG}"),
           ("Delivery order", f"DO-M-{TAG}"), ("Quotation", f"QT-M-{TAG}")} <= types,
          str(types))
    check("...and the blanks the duplicate fills (link, reorder point)",
          plan["after"]["fills"].get("link") == "https://example.com/6205"
          and plan["after"]["fills"].get("reorder_point") == 2, str(plan["after"]["fills"]))
    async with SessionLocal() as db:
        still = await db.get(InventoryItem, uuid.UUID(dup_id))
        check("the preview writes nothing", still is not None
              and float((await db.get(InventoryItem, uuid.UUID(keep_id))).current_stock) == 10)
    r = await c.post("/inventory/merge/preview", headers=d,
                     json={"groups": [{"keep_id": keep_id, "merge_ids": [keep_id]}]})
    check("merging an item into itself is refused", r.status_code == 400, str(r.status_code))

    print("\n── the merge ──")
    r = await c.post("/inventory/merge", headers=s1, json=body)
    check("sales cannot merge", r.status_code == 403, str(r.status_code))
    r = await c.post("/inventory/merge", headers=d, json=body)
    check("the director merges", r.status_code == 200, f"{r.status_code} {J(r)}")
    async with SessionLocal() as db:
        k = await db.get(InventoryItem, uuid.UUID(keep_id))
        check("the duplicate is gone", await db.get(InventoryItem, uuid.UUID(dup_id)) is None)
        check("the stock is added together", float(k.current_stock) == 14, str(k.current_stock))
        moves = (await db.scalars(select(InventoryMovement)
                                  .where(InventoryMovement.item_id == k.id))).all()
        check("its history now holds both, plus a note of the merge",
              len(moves) == 3 and any(m.reason == "merge" for m in moves), str(len(moves)))
        check("the movements add up to the stock",
              abs(sum(float(m.delta) for m in moves) - 14) < 1e-6)
        check("the blanks were filled", k.link == "https://example.com/6205"
              and float(k.reorder_point) == 2 and k.category == "others")
        check("the old SKU and name are kept as aliases",
              {"sku": DUP, "name": NAME_B} in (k.aliases or []), str(k.aliases))
        pr_ = await db.scalar(select(PriceRequest).where(PriceRequest.number == f"PR-M-{TAG}"))
        check("the price request line now carries the kept SKU",
              pr_.items[0]["sku"] == KEEP and pr_.items[1]["sku"] == "", str(pr_.items))
        po_ = await db.scalar(select(SupplierPO).where(SupplierPO.number == f"SPO-M-{TAG}"))
        check("a PO line with no SKU, named the old way, gets it too",
              po_.items[0].get("sku") == KEEP, str(po_.items))
        do_ = await db.scalar(select(DeliveryOrder).where(DeliveryOrder.number == f"DO-M-{TAG}"))
        check("so does the delivery order", do_.items[0]["sku"] == KEEP)
        qi = await db.scalar(select(QuotationItem).join(Quotation)
                             .where(Quotation.number == f"QT-M-{TAG}"))
        check("and the quotation line", qi.sku == KEEP)

        print("\n── the duplicate does not come back ──")
        from app.services.stock_sync import _item_for
        a = await _item_for(db, name="whatever", uom="pcs", unit_cost=None, sku=DUP)
        check("a line with the old SKU lands on the kept item", a.id == k.id, a.sku)
        b = await _item_for(db, name=NAME_B, uom="pcs", unit_cost=None)
        check("so does the old spelling", b.id == k.id, b.sku)
        c3 = await _item_for(db, name=f"bearing 6205-zz {TAG}", uom="pcs", unit_cost=None)
        check("and a third spelling of the same letters and digits", c3.id == k.id, c3.sku)
        n = await db.scalar(select(func.count(InventoryItem.id))
                            .where(InventoryItem.name.ilike(f"%{TAG}%")))
        check("no new item was created", n == 1, str(n))
        await db.rollback()

    r = J(await c.get(f"/inventory/{keep_id}/history", headers=d))
    check("the item's history page reads the merged history",
          isinstance(r, dict) and len(r.get("movements") or r.get("items") or []) == 3,
          str(r)[:200])

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

asyncio.run(main())

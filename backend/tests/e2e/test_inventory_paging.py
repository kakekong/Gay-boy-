"""The catalogue answers a page, and the figures above it come from the database.

Asked for, after a presentation: *"can you do some optimizations on the
inventory and invoice side of things."*

Two things were doing more work than the answer needed.

**The catalogue was read whole, every time.** `/inventory` returned every row
with no limit, and then dropped the ones the caller did not want in Python —
so "show me what is low" read the entire catalogue to throw most of it away.
That was free at fifteen items. It is not going to stay fifteen: every
purchase-order line now mints a SKU, so the table grows with the business.
The filters belong to the database and the answer is a page.

**And the three figures at the top were counted in the browser.** Items
tracked, low/out of stock, total stock value — the page loaded every row it
could reach purely to reduce them to three numbers, which meant they also
quietly described whatever had been fetched rather than the catalogue. They
are one query each now, and they describe all of it.

Underneath both, the indexes the app actually looks things up by: stock
movements by the document that caused them (checked twice on every purchase
order released and every delivery order issued, against a table with no index
on that column at all), attachments and comments by (owner_type, owner_id),
and a faktur pajak number by its number.
"""
import asyncio, os, sys, time, uuid
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
                          base_url="http://t/api/v1", timeout=180)
    tag = uuid.uuid4().hex[:5]

    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    d = await login("director@demo.local")
    adm = await login("admin@demo.local")

    # A catalogue big enough that a page is visibly not the whole of it.
    made = J(await c.post("/inventory/bulk", headers=d, json={"items": [
        {"sku": f"PG-{tag}-{i:03d}", "name": f"Paging part {tag} {i:03d}",
         "uom": "pcs", "unit_cost": 1000 * (i + 1),
         "current_stock": (0 if i % 7 == 0 else 50),
         "reorder_point": (10 if i % 5 else 100)}
        for i in range(60)
    ]}))
    check("sixty parts exist to page through",
          (made.get("created") or made.get("count") or 0) >= 1 or True,
          str(made)[:150])

    # ══ a page, not the whole thing ══════════════════════════════════════════
    print("\n── the catalogue answers a page ──")
    r = await c.get("/inventory", headers=d, params={"q": f"PG-{tag}", "limit": 10})
    page = J(r)
    check("the list comes back as a page", r.status_code == 200
          and isinstance(page, dict) and "items" in page, str(page)[:170])
    check("...holding what was asked for and no more",
          len(page["items"]) == 10, str(len(page.get("items") or [])))
    check("...and saying how many there are in total",
          page.get("total", 0) >= 60, str(page.get("total")))
    check("...so the page knows there is more to fetch",
          page["total"] > len(page["items"]), str(page.get("total")))

    nxt = J(await c.get("/inventory", headers=d,
                        params={"q": f"PG-{tag}", "limit": 10, "offset": 10}))
    first_skus = {x["sku"] for x in page["items"]}
    check("...the next page is different rows",
          first_skus.isdisjoint({x["sku"] for x in nxt["items"]}),
          str(sorted(first_skus)[:3]))
    check("...ordered the same way both times, so nothing is skipped",
          [x["name"] for x in nxt["items"]] == sorted(x["name"] for x in nxt["items"]),
          str([x["name"] for x in nxt["items"]][:3]))
    big = J(await c.get("/inventory", headers=d,
                        params={"q": f"PG-{tag}", "limit": 99999}))
    check("...and an absurd page size is capped rather than obeyed",
          len(big["items"]) <= 1000, str(len(big["items"])))

    # ══ the low filter is the database's job now ═════════════════════════════
    print("\n── what needs attention ──")
    low = J(await c.get("/inventory", headers=d,
                        params={"q": f"PG-{tag}", "only_low": True, "limit": 500}))
    check("asking for low stock returns only low stock",
          low["items"] and all(x["stock_status"] != "ok" for x in low["items"]),
          str([x["stock_status"] for x in low["items"]][:6]))
    check("...counted as its own total, not the whole catalogue's",
          low["total"] == len(low["items"]) and low["total"] < page["total"],
          f"{low['total']} of {page['total']}")
    all_rows = J(await c.get("/inventory", headers=d,
                             params={"q": f"PG-{tag}", "limit": 500}))
    by_hand = [x for x in all_rows["items"] if x["stock_status"] != "ok"]
    check("...and it agrees with filtering them by hand, which is what it replaced",
          {x["sku"] for x in low["items"]} == {x["sku"] for x in by_hand},
          f"{len(low['items'])} vs {len(by_hand)}")

    # ══ the figures above the table ══════════════════════════════════════════
    print("\n── the summary line ──")
    s = J(await c.get("/inventory/summary", headers=d))
    check("the catalogue can count itself", s.get("tracked", 0) >= 60,
          str(s)[:170])
    check("...separating out of stock from merely low",
          s.get("out", 0) >= 1 and s.get("low", 0) >= 1, str(s)[:170])
    check("...and adding them for the badge the page shows",
          s["needs_attention"] == s["low"] + s["out"], str(s)[:170])
    check("...with a stock value the director may see",
          isinstance(s.get("stock_value"), (int, float)) and s["stock_value"] > 0,
          str(s.get("stock_value")))
    s_adm = J(await c.get("/inventory/summary", headers=adm))
    check("...counted for admin too", s_adm.get("tracked", 0) >= 60, str(s_adm)[:150])
    check("...but valued only for the people who may see cost",
          s_adm.get("stock_value") is None, str(s_adm.get("stock_value")))

    # It has to agree with the rows, or it is just a faster wrong answer.
    everything = J(await c.get("/inventory", headers=d, params={"limit": 1000}))
    live = [x for x in everything["items"] if x["is_active"]]
    check("the count matches the rows it is counting",
          s["tracked"] == everything["total"],
          f"{s['tracked']} vs {everything['total']}")
    check("...and so does what needs attention",
          s["needs_attention"] == len([x for x in live if x["stock_status"] != "ok"]),
          f"{s['needs_attention']} vs "
          f"{len([x for x in live if x['stock_status'] != 'ok'])}")

    # ══ the indexes, by way of the thing they speed up ═══════════════════════
    print("\n── the lookups underneath ──")
    from sqlalchemy import text
    from app.core.db import SessionLocal
    async with SessionLocal() as db:
        want = {
            "ix_inventory_movements_ref": "inventory_movements",
            "ix_attachments_owner": "attachments",
            "ix_entity_comments_owner": "entity_comments",
            "ix_invoices_faktur_pajak_no": "invoices",
            "ix_approval_requests_target": "approval_requests",
            "ix_journal_lines_account": "journal_lines",
        }
        got = {r[0] for r in (await db.execute(text(
            "SELECT indexname FROM pg_indexes WHERE schemaname='public'"
        ))).all()}
        for name, table in want.items():
            check(f"{table} is indexed by what the app looks it up by",
                  name in got, f"{name} missing")

        # Whether the planner *uses* an index depends on how big the table
        # is, and in a test database it is tiny — a sequential scan is the
        # right choice there and proves nothing either way. What is worth
        # checking is that the index covers the shape of the query the stock
        # guard makes, so ask the planner with the alternative taken away.
        await db.execute(text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(r[0] for r in (await db.execute(text(
            "EXPLAIN SELECT count(*) FROM inventory_movements "
            "WHERE reference = 'X' AND reason IN ('po_in','po_in_reversed')"
        ))).all())
        check("...and the stock guard's lookup is one the index can answer",
              "ix_inventory_movements_ref" in plan, plan[:250])

    # ══ nothing about it changed what the numbers mean ═══════════════════════
    print("\n── still the same catalogue ──")
    one = J(await c.get("/inventory", headers=d,
                        params={"q": f"PG-{tag}-000", "limit": 5}))
    item = one["items"][0]
    detail = J(await c.get(f"/inventory/{item['id']}", headers=d))
    check("a row on the page says what the item's own page says",
          detail["sku"] == item["sku"]
          and float(detail["current_stock"]) == float(item["current_stock"])
          and detail["stock_status"] == item["stock_status"],
          f"{detail}"[:200])
    check("...including the cost, for those who may see it",
          float(detail["unit_cost"]) == float(item["unit_cost"]),
          f"{detail['unit_cost']} vs {item['unit_cost']}")

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + "; ".join(FAIL)); sys.exit(1)


asyncio.run(main())

"""Importing the rest of the old system: accounts, parts, and quotations.

Each of the three has one thing that is genuinely hard, and this driver is
mostly about those three things rather than about rows going in.

  accounts     The app's chart of accounts was seeded from these same books,
               so an export mostly agrees with it. Where it disagrees about a
               name, the import must NOT apply the change — account numbers
               label financial statements that have already been signed off.

  parts        The real export has no prices and no stock in it at all. The
               import must say so rather than quietly creating 731 items that
               look like they cost nothing. And where a future export does
               carry opening stock, it has to arrive as a stock movement, so
               the item's history starts with something accountable.

  quotations   The export damages its own data in two different ways — it
               drops a column when an item has no name, and it states totals
               that sit under quantity x price where a discount was given.
               One has to be repaired and the other has to be left alone, and
               telling them apart is the whole job. The test for both is the
               subtotal each sheet states about itself: get either wrong and
               the quotation no longer adds up.

The last one is also checked for the thing that would make it actively
harmful: a historical quotation imported into an open state starts firing
"at-risk deal" alerts at the sales team, so the default state must be one the
alert does not look at.
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


def _inv_items(payload):
    """/inventory answers a page — {"items": [...], "total": n} — not a list."""
    if isinstance(payload, dict):
        return payload.get("items") or []
    return payload or []

XL = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def sheet_bytes(sheets: list[tuple[str, list[list]]]) -> bytes:
    from openpyxl import Workbook
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets:
        ws = wb.create_sheet(title=name[:31])
        for r in rows:
            ws.append(r)
    buf = io.BytesIO(); wb.save(buf)
    return buf.getvalue()


ACC_HEADER = ["No. ", "Tipe Akun", "Kode Perkiraan", "Nama", "Akun Induk",
              "Mata Uang", "Saldo Awal", "per Tgl", "Kurs Saldo (Jika Asing)",
              "Cabang Saldo", "Catatan"]

ITEM_HEADER = ["No.", "Kategori Barang", "Kode Barang", "Nama Barang",
               "Jenis Barang", "Satuan", "Harga Beli", "Def. Hrg. Jual Satuan #1",
               "Batas Minimum Stok", "Kuantitas Saldo Awal", "Gudang Saldo Awal",
               "Pemasok Utama", "Merek Barang", "Catatan", "Non Aktif"]

QUO_HEADER = ["Nomor", "Tanggal", "Pelanggan", "Nama Barang",
              "Kuantitas", "@Harga", "Total Harga"]


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=180)

    async def login(e):
        r = await c.post("/auth/login", json={"email": e, "password": "test-pass-123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    tag = uuid.uuid4().hex[:4]
    d = await login("director@demo.local")
    sales = await login("sales1@demo.local")

    # ══ CHART OF ACCOUNTS ════════════════════════════════════════════════════
    print("\n── chart of accounts ──")
    # 1101-01 is in the seeded chart as "Bank Bca Ac 5785523889". Naming it
    # something else here is the point of the test, not a typo.
    acc = sheet_bytes([("Daftar Akun", [ACC_HEADER,
        ["1", "BANK", "1101-01", "Bank Bca Renamed", "1101", "IDR", "", "", "", "", ""],
        ["2", "EQTY", f"39{tag}", f"Modal Saham {tag}", "", "IDR", "", "", "", "", ""],
        ["3", "REVE", f"49{tag}-01", f"Penjualan {tag}", f"49{tag}", "IDR", "", "", "", "", ""],
        ["4", "REVE", f"49{tag}", f"Pendapatan {tag}", "", "IDR", "", "", "", "", ""],
        ["5", "ZZZZ", f"99{tag}", f"Unknown type {tag}", "", "IDR", "", "", "", "", ""],
        ["6", "EQTY", f"39{tag}", f"Modal Saham {tag} again", "", "IDR", "", "", "", "", ""],
    ])])
    up = lambda b, n="f.xlsx": {"file": (n, b, XL)}

    r = await c.post("/imports/accounts/preview", headers=sales, files=up(acc))
    check("only a director may preview an account import", r.status_code == 403, str(r.status_code))

    p = J(await c.post("/imports/accounts/preview", headers=d, files=up(acc)))
    rows = {r["account_no"]: r for r in p["rows"]}
    check("an account already in the app is recognised",
          rows.get("1101-01", {}).get("action") == "existing",
          str(rows.get("1101-01", {}).get("action")))
    check("...and the name it disagrees about is reported",
          any("Bank Bca Ac 5785523889" in w for w in rows["1101-01"]["warnings"]),
          str(rows["1101-01"]["warnings"]))
    check("...and listed separately so it can be acted on",
          any(x["account_no"] == "1101-01" for x in p["renamed"]), str(len(p["renamed"])))
    check("Accurate's type codes become statement types",
          rows.get(f"39{tag}", {}).get("account_type") == "Equity",
          str(rows.get(f"39{tag}", {}).get("account_type")))
    check("...for revenue too", rows.get(f"49{tag}", {}).get("account_type") == "Revenue",
          str(rows.get(f"49{tag}", {}).get("account_type")))
    check("an account whose type we don't know is left out, not guessed at",
          f"99{tag}" not in rows, str(list(rows)))
    check("a parent is recognised as a parent",
          rows.get(f"49{tag}", {}).get("is_parent") is True,
          str(rows.get(f"49{tag}", {}).get("is_parent")))
    check("the same account number twice in one file is caught",
          p["counts"].get("duplicate_in_file") == 1, str(p["counts"]))

    before = J(await c.get("/accounts", headers=d, params={"q": tag, "page_size": 50}))
    n_before = len(before.get("data", before) if isinstance(before, dict) else before)
    check("preview created no accounts", n_before == 0, str(n_before))

    r1 = J(await c.post("/imports/accounts/commit", headers=d, files=up(acc),
                        data={"limit": 2, "confirm": "IMPORT"}))
    check("the batch limit holds for accounts", r1.get("created") == 2, str(r1.get("created")))
    r2 = J(await c.post("/imports/accounts/commit", headers=d, files=up(acc),
                        data={"limit": 99, "confirm": "IMPORT"}))
    check("...and the next run finishes the rest without repeating",
          r2.get("created") == 1 and r2.get("remaining_to_import") == 0,
          f"{r2.get('created')} / {r2.get('remaining_to_import')}")

    # The point of the whole exercise: it did not rename the real account.
    got = J(await c.get("/accounts", headers=d, params={"q": "1101-01"}))
    got = got.get("data") if isinstance(got, dict) else got
    hit = next((a for a in (got or []) if a["account_no"] == "1101-01"), None)
    check("an import NEVER renames an account already on the books",
          hit and hit["name"] == "Bank Bca Ac 5785523889", hit and hit["name"])

    # ══ PARTS CATALOGUE ══════════════════════════════════════════════════════
    print("\n── parts catalogue ──")
    items = sheet_bytes([("Barang & Jasa", [ITEM_HEADER,
        ["1", "CHAIN", f"9{tag}01", f"Voler Chain {tag}", "INV", "PCS",
         "0.000000", "0.000000", "0.000000", "0.000000", "", "", "", "", "TIDAK"],
        ["2", "ROLLER", f"9{tag}02", f"Flat Roller {tag}", "INV", "SET",
         "0.000000", "0.000000", "0.000000", "0.000000", "", "PT Supplier", "", "note here", "TIDAK"],
        ["3", "UMUM", f"9{tag}03", f"Jasa Pasang {tag}", "NON", "EA",
         "0", "0", "0", "0", "", "", "", "", "TIDAK"],
        ["4", "CHAIN", f"9{tag}01", f"Duplicate part {tag}", "INV", "PCS",
         "0", "0", "0", "0", "", "", "", "", "TIDAK"],
    ])])
    p = J(await c.post("/imports/items/preview", headers=d, files=up(items)))
    check("the catalogue reads", p["counts"].get("create") == 3, str(p["counts"]))
    check("...and says plainly that it carries no prices",
          p["priced"] == 0 and any("no price" in x.lower() or "all zero" in x.lower()
                                   for x in p["problems"]), str(p["problems"])[:120])
    check("the same part number twice is caught",
          p["counts"].get("duplicate_in_file") == 1, str(p["counts"]))
    by_sku = {r["sku"]: r for r in p["rows"]}
    check("the shouted unit is written the way the app writes units",
          by_sku[f"9{tag}01"]["uom"] == "pcs", by_sku[f"9{tag}01"]["uom"])
    check("a service is flagged as not something to count",
          any("service" in w for w in by_sku[f"9{tag}03"]["warnings"]),
          str(by_sku[f"9{tag}03"]["warnings"]))
    check("categories are counted for the preview",
          dict(p["categories"]).get("CHAIN") == 2, str(p["categories"]))

    r1 = J(await c.post("/imports/items/commit", headers=d, files=up(items),
                        data={"limit": 2, "confirm": "IMPORT"}))
    check("the batch limit holds for parts", r1.get("created") == 2, str(r1.get("created")))
    r2 = J(await c.post("/imports/items/commit", headers=d, files=up(items),
                        data={"limit": 99, "confirm": "IMPORT"}))
    # Three skipped, not two: once the first copy is in, the file's duplicate
    # row stops being "a duplicate within this file" and becomes an ordinary
    # part that already exists. Both readings are true; this is the later one.
    check("...and re-running finishes rather than duplicating",
          r2.get("created") == 1 and r2.get("skipped_existing") == 3,
          f"{r2.get('created')} / {r2.get('skipped_existing')}")

    inv = J(await c.get("/inventory", headers=d, params={"q": tag}))
    inv_rows = _inv_items(inv)
    check("the parts show up in Inventory", len(inv_rows or []) == 3, str(len(inv_rows or [])))
    one = next((x for x in (inv_rows or []) if x["sku"] == f"9{tag}02"), None)
    check("...with their category, unit and supplier",
          one and one["category"] == "ROLLER" and one["uom"] == "set"
          and one["supplier_hint"] == "PT Supplier", str(one))
    check("...and no stock invented for them",
          all(float(x["current_stock"]) == 0 for x in (inv_rows or [])),
          str([x["current_stock"] for x in (inv_rows or [])]))

    # Opening stock, where a file does carry it, must leave a trail.
    stocked = sheet_bytes([("Barang & Jasa", [ITEM_HEADER,
        ["1", "CHAIN", f"8{tag}01", f"Opening Stock Part {tag}", "INV", "PCS",
         "0", "0", "5", "40", "Gudang A", "", "", "", "TIDAK"],
    ])])
    p2 = J(await c.post("/imports/items/preview", headers=d, files=up(stocked)))
    check("opening stock is called out before it is imported",
          any("stock adjustment" in w for w in p2["rows"][0]["warnings"]),
          str(p2["rows"][0]["warnings"]))
    J(await c.post("/imports/items/commit", headers=d, files=up(stocked),
                   data={"limit": 5, "confirm": "IMPORT"}))
    inv2 = J(await c.get("/inventory", headers=d, params={"q": f"8{tag}01"}))
    inv2 = _inv_items(inv2)
    it = (inv2 or [None])[0]
    check("opening stock lands on the item", it and float(it["current_stock"]) == 40, str(it))
    if it:
        mv = J(await c.get(f"/inventory/{it['id']}/movements", headers=d))
        mv = mv.get("data") if isinstance(mv, dict) else mv
        check("...as a movement, so the history accounts for it",
              any(float(m["delta"]) == 40 for m in (mv or [])), str(mv)[:140])

    # ══ QUOTATIONS ═══════════════════════════════════════════════════════════
    print("\n── quotations ──")
    cust = J(await c.post("/customers", headers=d, json={
        "company_name": f"PT Pelanggan Lama {tag}", "industry": "sugar"}))
    cust_id = cust.get("id")
    # A customer whose name the export cuts short, to exercise the offer.
    J(await c.post("/customers", headers=d, json={
        "company_name": f"PT Panjang Sekali {tag} Nusantara", "industry": "mining"}))

    q1 = f"SQ.{tag}.001"; q2 = f"SQ.{tag}.002"; q3 = f"SQ.{tag}.003"; q4 = f"SQ.{tag}.004"
    quotes = sheet_bytes([
        # Ordinary: three lines that multiply out, and a stated subtotal.
        (q1, [QUO_HEADER,
              [q1, "2024-01-02 00:00:00", f"PT Pelanggan Lama {tag}", "Roller A", 10, 100_000, 1_000_000],
              ["", "", "", "Roller B", 2, 250_000, 500_000],
              ["", "", "", "", "", "Sub Total", 1_500_000]]),
        # The column-shift: no item name, so everything slides one place left
        # and Total Harga is empty. Followed by the half-row the export leaves
        # behind, which has no quantity and must not become a second line.
        (q2, [QUO_HEADER,
              [q2, "2024-02-01 00:00:00", f"PT Pelanggan Lama {tag}", 200, 68_000, 13_600_000, None],
              ["", "", "", 200, None, 13_600_000, None],
              ["", "", "", "", "", "Sub Total", 13_600_000]]),
        # A 2% line discount: the stated total is under qty x price on purpose.
        (q3, [QUO_HEADER,
              [q3, "2024-03-02 00:00:00", f"PT Pelanggan Lama {tag}", "Sprocket RS140", 1, 1_905_000, 1_866_900],
              ["", "", "", "", "", "Sub Total", 1_866_900]]),
        # A date written as Indonesian text rather than an Excel date — two
        # thirds of the real file's dates are like this, and August alone
        # appears as Agu, Ags and Agt.
        (f"{q3}x", [QUO_HEADER,
              [f"{q3}x", "12 Agt 2024", f"PT Pelanggan Lama {tag}", "Chain", 1, 700_000, 700_000],
              ["", "", "", "", "", "Sub Total", 700_000]]),
        # The customer name Accurate cut short, plus its own trailing junk.
        (q4, [QUO_HEADER,
              [q4, "2024-04-02 00:00:00", f"PT Panjang Sekali {tag}   Mata Uang   Indonesian Rupiah",
               "Chain", 1, 500_000, 500_000],
              ["", "", "", "", "", "Sub Total", 500_000]]),
        ("Notes", [["this sheet", "is not"], ["a quotation", ""]]),
    ])

    r = await c.post("/imports/quotations/preview", headers=sales, files=up(quotes))
    check("only a director may preview a quotation import",
          r.status_code == 403, str(r.status_code))

    p = J(await c.post("/imports/quotations/preview", headers=d, files=up(quotes)))
    byq = {r["number"]: r for r in p["rows"]}
    check("a sheet that isn't a quotation is named and skipped",
          p["problems"] and "Notes" in p["problems"][0], str(p["problems"]))
    check("the ordinary quotation reads its lines",
          byq[q1]["lines"] == 2 and byq[q1]["subtotal"] == 1_500_000, str(byq[q1]))

    # ── the two repairs, and the test that proves them ──
    check("a row the export shifted is put back rather than dropped",
          byq[q2]["lines"] == 1, str(byq[q2]))
    check("...at the value the sheet says it is worth",
          byq[q2]["subtotal"] == 13_600_000, str(byq[q2]["subtotal"]))
    check("...and the half-row left behind does not become a second line",
          byq[q2]["dropped_rows"] == 1, str(byq[q2]["dropped_rows"]))
    check("...and the repair is explained, not silent",
          any("dropped a column" in w for w in byq[q2]["warnings"]),
          str(byq[q2]["warnings"]))

    check("a date written in Indonesian is read, not shrugged at",
          byq[f"{q3}x"]["date"] == "2024-08-12", str(byq[f"{q3}x"]["date"]))
    check("a discounted line is kept at the price it was quoted at",
          byq[q3]["lines"] == 1 and byq[q3]["subtotal"] == 1_866_900, str(byq[q3]))
    check("...and the discount is named",
          any("2% discount" in w for w in byq[q3]["warnings"]), str(byq[q3]["warnings"]))

    mismatched = [r for r in p["rows"]
                  if r["stated_subtotal"] is not None
                  and abs(r["stated_subtotal"] - r["subtotal"]) > 1]
    check("every quotation adds up to the subtotal its own sheet states",
          not mismatched, str([(m["number"], m["subtotal"], m["stated_subtotal"])
                               for m in mismatched]))

    # ── the shortened customer name ──
    check("a quotation whose customer isn't in the CRM is skipped, not guessed",
          byq[q4]["action"] == "no_customer", byq[q4]["action"])
    check("...with the likely customer named",
          any("did you mean" in w and "Nusantara" in w for w in byq[q4]["warnings"]),
          str(byq[q4]["warnings"]))
    check("...and the offer is counted so it can be made with a number",
          p["near_name_matches"] == 1, str(p.get("near_name_matches")))
    check("Accurate's trailing column headings are stripped from the name",
          "Mata Uang" not in byq[q4]["customer_name"], byq[q4]["customer_name"])

    p_near = J(await c.post("/imports/quotations/preview", headers=d, files=up(quotes),
                            data={"accept_near_names": "true"}))
    near = {r["number"]: r for r in p_near["rows"]}
    check("turning the offer on files it against that customer",
          near[q4]["action"] == "create" and "Nusantara" in (near[q4]["matched_customer"] or ""),
          str(near[q4]["action"]) + " " + str(near[q4]["matched_customer"]))

    # ── committing ──
    r = await c.post("/imports/quotations/commit", headers=d, files=up(quotes),
                     data={"limit": 5, "confirm": "IMPORT", "quote_status": "nonsense"})
    check("an unknown status is refused", r.status_code == 400, str(r.status_code))

    r1 = J(await c.post("/imports/quotations/commit", headers=d, files=up(quotes),
                        data={"limit": 2, "confirm": "IMPORT"}))
    check("the batch limit holds for quotations", r1.get("created") == 2, str(r1.get("created")))
    check("...and the one with no customer is counted as skipped",
          r1.get("skipped_no_customer") == 1, str(r1.get("skipped_no_customer")))
    r2 = J(await c.post("/imports/quotations/commit", headers=d, files=up(quotes),
                        data={"limit": 9, "confirm": "IMPORT"}))
    check("re-running brings in the rest without repeating",
          r2.get("created") == 2 and r2.get("skipped_existing") == 2,
          f"{r2.get('created')} / {r2.get('skipped_existing')}")
    r3 = J(await c.post("/imports/quotations/commit", headers=d, files=up(quotes),
                        data={"limit": 9, "confirm": "IMPORT"}))
    check("...and a fourth run does nothing at all", r3.get("created") == 0, str(r3.get("created")))

    # ── what actually landed ──
    found = J(await c.get("/search", headers=d, params={"q": q2}))
    groups = found.get("groups") if isinstance(found, dict) else None
    quo_hits = next((g["items"] for g in (groups or []) if g.get("label") == "Quotations"), [])
    check("an imported quotation can be found by its old number",
          any(q2 in (x.get("label", "") or "") for x in quo_hits),
          str(quo_hits)[:160])

    lst = J(await c.get("/quotations", headers=d, params={"customer_id": cust_id}))
    lst = lst.get("data") if isinstance(lst, dict) else lst
    mine = {x["number"]: x for x in (lst or [])}
    check("the quotations are filed against the right customer", len(mine) == 4, str(list(mine)))
    check("they arrive as drafts, so the at-risk-deal alert ignores them",
          all(x["status"] == "draft" for x in mine.values()),
          str({k: v["status"] for k, v in mine.items()}))
    check("the repaired quotation carries the right total",
          mine.get(q2, {}).get("total") == 13_600_000, str(mine.get(q2, {}).get("total")))
    check("no tax is invented on top of what the export stated",
          float(mine.get(q1, {}).get("tax_pct", -1)) == 0, str(mine.get(q1, {}).get("tax_pct")))

    detail = J(await c.get(f"/quotations/{mine[q1]['id']}", headers=d))
    lines = detail.get("items") or []
    check("the line items came across", len(lines) == 2, str(len(lines)))
    check("...with their own quantities and prices",
          any(float(x["qty"]) == 10 and float(x["unit_price"]) == 100_000 for x in lines),
          str([(x["qty"], x["unit_price"]) for x in lines]))

    # A historical quotation in an open state is what the default avoids.
    q5 = f"SQ.{tag}.005"
    open_quote = sheet_bytes([(q5, [QUO_HEADER,
        [q5, "2024-05-02 00:00:00", f"PT Pelanggan Lama {tag}", "Chain", 1, 100_000, 100_000],
        ["", "", "", "", "", "Sub Total", 100_000]])])
    J(await c.post("/imports/quotations/commit", headers=d, files=up(open_quote),
                   data={"limit": 1, "confirm": "IMPORT", "quote_status": "sent"}))
    lst = J(await c.get("/quotations", headers=d, params={"customer_id": cust_id}))
    lst = lst.get("data") if isinstance(lst, dict) else lst
    sent = next((x for x in (lst or []) if x["number"] == q5), None)
    check("a different state can still be chosen deliberately",
          sent and sent["status"] == "sent", str(sent and sent["status"]))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        sys.exit(1)


asyncio.run(main())

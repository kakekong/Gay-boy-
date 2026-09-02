"""Import the customer list from the old accounting system, a batch at a time.

The brief was "don't put all the data in first, let's test it by putting in a
small batch first", and that shapes what this driver checks. A one-shot
importer would be easy; what is hard — and what is actually being asked for —
is an importer you can run *four times*:

    preview            look at the whole file, write nothing
    import 5           eyeball them in the CRM
    import 5 again     the next five, not the same five
    import the rest    and still nothing duplicated

So the properties under test are re-runnability and idempotence, not just
"rows went in". The fixture is a verbatim-shaped slice of the real Accurate
"Daftar Pelanggan" export, including the two things that actually bite:
the same company written three different ways, and `Kategori` carrying the
sales rep as free text ("Customer Candra") because that is where this
company records ownership.

Sales scoping is checked at the end. An imported customer that lands with no
`sales_pic_id` is invisible to the sales rep who owns it in real life, which
would make the import worse than useless — so the linkage is asserted through
the real customer list endpoint, not by reading the column back.
"""
import asyncio, os, sys, uuid
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


HEADER = ("ID Pelanggan,Kategori,Nama,Kontak,No. Telp. Bisnis,Handphone,Email,"
          "Alamat Penagihan,Kota,Provinsi,Kode Pos,Alamat Pengiriman,"
          "Syarat Pembayaran,NPWP,Nama Wajib Pajak,Alamat (Pajak),Catatan")

def fixture(tag: str) -> bytes:
    """The real export's shape, with the awkward rows kept in.

    The rep names carry the run tag because `Kategori` is matched against real
    user accounts by first name, and a shared first name is deliberately left
    unmatched rather than guessed at. Without the tag this driver would start
    failing the moment someone called Candra joined the company.
    """
    rows = [
        # code,      kategori,          nama,                       kontak,  telp,        hp,          email,             alamat,           kota,      prov,        pos,     kirim, termin,  npwp,             wp, alamat pajak, catatan
        f"C.001{tag},Customer Candra{tag},PG. CANDI BARU {tag},Pak Budi,031-991234,081234567,budi@candi.co.id,Jl. Raya Candi 1,Sidoarjo,Jawa Timur,61234,,net 30,01.234.567.8-901.000,PG CANDI BARU,Jl. Raya Candi 1,langganan lama",
        f"C.002{tag},Customer Gora{tag},PT PUPUK SRIWIDJAJA {tag},Bu Rina,0711-712345,,rina@pusri.co.id,Jl. Mayor Zen,Palembang,Sumsel,30118,,net 45,02.345.678.9-012.000,,,",
        f"C.003{tag},Umum,PT. KIDECO JAYA AGUNG {tag},,,08987654,,Jl. Tambang 9,Paser,Kaltim,76281,Site Batu Kajang,C.O.D,,,,",
        f"C.004{tag},customer Kantor,CV.BERKAT JAYA {tag},Pak Anton,,081100022,,Ruko Blok C,Surabaya,Jawa Timur,60119,,,,,,",
        f"C.005{tag},Customer Candra{tag},PT. MAYORA INDAH {tag},Ibu Sari,021-8998,,sari@mayora.co.id,Jl. Tomang Raya 21,Jakarta,DKI Jakarta,11440,,net 30,03.456.789.0-123.000,,,",
        # Same company again, written the way Accurate's second record has it —
        # no space after the dot, and the legal form appended after a comma, so
        # the field has to be quoted exactly as the real export quotes it. Must
        # be caught as a duplicate of the row above, not imported twice.
        f'C.006{tag},Customer Candra{tag},"PT.MAYORA INDAH {tag}, TBK",,,,,Jl. Tomang Raya 21,Jakarta,,,,net 30,,,,',
        # Accurate's own duplicate marker, left in the file by the export.
        f"C.007{tag},Customer Diani{tag},[C.00013] PT.SUKSES MANTAP {tag},,,,,Jl. Industri 5,Gresik,Jawa Timur,,,,,,,",
        # A blank spacer row, which the export really does contain.
        ",,,,,,,,,,,,,,,,",
        f"C.008{tag},Customer Gora{tag},PT SEMEN INDONESIA {tag},Pak Joko,031-3981,,,Jl. Veteran,Gresik,Jawa Timur,61122,Gudang Tuban,net 30,04.567.890.1-234.000,,,",
    ]
    return ("\n".join([HEADER, *rows]) + "\n").encode()


async def main():
    from app.scripts.seed import ensure_schema; await ensure_schema()
    from app.main import app
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://t/api/v1", timeout=120)

    async def login(e, p="test-pass-123"):
        r = await c.post("/auth/login", json={"email": e, "password": p})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    tag = uuid.uuid4().hex[:4]
    d = await login("director@demo.local")
    data = fixture(tag)
    up = lambda: {"file": (f"daftar-pelanggan-{tag}.csv", data, "text/csv")}

    # Two of the three reps named in Kategori exist; "Diani" deliberately does
    # not, so the unmatched-rep warning has something real to report.
    reps = {}
    for first in (f"Candra{tag}", f"Gora{tag}"):
        emp = J(await c.post("/employees", headers=d, json={
            "full_name": f"{first} Wijaya", "intended_role": "sales"}))
        r = J(await c.post("/users", headers=d, json={
            "email": f"{first.lower()}@voler.co.id",
            "full_name": f"{first} Wijaya", "role": "sales",
            "employee_id": emp["id"], "password": "test-pass-123"}))
        reps[first.lower()] = r.get("id")
    check("the sales accounts the import will link to exist",
          all(reps.values()), str(reps))

    # ── who may run it ───────────────────────────────────────────────────────
    for role, email in [("sales", "sales1@demo.local"), ("admin", "admin@demo.local"),
                        ("hr", "hr@demo.local"), ("manager", "manager@demo.local")]:
        h = await login(email)
        r = await c.post("/imports/customers/preview", headers=h, files=up())
        check(f"{role} cannot preview an import", r.status_code == 403, str(r.status_code))
        r = await c.post("/imports/customers/commit", headers=h, files=up(),
                         data={"limit": 1, "confirm": "IMPORT"})
        check(f"{role} cannot commit an import", r.status_code == 403, str(r.status_code))

    # ── preview writes nothing ───────────────────────────────────────────────
    before = J(await c.get("/customers", headers=d, params={"q": tag}))
    n_before = len(before.get("data", before) if isinstance(before, dict) else before)
    p = J(await c.post("/imports/customers/preview", headers=d, files=up()))
    after = J(await c.get("/customers", headers=d, params={"q": tag}))
    n_after = len(after.get("data", after) if isinstance(after, dict) else after)
    check("preview creates nothing", n_before == n_after == 0, f"{n_before} -> {n_after}")

    rows = {r["row_no"]: r for r in p.get("rows", [])}
    check("the blank spacer row is skipped, not imported as a nameless customer",
          p["rows_in_file"] == 9 and len(rows) == 8, f"{p['rows_in_file']} / {len(rows)}")
    check("every non-blank row is accounted for",
          sum(p["counts"].values()) == 8, str(p["counts"]))

    # ── the mapping ──────────────────────────────────────────────────────────
    candi = next((r for r in rows.values() if "CANDI" in r["company_name"]), None)
    check("industry is inferred from the company name",
          candi and candi["industry"] == "sugar", candi and candi["industry"])
    pusri = next((r for r in rows.values() if "PUPUK" in r["company_name"]), None)
    check("...for fertilizer too", pusri and pusri["industry"] == "fertilizer",
          pusri and pusri["industry"])
    kideco = next((r for r in rows.values() if "KIDECO" in r["company_name"]), None)
    check("...and mining", kideco and kideco["industry"] == "mining",
          kideco and kideco["industry"])

    check("Kategori resolves to a real sales account",
          candi and candi["sales_pic_id"] == reps[f"candra{tag}"],
          candi and str(candi["sales_pic_id"]))
    check("'Umum' imports unassigned rather than guessing",
          kideco and kideco["sales_rep_hint"] is None and kideco["sales_pic_id"] is None,
          kideco and str(kideco["sales_rep_hint"]))
    kantor = next((r for r in rows.values() if "BERKAT" in r["company_name"]), None)
    check("'customer Kantor' is the office, not a person",
          kantor and kantor["sales_pic_id"] is None, kantor and str(kantor["sales_rep_hint"]))
    check("a rep with no account is named in the preview, not silently dropped",
          p["unmatched_reps"] == [f"diani{tag}"], str(p["unmatched_reps"]))
    sukses = next((r for r in rows.values() if "SUKSES" in r["company_name"]), None)
    check("...and that row still imports, just unassigned",
          sukses and sukses["action"] == "create" and sukses["sales_pic_id"] is None,
          sukses and sukses["action"])
    check("...with a warning saying why",
          sukses and any(f"diani{tag}" in w for w in sukses["warnings"]),
          sukses and str(sukses["warnings"]))

    check("payment terms are parsed, not just copied",
          candi and candi["payment_terms"].get("kind") == "net"
          and candi["payment_terms"].get("days") == 30, candi and str(candi["payment_terms"]))
    check("...including C.O.D",
          kideco and kideco["payment_terms"].get("kind") == "cod",
          kideco and str(kideco["payment_terms"]))
    check("...and net 45", pusri and pusri["payment_terms"].get("days") == 45,
          pusri and str(pusri["payment_terms"]))

    check("city and province are folded into the address",
          candi and "Sidoarjo" in (candi["company_address"] or "")
          and "Jawa Timur" in (candi["company_address"] or ""),
          candi and candi["company_address"])
    check("NPWP comes across", candi and candi["tax_id"] == "01.234.567.8-901.000",
          candi and candi["tax_id"])
    check("the contact name comes across", candi and candi["pic_name"] == "Pak Budi",
          candi and candi["pic_name"])

    # ── the duplicate the real file actually contains ────────────────────────
    mayoras = [r for r in rows.values() if "MAYORA" in r["company_name"].upper()]
    check("both Mayora rows are seen", len(mayoras) == 2, str(len(mayoras)))
    check("the same company written two ways is flagged once, not imported twice",
          sorted(r["action"] for r in mayoras) == ["create", "duplicate_in_file"],
          str([r["action"] for r in mayoras]))
    check("Accurate's [C.00013] marker doesn't defeat name matching",
          sukses and any("duplicate marker" in w for w in sukses["warnings"]),
          sukses and str(sukses["warnings"]))

    # ── the confirmation ─────────────────────────────────────────────────────
    r = await c.post("/imports/customers/commit", headers=d, files=up(),
                     data={"limit": 5, "confirm": ""})
    check("nothing imports without typing IMPORT", r.status_code == 400, str(r.status_code))
    r = await c.post("/imports/customers/commit", headers=d, files=up(),
                     data={"limit": 0, "confirm": "IMPORT"})
    check("a limit of zero is refused rather than importing everything",
          r.status_code == 400, str(r.status_code))

    # ── batch one ────────────────────────────────────────────────────────────
    want = p["counts"].get("create", 0)
    r1 = J(await c.post("/imports/customers/commit", headers=d, files=up(),
                        data={"limit": 3, "confirm": "IMPORT"}))
    check("the batch limit is respected", r1.get("created") == 3, str(r1.get("created")))
    check("...and it says how many are left",
          r1.get("remaining_to_import") == want - 3,
          f"{r1.get('remaining_to_import')} of {want}")
    lst = J(await c.get("/customers", headers=d, params={"q": tag, "page_size": 50}))
    got = lst.get("data") if isinstance(lst, dict) else lst
    check("...and exactly that many exist in the CRM", len(got) == 3, str(len(got)))

    # ── batch two continues, it does not repeat ──────────────────────────────
    first_names = {x["company_name"] for x in r1["customers"]}
    r2 = J(await c.post("/imports/customers/commit", headers=d, files=up(),
                        data={"limit": 3, "confirm": "IMPORT"}))
    second_names = {x["company_name"] for x in r2["customers"]}
    check("re-running imports the NEXT rows, not the same ones again",
          not (first_names & second_names), str(first_names & second_names))
    check("...and reports the ones it skipped",
          r2.get("skipped_existing") == 3, str(r2.get("skipped_existing")))

    # ── the rest, then a no-op run ───────────────────────────────────────────
    r3 = J(await c.post("/imports/customers/commit", headers=d, files=up(),
                        data={"limit": 999, "confirm": "IMPORT"}))
    check("a large limit finishes the file",
          r3.get("remaining_to_import") == 0, str(r3.get("remaining_to_import")))
    r4 = J(await c.post("/imports/customers/commit", headers=d, files=up(),
                        data={"limit": 999, "confirm": "IMPORT"}))
    check("importing an already-imported file creates nothing",
          r4.get("created") == 0, str(r4.get("created")))

    lst = J(await c.get("/customers", headers=d, params={"q": tag, "page_size": 50}))
    got = lst.get("data") if isinstance(lst, dict) else lst
    check("the whole file lands as the right number of customers",
          len(got) == want, f"{len(got)} vs {want} expected")
    check("...and the duplicate Mayora is in there exactly once",
          sum(1 for x in got if "MAYORA" in x["company_name"].upper()) == 1,
          str([x["company_name"] for x in got if "MAYORA" in x["company_name"].upper()]))

    # ── the point of importing Kategori at all ───────────────────────────────
    candra = await login(f"candra{tag}@voler.co.id")
    mine = J(await c.get("/customers", headers=candra, params={"q": tag, "page_size": 50}))
    mine_rows = mine.get("data") if isinstance(mine, dict) else mine
    names = {x["company_name"] for x in mine_rows}
    check("an imported customer shows up for the sales rep who owns it",
          any("CANDI" in n for n in names), str(sorted(names)))
    check("...and the other rep's customers do not",
          not any("PUPUK" in n for n in names), str(sorted(names)))

    one = next((x for x in got if "CANDI" in x["company_name"]), None)
    if one:
        full = J(await c.get(f"/customers/{one['id']}", headers=d))
        check("the Accurate code is kept so a second import can recognise the row",
              full.get("external_code") == f"C.001{tag}", str(full.get("external_code")))
        check("imported customers start at the beginning of the pipeline",
              full.get("stage") == "lead", str(full.get("stage")))
        check("the NPWP marks them as PKP", full.get("is_pkp") is True, str(full.get("is_pkp")))

    # ── bad input fails clearly instead of half-importing ────────────────────
    r = await c.post("/imports/customers/preview", headers=d,
                     files={"file": ("wrong.csv", b"Kode,Deskripsi,Qty\nA-1,Bearing,4\n", "text/csv")})
    body = J(r)
    check("the wrong spreadsheet is named as such, not silently imported as blanks",
          r.status_code == 200 and body.get("problems")
          and not body.get("rows"), str(body)[:120])
    r = await c.post("/imports/customers/commit", headers=d,
                     files={"file": ("wrong.csv", b"Kode,Deskripsi\nA-1,Bearing\n", "text/csv")},
                     data={"limit": 5, "confirm": "IMPORT"})
    check("...and committing it is refused", r.status_code == 400, str(r.status_code))
    r = await c.post("/imports/customers/preview", headers=d,
                     files={"file": ("empty.csv", b"", "text/csv")})
    check("an empty file is refused", r.status_code == 400, str(r.status_code))

    # ── the same file as .xlsx, which is what they will actually upload ──────
    try:
        import csv, io
        from openpyxl import Workbook
        wb = Workbook(); ws = wb.active
        for row in csv.reader(io.StringIO(data.decode())):
            ws.append(row)
        buf = io.BytesIO(); wb.save(buf)
        x = J(await c.post("/imports/customers/preview", headers=d,
                           files={"file": ("daftar-pelanggan.xlsx", buf.getvalue(),
                                           "application/vnd.openxmlformats-officedocument"
                                           ".spreadsheetml.sheet")}))
        # Same file, same conclusion: everything in it is already in the CRM,
        # including the duplicate row, which now matches the row it duplicates.
        check("an .xlsx export reads the same as the .csv",
              x.get("rows_in_file") == 9 and x["counts"] == {"existing": 8},
              str(x.get("counts")))
    except ImportError:
        check("openpyxl is available to read .xlsx exports", False, "not installed")

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        sys.exit(1)


asyncio.run(main())

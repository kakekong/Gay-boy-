"""Where the money sits on the printed quotation, and how much room the notes get.

Asked for, against a marked-up print: put the price block behind the line the
sender drew — the rule between SATUAN and UNIT — move it up a little, and give
KETERANGAN more room.

Those are one change, not three. The totals block used to be sized in
fractions of the page (48/8/24/20), which put its left edge at 119.7mm, a
centimetre inside the SATUAN column: the prices hung under the wrong heading
and the notes panel was squeezed to 85mm for nothing. Sizing it off the item
grid instead — the last three columns, 69mm — lands it exactly on the rule and
hands the 20mm back to the notes.

The fourth check here is a different bug the same print exposed: senders type
"1." at the start of each note themselves, and the builder added its own
number on top, so every line printed as "1. 1. Drawing akan…".

Geometry is read back out of the PDF rather than eyeballed, because the whole
point is where things landed on the page.
"""
import asyncio, os, re as _re, sys, uuid
os.environ.update(DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:55432/transmisi_test",
    APP_ENV="dev", DEMO_SEED_PASSWORD="test-pass-123",
    STORAGE_LOCAL_DIR="/tmp/storage_test", JWT_SECRET="e2e-test-secret")
sys.path.insert(0, "/home/user/Gay-boy-/backend")
import fitz, httpx, logging; logging.disable(logging.INFO)
PASS, FAIL = [], []
def check(n, c, d=""):
    (PASS if c else FAIL).append(n); print(("  PASS " if c else "  FAIL ")+n+(f"  [{d}]" if d and not c else ""))
def J(r):
    try: return r.json()
    except Exception: return {"_": r.text[:200]}

MM = 72 / 25.4                     # PDF points per millimetre

# What a sender actually types: their own numbering, one clause per line.
NOTES = "\n".join([
    "1. Drawing akan diberikan setelah PO diterima dan harus approval.",
    "2. Merek yang ditawarkan : VOLER (www.voler.co.id).",
    "3. PO boleh di batalkan jika barang tidak sesuai sample.",
    "4. Waktu Penyerahan (WP) : +- 120 hari dari PO dan Drawing Approval.",
    "5. Penawaran berlaku selama 1 Bulan.",
    "6. Harga penawaran adalah Franco Gudang PT. Diamond Cold Storage.",
    "7. Pembayaran : 30 hari setelah Barang dan Invoice diterima.",
])


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
    rp = await login("sales1@demo.local")

    cust = J(await c.post("/customers", headers=rp, json={
        "company_name": f"PT Cetak {tag}", "industry": "mining"}))["id"]
    desc = ("HAIN CONVEYOR PITCH 27 7MM,SS,VOLER CHAIN PITCH 12.7MM WITH "
            f"CUSTOM ATTACHMENT MAT STAINLESS SUS {tag}")
    # sales file price requests, not quotations; the director writes this one
    # and it lands in the account rep's name, which is whose print this is.
    q = J(await c.post("/quotations", headers=d, json={
        "customer_id": cust, "variant": "detailed", "notes": NOTES,
        "items": [{"line_no": 1, "description": desc, "qty": 50,
                   "uom": "METER", "unit_price": 4_085_000}]}))

    r = await c.get(f"/quotations/{q['id']}/export.pdf", headers=rp)
    check("the quotation prints", r.status_code == 200 and r.content[:4] == b"%PDF",
          f"{r.status_code} {r.content[:20]}")
    doc = fitz.open(stream=r.content, filetype="pdf")
    check("...on one page", doc.page_count == 1, str(doc.page_count))
    page = doc.load_page(0)
    text = page.get_text()
    # our own number is set off with a non-breaking space; flatten it so the
    # doubled-up "1. 1." reads as one string here the way it does on paper
    flat = _re.sub(r"\s+", " ", text.replace("\xa0", " "))

    def at(needle):
        hits = page.search_for(needle)
        return hits[0] if hits else None

    # ══ the numbering ════════════════════════════════════════════════════════
    print("\n── the notes are numbered once, not twice ──")
    check("no line comes out double-numbered",
          not any(f"{i}. {i}." in flat for i in range(1, 8)),
          flat[flat.find("KETERANGAN"):][:160])
    check("...the first note still reads as the sender wrote it",
          "Drawing akan diberikan setelah PO diterima" in text,
          text[text.find("KETERANGAN"):][:200])
    check("...and all seven survived",
          all(frag in text for frag in
              ["VOLER", "tidak sesuai sample", "120 hari", "1 Bulan",
               "Franco Gudang", "30 hari setelah Barang"]),
          text[text.find("KETERANGAN"):][:400])
    check("...still numbered, so they can be quoted back over the phone",
          "7." in text[text.find("KETERANGAN"):], text[text.find("KETERANGAN"):][:400])

    # ══ where the money sits ═════════════════════════════════════════════════
    print("\n── the price block is behind the rule, not straddling it ──")
    satuan, unit, sub = at("SATUAN"), at("UNIT"), at("SUB TOTAL")
    check("the print has the columns this is measured against",
          None not in (satuan, unit, sub), f"{satuan} {unit} {sub}")
    check("SUB TOTAL starts on the UNIT column, to the millimetre",
          abs(sub.x0 - unit.x0) < 0.5 * MM,
          f"sub {sub.x0 / MM:.1f}mm vs unit {unit.x0 / MM:.1f}mm")
    check("...which is right of where SATUAN ends",
          sub.x0 > satuan.x1, f"{sub.x0 / MM:.1f} vs {satuan.x1 / MM:.1f}")
    line_amt, hdr = at("204.250.000"), at("TOTAL HARGA (IDR)")
    check("...the line amount still hangs under its own heading",
          line_amt and hdr and abs(line_amt.x1 - hdr.x1) < 1 * MM,
          f"{line_amt} {hdr}")
    ends = {round((page.search_for(v)[-1]).x1 / MM, 1)
            for v in ("204.250.000", "22.467.500", "226.717.500")
            if page.search_for(v)}
    check("...and subtotal, PPN and total end on one right edge",
          len(ends) == 1, str(sorted(ends)))

    # ══ the room it freed ════════════════════════════════════════════════════
    print("\n── and the notes panel got the difference ──")
    fills = [g["rect"] for g in page.get_drawings() if g.get("fill")]
    panel = max((f for f in fills if f.height > 20 * MM and f.width < 140 * MM),
                key=lambda f: f.width, default=None)
    check("the KETERANGAN panel is wider than the old 85mm",
          panel is not None and panel.width > 100 * MM,
          panel and f"{panel.width / MM:.1f}mm")
    check("...and it stops at the gutter rather than running under the prices",
          panel is not None and panel.x1 < sub.x0, panel and f"{panel.x1 / MM:.1f}mm")

    ket, item = at("KETERANGAN"), at(f"SUS {tag}")
    check("the block sits close under the last item line",
          ket and item and (ket.y0 - item.y1) < 6.5 * MM,
          ket and item and f"{(ket.y0 - item.y1) / MM:.1f}mm")

    # ══ and it survives the shapes that used to break it ═════════════════════
    print("\n── the awkward cases ──")
    r = await c.patch(f"/quotations/{q['id']}", headers=rp, json={"notes": ""})
    r = await c.get(f"/quotations/{q['id']}/export.pdf", headers=rp)
    empty = fitz.open(stream=r.content, filetype="pdf")
    check("a quotation with no notes at all still prints on one page",
          r.status_code == 200 and empty.page_count == 1,
          f"{r.status_code} {empty.page_count}")

    long_notes = "\n".join(f"{i}) " + ("syarat pembayaran dan pengiriman " * 4)
                           for i in range(1, 13))
    await c.patch(f"/quotations/{q['id']}", headers=rp, json={"notes": long_notes})
    r = await c.get(f"/quotations/{q['id']}/export.pdf", headers=rp)
    long_doc = fitz.open(stream=r.content, filetype="pdf")
    check("twelve long notes print without losing any",
          r.status_code == 200 and long_doc.page_count >= 1
          and "12." in "".join(p.get_text() for p in long_doc),
          f"{r.status_code} pages={long_doc.page_count}")
    check('...and "1)" is stripped the same as "1."',
          "1) syarat" not in "".join(p.get_text() for p in long_doc),
          "".join(p.get_text() for p in long_doc)[:200])

    # the director's copy of the same document is the same document
    r = await c.get(f"/quotations/{q['id']}/export.pdf", headers=d)
    check("the director prints the same layout", r.status_code == 200
          and r.content[:4] == b"%PDF", str(r.status_code))

    await c.aclose()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        sys.exit(1)


asyncio.run(main())

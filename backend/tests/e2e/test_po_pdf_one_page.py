"""The supplier PO prints on one page when it can.

A two-line PO with a long set of notes was printing "Yours sincerely" at the
foot of page one and the signature alone on page two. The sheet now steps down
its spacing (and, last, its type) until it fits one page; the sign-off never
splits; and a PO too long for one page anyway keeps the roomy layout.

Also: a Chinese vendor's full-width comma ("FLOOR，THE") printed as a black
box, and an "&" in a name could break the sheet.
"""
import io, sys
sys.path.insert(0, "/home/user/Gay-boy-/backend")
from pypdf import PdfReader

from app.services.supplier_po_pdf import build_supplier_po_pdf

PASS, FAIL = [], []
def check(n, c, d=""):
    (PASS if c else FAIL).append(n); print(("  PASS " if c else "  FAIL ")+n+(f"  [{d}]" if d and not c else ""))

NOTES = """Mark : "VOLER" at Outer Plate
1. Inspection Report ( Material, Dimentional, Hardness, Length, Tensile Strength), Certificate of Manufacture (COM) Before Send out
2. Delivery Time : 40 Days after Drawing Approval
3. Delivery Point : To Be Advised
4. Term of payment : 30 Days after Receive Goods
5. Package : Wooden Case with Plastic inside cover the chain.
6. Quality Discrepancy : Any issues or complaints should be filed by the Buyer within 12 months after the arrival of the goods at port of destination."""
ROWS = [
    {"description": "CHAIN P600 two side 91.2 meter*2 (DWG: P600-SR-G2L2)", "qty": 91.2,
     "uom": "meter", "unit_price": 1020, "amount": 93024},
    {"description": "for Sample 4 links left, 4 link right", "qty": 4.8, "uom": "meter",
     "unit_price": 1020, "amount": 4896},
]
BASE = dict(
    number="PO-GZG-261012-002", po_date="12 Oct 2026",
    supplier_name="GUI ZHOU GZG TRANSMISSION CO.,LIMITED & SONS",
    supplier_address="North side of the second floor，the newly built building 12-5, "
                     "Sanxian Cultural Creative Park, Duyun City, Guizhou",
    supplier_pic="Lucy", supplier_phone="Wechat ID : liutingyqn",
    supplier_email="lucy@gzg-transmission.com",
    ship_to_label="PT. Transmisi Enjinering warehouse",
    ship_to_address="— delivery address not set, please confirm with us —",
    project_code="PRJ-2026-0019", lead_days=None, currency="CNY",
    rows=ROWS, total=97920, notes=NOTES, issued_by="Calderon", issuer_signature=None,
)


def pages(**over):
    r = PdfReader(io.BytesIO(build_supplier_po_pdf(**dict(BASE, **over))))
    return [p.extract_text() or "" for p in r.pages]


got = pages()
check("the GZG order with its long notes is one page", len(got) == 1, f"{len(got)} pages")
check("...and still carries the sign-off", "Yours sincerely" in got[-1] and "Calderon" in got[-1])
check("the full-width comma prints as a comma", "second floor, the newly" in got[0],
      got[0][:400])
check("an '&' in the supplier's name prints", "LIMITED &" in got[0] and "&AMP" not in got[0])

got = pages(notes=None)
check("without notes it is one page too", len(got) == 1, f"{len(got)} pages")

got = pages(rows=ROWS * 20)
check("a 40-line order runs on to a second page", len(got) >= 2, f"{len(got)} pages")
sign = [i for i, t in enumerate(got) if "Yours sincerely" in t]
check("...with the sign-off whole on one page",
      len(sign) == 1 and "Calderon" in got[sign[0]], str(sign))

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED: " + "; ".join(FAIL)); sys.exit(1)

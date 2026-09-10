"""The part code and the part name must not print on top of each other.

The quotation's KODE BARANG column was a flat 20mm holding a plain string, and
ReportLab does not wrap a plain string — it lets it run straight over the cell
next to it. `DUS-CLP-RC-0001` needs 27mm with its padding, so it printed across
NAMA BARANG and the two columns read as one smear. The header itself needs
23mm, so it overflowed on every quotation ever printed, whatever the codes
were.

The column is measured now: wide enough for the widest code on the document,
clamped so a short-SKU quotation does not look lopsided and one pathological
code cannot eat the column people actually read. Past the ceiling the code
wraps, which is ugly and legible, rather than overflowing, which is neither.

These assert on where the ink actually lands — the text boxes pdfminer reads
back out of the finished file — because the bug was invisible to anything that
only checked the strings were present. Both columns were there. They were in
the same place.
"""

from io import BytesIO

import pytest
from pdfminer.high_level import extract_pages
from pdfminer.layout import LTTextContainer
from reportlab.lib.units import mm

from app.services.quotation_pdf import build_quotation_pdf


def _pdf(rows):
    return build_quotation_pdf(
        number="QT-TSE-2026-0014", issued="2026-09-05",
        customer_name="PT MANGOLE TIMBER PRODUCEER",
        customer_address="Jakarta", cp_name="Candra",
        cp_position="Purchasing", cp_email="c@example.com",
        rows=rows, subtotal=1_903_000, discount=0, tax_pct=11,
        tax=209_330, total=2_112_330, notes="Status : Ready Stock",
        signer_name="A", signer_phone="1", signer_email="a@example.com",
    )


def _box(pdf: bytes, needle: str):
    """Where a piece of text sits on page one, in points, or None."""
    for page in extract_pages(BytesIO(pdf)):
        for el in page:
            if isinstance(el, LTTextContainer) and needle in el.get_text():
                return el.x0, el.x1
        return None
    return None


def _row(code, name="Roller Chain 120-2"):
    return {"code": code, "name": name, "qty": 1, "uom": "ROLL",
            "unit_price": 1_903_000, "line_total": 1_903_000}


@pytest.mark.parametrize("code", [
    "DUS-CLP-RC-0001",                            # the reported case
    "100135",                                     # a short generated SKU
    "DUS-CLP-RC-0001-EXTREMELY-LONG-VARIANT-XYZ",  # past the clamp: must wrap
])
def test_code_never_runs_into_the_name(code):
    pdf = _pdf([_row(code)])
    head = code.split("-")[0][:7] if "-" in code else code
    code_box = _box(pdf, head)
    name_box = _box(pdf, "Roller Chain")
    assert code_box and name_box, f"missing text for {code!r}"
    # The name starts after the code ends. Negative is the bug: the two
    # columns overlapping is what made the printed line unreadable.
    gap = name_box[0] - code_box[1]
    assert gap >= 0, (
        f"code and name overlap by {abs(gap) / mm:.1f}mm for {code!r}")


def test_a_missing_code_does_not_break_the_row():
    """A line with no catalogue code still prints its name."""
    pdf = _pdf([_row(None)])
    assert _box(pdf, "Roller Chain") is not None


def test_the_column_grows_for_a_long_code_and_not_for_a_short_one():
    """The width follows the content — that is the whole point of measuring."""
    short = _box(_pdf([_row("100135")]), "Roller Chain")
    long_ = _box(_pdf([_row("DUS-CLP-RC-0001")]), "Roller Chain")
    assert short and long_
    # A wider code column pushes the name column to the right.
    assert long_[0] > short[0], (
        f"name column did not move for a longer code: {short[0]} vs {long_[0]}")


def test_the_header_fits_even_when_every_code_is_short():
    """"KODE BARANG" is 23mm wide; a 20mm floor would clip the header on a
    document whose codes are all short, which was true of every quotation."""
    pdf = _pdf([_row("1")])
    head = _box(pdf, "KODE BARANG")
    name_head = _box(pdf, "NAMA BARANG")
    assert head and name_head
    assert name_head[0] - head[1] >= 0, "the header row itself overlaps"

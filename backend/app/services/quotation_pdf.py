"""The PENAWARAN HARGA sheet — PT Transmisi Enjinering's quotation letterhead.

Built to match the company's own design (colours sampled straight off it:
navy #033171, orange #F5820A, panel #F5F6F8), so what the customer receives
looks like the document the office already sends, not a generic export.

Structure, top to bottom: a double rule frame, the letterhead with contact
details, the PENAWARAN HARGA title under an orange rule, KEPADA facing
INFORMASI PENAWARAN, the item table, KETERANGAN facing the totals with the
grand total in a navy bar, the signature block, the four capability marks, and
a footer rule. The frame, letterhead and footer are drawn on the canvas so they
repeat on every page; the rest flows.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate, Frame, KeepTogether, PageTemplate, Paragraph, Spacer,
    Table, TableStyle,
)

NAVY = colors.HexColor("#033171")
NAVY_DARK = colors.HexColor("#02245A")
ORANGE = colors.HexColor("#F5820A")
PANEL = colors.HexColor("#F5F6F8")
RULE = colors.HexColor("#D7DBE2")
INK = colors.HexColor("#1A1A1A")
INK_SOFT = colors.HexColor("#55585E")

# Letterhead. Kept here rather than in the database because it is print
# stationery, not data — one place to correct when the office moves.
COMPANY_NAME = "PT. TRANSMISI ENJINERING"
COMPANY_TAGLINE = "ENGINEERING CONVEYOR CHAIN SPECIALIST"
COMPANY_ADDRESS = [
    "PIK AVENUE MALL LEVEL 6 PANTAI INDAH KAPUK BOULEVARD,",
    "KAMAL MUARA, PENJARINGAN,",
    "KOTA ADMINISTRASI JAKARTA UTARA DKI JAKARTA 14470",
]
COMPANY_EMAIL = "transmisi.eng@gmail.com"
COMPANY_WA = "0813 1659 0808"
COMPANY_WEB = "https://transmisi-eng.com"

CAPABILITIES = [
    ("QUALITY", "PRODUCT"),
    ("CUSTOM", "ENGINEERING"),
    ("RELIABLE", "PERFORMANCE"),
    ("ON-TIME", "DELIVERY"),
]

# Drop a PNG here and it replaces the drawn placeholder mark. Absent by
# default so the export never depends on a file that may not be committed.
LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "te-logo.png"

MARGIN_X = 16 * mm
FRAME_PAD = 6 * mm
HEADER_H = 46 * mm
FOOTER_H = 16 * mm


def _idr_plain(n) -> str:
    """Indonesian thousands, no currency prefix — the table columns already
    say (IDR), and repeating 'Rp' on every row is noise."""
    n = float(n or 0)
    sign = "-" if n < 0 else ""
    return sign + f"{abs(n):,.0f}".replace(",", ".")


def _draw_frame_and_chrome(canvas, doc) -> None:
    """Everything that repeats on each page: the double border, the
    letterhead and the footer rule."""
    canvas.saveState()
    w, h = A4

    # Double rule frame — orange outside, navy inside.
    canvas.setStrokeColor(ORANGE)
    canvas.setLineWidth(1.6)
    canvas.rect(8 * mm, 8 * mm, w - 16 * mm, h - 16 * mm)
    canvas.setStrokeColor(NAVY)
    canvas.setLineWidth(0.8)
    canvas.rect(10 * mm, 10 * mm, w - 20 * mm, h - 20 * mm)

    top = h - 18 * mm

    # ── Logo ────────────────────────────────────────────────────────────
    logo_w, logo_h = 22 * mm, 16 * mm
    if LOGO_PATH.exists():
        canvas.drawImage(str(LOGO_PATH), MARGIN_X, top - logo_h,
                         width=logo_w, height=logo_h,
                         preserveAspectRatio=True, mask="auto")
    else:
        # A stand-in mark in the brand's geometry until the real artwork is
        # dropped in: an orange chevron over a navy bar.
        cx, cy = MARGIN_X + logo_w / 2, top - logo_h / 2
        canvas.setFillColor(ORANGE)
        p = canvas.beginPath()
        p.moveTo(cx - 9 * mm, cy - 5 * mm)
        p.lineTo(cx, cy + 6 * mm)
        p.lineTo(cx + 9 * mm, cy - 5 * mm)
        p.lineTo(cx + 4.5 * mm, cy - 5 * mm)
        p.lineTo(cx, cy + 1.5 * mm)
        p.lineTo(cx - 4.5 * mm, cy - 5 * mm)
        p.close()
        canvas.drawPath(p, fill=1, stroke=0)
        canvas.setFillColor(NAVY)
        canvas.rect(cx - 9 * mm, cy - 7.6 * mm, 18 * mm, 1.8 * mm, fill=1, stroke=0)

    # ── Company name + tagline ──────────────────────────────────────────
    name_x = MARGIN_X + logo_w + 6 * mm
    canvas.setFillColor(INK)
    canvas.setFont("Helvetica-Bold", 14.5)
    canvas.drawString(name_x, top - 8 * mm, COMPANY_NAME)
    canvas.setFillColor(INK_SOFT)
    canvas.setFont("Helvetica", 6.6)
    canvas.drawString(name_x, top - 12.5 * mm, " ".join(COMPANY_TAGLINE))

    # ── Contact block, top right ────────────────────────────────────────
    # The design marks this block as belonging on the right-hand side of the
    # letterhead rather than under the company name.
    right = w - MARGIN_X
    y = top - 3 * mm
    canvas.setFont("Helvetica", 6.6)
    canvas.setFillColor(INK)
    for line in COMPANY_ADDRESS:
        canvas.drawRightString(right, y, line)
        y -= 3.2 * mm
    y -= 1.0 * mm
    canvas.setFillColor(INK_SOFT)
    canvas.drawRightString(right, y, f"Email : {COMPANY_EMAIL}   ·   WA : {COMPANY_WA}")
    y -= 3.2 * mm
    canvas.drawRightString(right, y, f"Website : {COMPANY_WEB}")

    # Hairline under the letterhead.
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.7)
    canvas.line(MARGIN_X, top - 27 * mm, right, top - 27 * mm)

    # ── Capability marks + footer ───────────────────────────────────────
    _capability_row(canvas, doc, 24 * mm)
    fy = 16 * mm
    canvas.setStrokeColor(RULE)
    canvas.line(MARGIN_X, fy + 4 * mm, right, fy + 4 * mm)
    canvas.setFillColor(INK_SOFT)
    canvas.setFont("Helvetica", 7)
    canvas.drawString(MARGIN_X, fy, " ".join(COMPANY_NAME))
    canvas.drawCentredString(w / 2, fy, " ".join("PENAWARAN HARGA"))
    canvas.drawRightString(right, fy, f"PAGE {doc.page:02d} / {doc._total_pages:02d}"
                           if getattr(doc, "_total_pages", None) else f"PAGE {doc.page:02d}")
    canvas.restoreState()


def _capability_row(canvas, doc, y: float) -> None:
    """The four capability marks along the bottom of the sheet."""
    w = A4[0]
    right = w - MARGIN_X
    span = right - MARGIN_X
    step = span / len(CAPABILITIES)
    canvas.saveState()
    for i, (top_word, bottom_word) in enumerate(CAPABILITIES):
        cx = MARGIN_X + step * i + step / 2
        canvas.setStrokeColor(NAVY)
        canvas.setLineWidth(0.9)
        canvas.circle(cx - 16 * mm, y + 1.2 * mm, 3.4 * mm, fill=0, stroke=1)
        canvas.setFillColor(NAVY)
        canvas.setFont("Helvetica-Bold", 6.8)
        canvas.drawString(cx - 10 * mm, y + 2.6 * mm, top_word)
        canvas.setFillColor(INK_SOFT)
        canvas.drawString(cx - 10 * mm, y - 1.0 * mm, bottom_word)
    canvas.restoreState()


class _Doc(BaseDocTemplate):
    """Two-pass build so the footer can print 'PAGE 01 / 03'."""

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        self._total_pages = None

    def afterFlowable(self, flowable):  # noqa: D102
        pass


def build_quotation_pdf(*, number: str, issued: str, customer_name: str,
                        customer_address: str, cp_name: str, cp_position: str,
                        cp_email: str, rows: list[dict], subtotal: float,
                        discount: float, tax_pct: float, tax: float,
                        total: float, notes: str | None,
                        signer_name: str, signer_phone: str,
                        signer_email: str) -> bytes:
    buf = BytesIO()
    doc = _Doc(
        buf, pagesize=A4,
        leftMargin=MARGIN_X, rightMargin=MARGIN_X,
        topMargin=18 * mm + HEADER_H - 18 * mm, bottomMargin=FOOTER_H + 14 * mm,
        title=f"Penawaran Harga {number}",
    )
    content_w = A4[0] - 2 * MARGIN_X
    frame = Frame(
        MARGIN_X, FOOTER_H + 14 * mm, content_w,
        A4[1] - (18 * mm + 30 * mm) - (FOOTER_H + 14 * mm),
        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
    )
    doc.addPageTemplates([
        PageTemplate(id="sheet", frames=[frame], onPage=_draw_frame_and_chrome),
    ])

    title = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=21,
                           textColor=NAVY, alignment=1, spaceAfter=0, leading=24)
    lbl = ParagraphStyle("lbl", fontName="Helvetica-Bold", fontSize=8.6,
                         textColor=NAVY, spaceAfter=3)
    body = ParagraphStyle("body", fontName="Helvetica", fontSize=8.4,
                          textColor=INK, leading=12)
    body_b = ParagraphStyle("bodyb", parent=body, fontName="Helvetica-Bold", fontSize=9.6)
    small = ParagraphStyle("small", parent=body, fontSize=7.2, leading=10.4,
                           textColor=INK_SOFT)

    flow: list = []
    flow.append(Paragraph("PENAWARAN HARGA", title))
    flow.append(_OrangeRule(width=34 * mm, thickness=2.2))
    flow.append(Spacer(1, 5 * mm))

    # ── KEPADA  |  INFORMASI PENAWARAN ──────────────────────────────────
    # Both panels are single Paragraphs inside one flat table. Nesting a table
    # that contains Paragraphs inside another table's cell makes reportlab
    # compute an unbounded row height and abort the build.
    cp_line = ""
    if cp_name and cp_name != "—":
        pos = f" &nbsp;&nbsp;{cp_position}" if cp_position and cp_position != "—" else ""
        cp_line = (f'<br/><br/><font color="#55585E">CP&nbsp;&nbsp;&nbsp;&nbsp;: </font>'
                   f"{cp_name}{pos}"
                   f'<br/><font color="#55585E">Email : </font>{cp_email or "—"}')
    kepada_html = (f"<b>{customer_name.upper()}</b><br/>"
                   f'<font size="8.4">{customer_address or "—"}</font>{cp_line}')
    info_html = (f'<font color="#55585E">NOMOR</font>'
                 f"&nbsp;&nbsp;&nbsp;&nbsp;:&nbsp;&nbsp;<b>{number}</b><br/><br/>"
                 f'<font color="#55585E">TANGGAL</font>&nbsp;&nbsp;:&nbsp;&nbsp;{issued}')

    panel_body = ParagraphStyle("panel", parent=body, fontSize=8.6, leading=13)
    panel_info = ParagraphStyle("panelinfo", parent=body, fontSize=9.4, leading=17)

    flow.append(Table(
        [[Paragraph("KEPADA", lbl), "", Paragraph("INFORMASI PENAWARAN", lbl)],
         [Paragraph(kepada_html, panel_body), "", Paragraph(info_html, panel_info)]],
        colWidths=[content_w * 0.46, content_w * 0.08, content_w * 0.46],
        style=TableStyle([
            ("VALIGN", (0, 1), (-1, 1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, 0), 0),
            ("RIGHTPADDING", (0, 0), (-1, 0), 0),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
            ("BACKGROUND", (0, 1), (0, 1), PANEL),
            ("BACKGROUND", (2, 1), (2, 1), PANEL),
            ("LEFTPADDING", (0, 1), (0, 1), 5 * mm),
            ("RIGHTPADDING", (0, 1), (0, 1), 5 * mm),
            ("LEFTPADDING", (2, 1), (2, 1), 5 * mm),
            ("RIGHTPADDING", (2, 1), (2, 1), 5 * mm),
            ("TOPPADDING", (0, 1), (-1, 1), 5 * mm),
            ("BOTTOMPADDING", (0, 1), (-1, 1), 5 * mm),
        ])))
    flow.append(Spacer(1, 5 * mm))

    # ── Items ───────────────────────────────────────────────────────────
    item_name = ParagraphStyle("itemname", parent=body, fontSize=7.4, leading=9.4)
    head = ["KODE BARANG", "NAMA BARANG", "SATUAN", "UNIT",
            "@HARGA (IDR)", "TOTAL HARGA (IDR)"]
    data = [head]
    for r in rows:
        data.append([
            r["code"],
            Paragraph(r["name"], item_name),
            r["qty"],
            r["uom"],
            _idr_plain(r["unit_price"]),
            _idr_plain(r["line_total"]),
        ])
    col = [20 * mm, content_w - 20 * mm - 15 * mm - 14 * mm - 25 * mm - 30 * mm,
           15 * mm, 14 * mm, 25 * mm, 30 * mm]
    items = Table(data, colWidths=col, repeatRows=1)
    items.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7.4),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 7.4),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (2, 0), (3, -1), "CENTER"),
        ("ALIGN", (4, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, 0), 2.8 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 2.8 * mm),
        ("TOPPADDING", (0, 1), (-1, -1), 1.9 * mm),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 1.9 * mm),
        ("LINEBELOW", (0, 1), (-1, -1), 0.5, RULE),
    ]))
    flow.append(items)
    flow.append(Spacer(1, 5 * mm))

    # ── KETERANGAN  |  totals ───────────────────────────────────────────
    # One flat table again: the notes cell spans every totals row rather than
    # holding a nested table.
    note_lines = [n.strip() for n in (notes or "").splitlines() if n.strip()]
    notes_html = "<br/>".join(f"{i}. &nbsp;{t}" for i, t in enumerate(note_lines, 1)) or "—"
    note_para = Paragraph(notes_html, small)

    tot: list[tuple[str, str]] = [("SUB TOTAL", _idr_plain(subtotal))]
    if discount:
        tot.append(("DISKON", "-" + _idr_plain(discount)))
    tot.append((f"PPN ({tax_pct:g}%)", _idr_plain(tax)))
    tot.append(("TOTAL", _idr_plain(total)))

    grid = [[note_para, "", tot[0][0], tot[0][1]]]
    for label_txt, amount in tot[1:]:
        grid.append(["", "", label_txt, amount])
    last = len(grid) - 1

    style = [
        ("SPAN", (0, 0), (0, last)),
        ("VALIGN", (0, 0), (0, 0), "TOP"),
        ("BACKGROUND", (0, 0), (0, last), PANEL),
        ("LEFTPADDING", (0, 0), (0, last), 5 * mm),
        ("RIGHTPADDING", (0, 0), (0, last), 5 * mm),
        ("TOPPADDING", (0, 0), (0, last), 4 * mm),
        ("BOTTOMPADDING", (0, 0), (0, last), 4 * mm),
        ("FONT", (2, 0), (-1, last - 1), "Helvetica", 9.4),
        ("ALIGN", (3, 0), (3, last), "RIGHT"),
        ("LEFTPADDING", (2, 0), (2, last), 4 * mm),
        ("RIGHTPADDING", (3, 0), (3, last), 4 * mm),
        ("TOPPADDING", (2, 0), (-1, last - 1), 2.6 * mm),
        ("BOTTOMPADDING", (2, 0), (-1, last - 1), 2.6 * mm),
        ("LINEBELOW", (2, 0), (-1, last - 1), 0.6, RULE),
        # The grand total sits in the navy bar.
        ("BACKGROUND", (2, last), (-1, last), NAVY),
        ("TEXTCOLOR", (2, last), (-1, last), colors.white),
        ("FONT", (2, last), (-1, last), "Helvetica-Bold", 12),
        ("TOPPADDING", (2, last), (-1, last), 4 * mm),
        ("BOTTOMPADDING", (2, last), (-1, last), 4 * mm),
    ]
    keterangan_block = Table(
        [[Paragraph("KETERANGAN", lbl), "", "", ""]] + grid,
        colWidths=[content_w * 0.48, content_w * 0.08,
                   content_w * 0.24, content_w * 0.20],
        style=TableStyle([
            ("LEFTPADDING", (0, 0), (-1, 0), 0),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
        ] + [(a, (c0, r0 + 1), (c1, r1 + 1), *rest)
             for (a, (c0, r0), (c1, r1), *rest) in style]))
    flow.append(KeepTogether(keterangan_block))
    flow.append(Spacer(1, 4 * mm))

    # ── Signature ───────────────────────────────────────────────────────
    sign = [
        [Paragraph("Hormat kami,", body)],
        [Spacer(1, 11 * mm)],
        [Paragraph(signer_name.upper(), body_b)],
        [Paragraph(f"Hp&nbsp;&nbsp;&nbsp;: {signer_phone}", small)],
        [Paragraph(f"Email : {signer_email}", small)],
    ]
    sign_t = Table(sign, colWidths=[62 * mm], hAlign="LEFT")
    sign_t.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ("LINEABOVE", (0, 2), (0, 2), 1.1, INK),
        ("TOPPADDING", (0, 2), (0, 2), 3),
    ]))
    flow.append(KeepTogether(sign_t))

    # BaseDocTemplate takes the page callback from the template, not build().
    doc.build(flow)
    return buf.getvalue()


class _OrangeRule(Spacer):
    """The short orange rule that sits under the PENAWARAN HARGA title."""

    def __init__(self, width: float, thickness: float = 2.0):
        super().__init__(1, thickness + 4)
        self._w = width
        self._t = thickness

    def draw(self):  # noqa: D102
        self.canv.setStrokeColor(ORANGE)
        self.canv.setLineWidth(self._t)
        mid = self._width / 2 if getattr(self, "_width", None) else A4[0] / 2 - MARGIN_X
        self.canv.line(mid - self._w / 2, 2, mid + self._w / 2, 2)

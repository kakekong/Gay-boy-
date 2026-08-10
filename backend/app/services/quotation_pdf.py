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
    # The TE diamond, lifted from the company's own quotation artwork. Swap
    # app/assets/te-logo.png for a higher-resolution original when there is
    # one — this crop is about 100 dpi at the size it prints.
    logo_w, logo_h = 20 * mm, 15 * mm
    if LOGO_PATH.exists():
        canvas.drawImage(str(LOGO_PATH), MARGIN_X, top - logo_h,
                         width=logo_w, height=logo_h,
                         preserveAspectRatio=True, anchor="sw", mask="auto")

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
    # The document's own name, so this chrome can carry other sheets too
    # (the customer-PO confirmation reuses it).
    footer_label = getattr(doc, "footer_label", "PENAWARAN HARGA")
    canvas.drawCentredString(w / 2, fy, " ".join(footer_label))
    canvas.drawRightString(right, fy, f"PAGE {doc.page:02d} / {doc._total_pages:02d}"
                           if getattr(doc, "_total_pages", None) else f"PAGE {doc.page:02d}")
    canvas.restoreState()


def _icon_quality(c, cx, cy, r) -> None:
    """Shield with a tick — quality product."""
    p = c.beginPath()
    p.moveTo(cx - r, cy + r * 0.62)
    p.lineTo(cx + r, cy + r * 0.62)
    p.lineTo(cx + r, cy - r * 0.15)
    p.curveTo(cx + r, cy - r * 0.72, cx + r * 0.45, cy - r * 0.9, cx, cy - r)
    p.curveTo(cx - r * 0.45, cy - r * 0.9, cx - r, cy - r * 0.72, cx - r, cy - r * 0.15)
    p.close()
    c.drawPath(p, fill=0, stroke=1)
    t = c.beginPath()
    t.moveTo(cx - r * 0.42, cy + r * 0.05)
    t.lineTo(cx - r * 0.08, cy - r * 0.32)
    t.lineTo(cx + r * 0.48, cy + r * 0.34)
    c.drawPath(t, fill=0, stroke=1)


def _icon_wrench(c, cx, cy, r) -> None:
    """Open-ended spanner — custom engineering.

    An arc with a deliberate gap reads as a jaw; a straight shaft below it
    reads as the handle. Drawn rather than assembled from rectangles, which
    came out looking like a syringe.
    """
    c.saveState()
    c.translate(cx, cy)
    c.rotate(-40)
    jr = r * 0.44
    base = r * 0.22
    # Jaw: ring left open across the top 80 degrees.
    c.arc(-jr, base, jr, base + 2 * jr, startAng=130, extent=280)
    # Handle.
    c.line(0, base, 0, -r * 0.95)
    c.restoreState()


def _icon_gear(c, cx, cy, r) -> None:
    """Toothed wheel — reliable performance."""
    import math
    teeth = 8
    inner, outer = r * 0.62, r * 0.98
    p = c.beginPath()
    first = True
    for i in range(teeth * 2):
        a0 = (2 * math.pi / (teeth * 2)) * i
        a1 = (2 * math.pi / (teeth * 2)) * (i + 1)
        rad = outer if i % 2 == 0 else inner
        for a in (a0, a1):
            x, y = cx + rad * math.cos(a), cy + rad * math.sin(a)
            if first:
                p.moveTo(x, y); first = False
            else:
                p.lineTo(x, y)
    p.close()
    c.drawPath(p, fill=0, stroke=1)
    c.circle(cx, cy, r * 0.30, fill=0, stroke=1)


def _icon_clock(c, cx, cy, r) -> None:
    """Dial with hands — on-time delivery."""
    c.circle(cx, cy, r * 0.95, fill=0, stroke=1)
    p = c.beginPath()
    p.moveTo(cx, cy + r * 0.52)
    p.lineTo(cx, cy)
    p.lineTo(cx + r * 0.42, cy - r * 0.10)
    c.drawPath(p, fill=0, stroke=1)


_ICONS = (_icon_quality, _icon_wrench, _icon_gear, _icon_clock)


def _capability_row(canvas, doc, y: float) -> None:
    """The four capability marks along the bottom of the sheet — line icon,
    two-line label, and a hairline divider between each group."""
    w = A4[0]
    right = w - MARGIN_X
    span = right - MARGIN_X
    step = span / len(CAPABILITIES)
    canvas.saveState()
    canvas.setLineJoin(1)
    canvas.setLineCap(1)
    for i, (top_word, bottom_word) in enumerate(CAPABILITIES):
        left = MARGIN_X + step * i
        icon_cx = left + step * 0.20
        canvas.setStrokeColor(NAVY)
        canvas.setLineWidth(0.85)
        _ICONS[i](canvas, icon_cx, y + 1.2 * mm, 3.2 * mm)
        text_x = icon_cx + 5.4 * mm
        canvas.setFillColor(NAVY)
        canvas.setFont("Helvetica-Bold", 6.8)
        canvas.drawString(text_x, y + 2.6 * mm, top_word)
        canvas.setFillColor(INK_SOFT)
        canvas.drawString(text_x, y - 1.0 * mm, bottom_word)
        if i:
            canvas.setStrokeColor(RULE)
            canvas.setLineWidth(0.6)
            canvas.line(left - 2 * mm, y - 2.6 * mm, left - 2 * mm, y + 4.6 * mm)
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
                        signer_email: str,
                        signer_signature: bytes | None = None) -> bytes:
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
    # The scan goes in the gap that was always left for a wet signature, and
    # is scaled to this block's shape — 62mm wide, and no taller than the gap
    # it replaces, so the name below never gets pushed off the page.
    from app.services.signature import fitted_flowable
    ink = (fitted_flowable(signer_signature, max_w_mm=58, max_h_mm=11)
           if signer_signature else None)
    sign = [
        [Paragraph("Hormat kami,", body)],
        [ink if ink is not None else Spacer(1, 11 * mm)],
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

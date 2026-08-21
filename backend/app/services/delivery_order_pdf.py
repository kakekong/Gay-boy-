"""The delivery order the driver carries and the customer signs.

Modelled on the sheet PT Transmisi Enjinering has always sent out — the one
that comes back stamped RECEIVED with a date and a signature on it — so the
document generated here is the document people already know:

    To: the customer, with their address and telephone
    Date, and the customer's PO number as the reference
    "Harap diterima barang-barang di bawah ini:"
    No | Description | Qty | Unit Size | Remarks
    TOTAL, in the same unit as the lines
    Prepared by / Sent by / Received by

Two things it deliberately does not carry. **No prices** — it is signed by
whoever is on the gate at a site, and what the customer pays is not their
business. And **no "sent by" or "received by" names**: those two boxes stay
empty on purpose, because they are filled in with a pen by the person who
hands the goods over and the person who takes them.

The Remarks column is where the real destination goes. Head office is on the
letterhead; the goods go to a site, which on the paper sheet was written into
Remarks by hand every time.
"""

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle,
)

from app.services.quotation_pdf import (
    FOOTER_H, HEADER_H, INK, INK_SOFT, MARGIN_X, NAVY, PANEL, RULE,
    _draw_frame_and_chrome, _OrangeRule,
)


class _Doc(BaseDocTemplate):
    footer_label = "SURAT JALAN"


def _draw_draft(canvas, doc) -> None:
    """The letterhead, plus DRAFT struck across the page.

    Drawn for the director deciding whether to release the sheet. It is the
    real document — same lines, same address, same numbers — so the decision
    is made on what would actually print; and it is unmistakably not the
    printed copy, so nobody can hand it to a driver.
    """
    _draw_frame_and_chrome(canvas, doc)
    w, h = A4
    canvas.saveState()
    canvas.translate(w / 2, h / 2)
    canvas.rotate(38)
    canvas.setFont("Helvetica-Bold", 96)
    canvas.setFillColor(colors.Color(0.85, 0.30, 0.10, alpha=0.14))
    canvas.drawCentredString(0, -30, "DRAFT")
    canvas.setFont("Helvetica-Bold", 14)
    canvas.setFillColor(colors.Color(0.85, 0.30, 0.10, alpha=0.30))
    canvas.drawCentredString(0, -56, "BELUM DISETUJUI — NOT YET APPROVED")
    canvas.restoreState()


def build_delivery_order_pdf(
    *, number: str, do_date: str, customer_name: str, customer_address: str,
    customer_phone: str | None, customer_fax: str | None,
    po_number: str | None, project_code: str | None,
    rows: list[dict], remarks: str | None,
    courier: str | None, tracking_no: str | None,
    prepared_by: str, preparer_signature: bytes | None = None,
    draft: bool = False,
) -> bytes:
    buf = BytesIO()
    doc = _Doc(
        buf, pagesize=A4,
        leftMargin=MARGIN_X, rightMargin=MARGIN_X,
        topMargin=18 * mm + HEADER_H - 18 * mm, bottomMargin=FOOTER_H + 14 * mm,
        title=("DRAFT — " if draft else "") + f"Surat Jalan {number}",
    )
    content_w = A4[0] - 2 * MARGIN_X
    frame = Frame(
        MARGIN_X, FOOTER_H + 14 * mm, content_w,
        A4[1] - (18 * mm + 30 * mm) - (FOOTER_H + 14 * mm),
        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
    )
    doc.addPageTemplates([
        PageTemplate(id="sheet", frames=[frame],
                     onPage=(_draw_draft if draft else _draw_frame_and_chrome)),
    ])

    title = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=21,
                           textColor=NAVY, alignment=1, leading=24)
    lbl = ParagraphStyle("lbl", fontName="Helvetica-Bold", fontSize=8.6,
                         textColor=NAVY, spaceAfter=3)
    body = ParagraphStyle("body", fontName="Helvetica", fontSize=8.4,
                          textColor=INK, leading=12)
    panel_body = ParagraphStyle("panel", parent=body, fontSize=8.6, leading=13)
    cell = ParagraphStyle("cell", parent=body, fontSize=7.6, leading=10.4)
    small = ParagraphStyle("small", parent=body, fontSize=7.2, leading=10.4,
                           textColor=INK_SOFT)

    def panel_pair(l_title, l_html, r_title, r_html):
        """Two flat grey panels. Never nest a table in a cell — reportlab
        computes an unbounded row height for that and aborts."""
        return Table(
            [[Paragraph(l_title, lbl), "", Paragraph(r_title, lbl)],
             [Paragraph(l_html, panel_body), "", Paragraph(r_html, panel_body)]],
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
                ("TOPPADDING", (0, 1), (-1, 1), 4 * mm),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 4 * mm),
            ]),
        )

    flow: list = []
    flow.append(Paragraph("SURAT JALAN", title))
    flow.append(Paragraph(
        '<font size="9" color="#55585E">DELIVERY ORDER</font>',
        ParagraphStyle("sub", parent=body, alignment=1)))
    flow.append(_OrangeRule(width=40 * mm, thickness=2.2))
    flow.append(Spacer(1, 5 * mm))

    to_html = f"<b>{(customer_name or '—').upper()}</b>"
    if (customer_address or "").strip():
        to_html += "<br/>" + customer_address.strip().replace("\n", "<br/>")
    if customer_phone:
        to_html += f'<br/><font color="#55585E">TELP</font> : {customer_phone}'
    if customer_fax:
        to_html += f'<br/><font color="#55585E">FAX</font>&nbsp;&nbsp; : {customer_fax}'

    meta = (f'<font color="#55585E">NO. SJ</font>&nbsp;&nbsp;&nbsp;:&nbsp;&nbsp;'
            f"<b>{number}</b>"
            f'<br/><font color="#55585E">TANGGAL</font>&nbsp;:&nbsp;&nbsp;{do_date}')
    if po_number:
        meta += (f'<br/><font color="#55585E">REF/PO</font>&nbsp;:&nbsp;&nbsp;'
                 f"{po_number}")
    if project_code:
        meta += (f'<br/><font color="#55585E">PROYEK</font>&nbsp;&nbsp;:&nbsp;&nbsp;'
                 f"{project_code}")
    flow.append(panel_pair("KEPADA", to_html, "INFORMASI PENGIRIMAN", meta))
    flow.append(Spacer(1, 4 * mm))

    flow.append(Paragraph(
        "<i>Harap diterima barang-barang di bawah ini:</i>", body))
    flow.append(Spacer(1, 2.5 * mm))

    head = ["NO", "DESCRIPTION", "QTY", "UNIT SIZE", "REMARKS"]
    data = [[Paragraph(f'<font color="#FFFFFF"><b>{h}</b></font>', cell) for h in head]]
    total_qty = 0.0
    units = set()
    for i, r in enumerate(rows, 1):
        qty = float(r.get("qty") or 0)
        uom = (r.get("uom") or "EA").strip() or "EA"
        total_qty += qty
        units.add(uom.upper())
        data.append([
            Paragraph(str(i), cell),
            Paragraph(str(r.get("description") or "—"), cell),
            Paragraph(f"{qty:g}", cell),
            Paragraph(uom, cell),
            # The destination rides on the first line, the way it was always
            # written on the paper sheet — one block against the goods, not
            # repeated down the page.
            Paragraph((remarks or "").strip().replace("\n", "<br/>"), cell)
            if i == 1 else Paragraph("", cell),
        ])
    col_w = [content_w * 0.06, content_w * 0.42, content_w * 0.09,
             content_w * 0.11, content_w * 0.32]
    flow.append(Table(data, colWidths=col_w, repeatRows=1, style=TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.4, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (2, 0), (3, -1), "CENTER"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 1.9 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.9 * mm),
        ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
    ])))

    # One unit across the sheet totals cleanly; a mixed sheet does not, and
    # saying "8" over metres and pieces together would be a lie in a box.
    unit_label = next(iter(units)) if len(units) == 1 else ""
    flow.append(Table(
        [["", Paragraph("<b>TOTAL</b>", cell),
          Paragraph(f"<b>{total_qty:g}</b>", cell),
          Paragraph(f"<b>{unit_label}</b>", cell), ""]],
        colWidths=col_w,
        style=TableStyle([
            ("BACKGROUND", (1, 0), (3, 0), PANEL),
            ("GRID", (1, 0), (3, 0), 0.4, RULE),
            ("ALIGN", (2, 0), (3, 0), "CENTER"),
            ("TOPPADDING", (0, 0), (-1, -1), 2.2 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2 * mm),
            ("LEFTPADDING", (1, 0), (-1, -1), 2 * mm),
            ("RIGHTPADDING", (1, 0), (-1, -1), 2 * mm),
        ]),
    ))

    if courier or tracking_no:
        bits = []
        if courier:
            bits.append(f'<font color="#55585E">EKSPEDISI</font> : {courier}')
        if tracking_no:
            bits.append(f'<font color="#55585E">NO. RESI</font> : {tracking_no}')
        flow.append(Spacer(1, 3 * mm))
        flow.append(Paragraph("&nbsp;&nbsp;&nbsp;".join(bits), small))
    flow.append(Spacer(1, 8 * mm))

    # Three boxes, and only the first one is ours to fill. The other two are
    # signed with a pen at the loading bay and at the gate.
    from app.services.signature import fitted_flowable
    box_w = content_w * 0.30
    _ink = (fitted_flowable(preparer_signature, max_w_mm=box_w / mm, max_h_mm=14)
            if preparer_signature else None)
    sign_row = Table(
        [[Paragraph("Prepared by,", small), "",
          Paragraph("Sent by,", small), "",
          Paragraph("Received by,", small)],
         [_ink if _ink is not None else Spacer(1, 14 * mm), "",
          Spacer(1, 14 * mm), "", Spacer(1, 14 * mm)],
         [Paragraph(f"<b>{prepared_by or '—'}</b>", body), "",
          Paragraph("&nbsp;", body), "", Paragraph("&nbsp;", body)],
         [Paragraph("PT. Transmisi Enjinering", small), "",
          Paragraph('<font color="#55585E">Nama &amp; tanda tangan</font>', small), "",
          Paragraph('<font color="#55585E">Nama, tanggal &amp; cap</font>', small)]],
        colWidths=[box_w, content_w * 0.05, box_w, content_w * 0.05, box_w],
        style=TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
            ("LINEBELOW", (0, 1), (0, 1), 0.5, colors.HexColor("#9AA0A8")),
            ("LINEBELOW", (2, 1), (2, 1), 0.5, colors.HexColor("#9AA0A8")),
            ("LINEBELOW", (4, 1), (4, 1), 0.5, colors.HexColor("#9AA0A8")),
        ]),
    )
    flow.append(sign_row)

    doc.build(flow)
    return buf.getvalue()

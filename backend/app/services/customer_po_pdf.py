"""Order confirmation sheet for a customer PO.

Printed on the same letterhead as the quotation, so the paperwork a customer
receives from us looks like one set of documents rather than three.

Two things on this sheet are chosen at download time rather than stored on the
PO, because they are decisions about *this* shipment:

* **Where it ships.** The customer's office and their delivery address are
  routinely different — the order goes to a site, the invoice goes to head
  office — so the person printing picks which one belongs on the sheet.
* **Who is in charge.** Which PIC owns this specific order. That is the
  customer's own contact list, so any of their contacts can be named, not just
  whoever happens to be the primary on the customer record.
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
    _draw_frame_and_chrome, _idr_plain, _OrangeRule,
)


class _Doc(BaseDocTemplate):
    """Same letterhead as the quotation; only the footer word differs."""

    footer_label = "KONFIRMASI PESANAN"


def build_customer_po_pdf(
    *, number: str, po_date: str, customer_name: str, ship_to_label: str,
    ship_to_address: str, pic_name: str, pic_position: str, pic_phone: str,
    pic_email: str, quotation_number: str | None, rows: list[dict],
    total: float, keterangan: str | None, sales_pic: str,
) -> bytes:
    buf = BytesIO()
    doc = _Doc(
        buf, pagesize=A4,
        leftMargin=MARGIN_X, rightMargin=MARGIN_X,
        topMargin=18 * mm + HEADER_H - 18 * mm, bottomMargin=FOOTER_H + 14 * mm,
        title=f"Konfirmasi Pesanan {number}",
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
        """Two side-by-side grey panels — flat, never nested.

        A table whose cell contains another table of Paragraphs makes reportlab
        compute an unbounded row height and abort, so both panels are single
        Paragraphs in one flat table.
        """
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
    flow.append(Paragraph("KONFIRMASI PESANAN", title))
    flow.append(_OrangeRule(width=40 * mm, thickness=2.2))
    flow.append(Spacer(1, 5 * mm))

    ref = (f'<br/><font color="#55585E">REF</font>'
           f"&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;:&nbsp;&nbsp;{quotation_number}"
           if quotation_number else "")
    flow.append(panel_pair(
        "PELANGGAN",
        f"<b>{customer_name.upper()}</b>",
        "INFORMASI PESANAN",
        f'<font color="#55585E">NO. PO</font>&nbsp;&nbsp;:&nbsp;&nbsp;<b>{number}</b>'
        f'<br/><font color="#55585E">TANGGAL</font>&nbsp;:&nbsp;&nbsp;{po_date}{ref}',
    ))
    flow.append(Spacer(1, 4 * mm))

    # The two per-shipment choices, side by side and clearly labelled — the
    # whole reason this sheet takes options.
    pic_html = f"<b>{pic_name or '—'}</b>"
    if pic_position:
        pic_html += f'<br/><font color="#55585E">{pic_position}</font>'
    if pic_phone:
        pic_html += f'<br/><font color="#55585E">Telp</font>&nbsp;&nbsp;: {pic_phone}'
    if pic_email:
        pic_html += f'<br/><font color="#55585E">Email</font> : {pic_email}'

    flow.append(panel_pair(
        f"KIRIM KE — {ship_to_label.upper()}",
        (ship_to_address or "—").replace("\n", "<br/>"),
        "PIC PESANAN INI",
        pic_html,
    ))
    flow.append(Spacer(1, 5 * mm))

    # ── Items ────────────────────────────────────────────────────────────
    head = ["NO", "NAMA BARANG", "QTY", "HARGA SATUAN", "JUMLAH"]
    data = [[Paragraph(f'<font color="#FFFFFF"><b>{h}</b></font>', cell) for h in head]]
    for i, r in enumerate(rows, 1):
        qty = float(r.get("qty") or 0)
        unit = float(r.get("unit_price") or 0)
        data.append([
            Paragraph(str(i), cell),
            Paragraph(str(r.get("description") or "—"), cell),
            Paragraph(f"{qty:g} {r.get('uom') or ''}".strip(), cell),
            Paragraph(_idr_plain(unit), cell),
            Paragraph(_idr_plain(qty * unit), cell),
        ])
    col_w = [content_w * 0.06, content_w * 0.46, content_w * 0.12,
             content_w * 0.18, content_w * 0.18]
    flow.append(Table(data, colWidths=col_w, repeatRows=1, style=TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.4, RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 1.9 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.9 * mm),
        ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
    ])))

    flow.append(Table(
        [["", Paragraph('<b>TOTAL</b>', cell),
          Paragraph(f"<b>{_idr_plain(total)}</b>", cell)]],
        colWidths=[content_w * 0.64, content_w * 0.18, content_w * 0.18],
        style=TableStyle([
            ("BACKGROUND", (1, 0), (-1, 0), PANEL),
            ("GRID", (1, 0), (-1, 0), 0.4, RULE),
            ("ALIGN", (2, 0), (2, 0), "RIGHT"),
            ("TOPPADDING", (0, 0), (-1, -1), 2.2 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2 * mm),
            ("LEFTPADDING", (1, 0), (-1, -1), 2 * mm),
            ("RIGHTPADDING", (1, 0), (-1, -1), 2 * mm),
        ]),
    ))
    flow.append(Spacer(1, 5 * mm))

    if (keterangan or "").strip():
        flow.append(Paragraph("KETERANGAN", lbl))
        flow.append(Table(
            [[Paragraph(keterangan.strip().replace("\n", "<br/>"), panel_body)]],
            colWidths=[content_w],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), PANEL),
                ("LEFTPADDING", (0, 0), (-1, -1), 5 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 3.5 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5 * mm),
            ]),
        ))
        flow.append(Spacer(1, 6 * mm))

    flow.append(Table(
        [[Paragraph("Hormat kami,", small)],
         [Spacer(1, 16 * mm)],
         [Paragraph(f"<b>{sales_pic or '—'}</b>", body)],
         [Paragraph("PT. Transmisi Enjinering", small)]],
        colWidths=[content_w * 0.42], hAlign="LEFT",
        style=TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ("LINEBELOW", (0, 1), (0, 1), 0.5, colors.HexColor("#9AA0A8")),
        ]),
    ))

    doc.build(flow)
    return buf.getvalue()

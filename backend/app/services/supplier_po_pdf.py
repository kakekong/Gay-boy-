"""The purchase order we send a supplier.

Same letterhead as everything else that leaves this company, because a vendor
receiving our order and our order confirmation should be looking at one set of
documents. What differs from the customer-facing sheets is who it is addressed
to and which of their addresses matters: the goods are *collected from* the
supplier, so the panel carries their warehouse address when they have one, and
their office address when they don't.

It also carries the ship-to — our own warehouse or, on a drop-ship, wherever
the goods are actually going — because a PO that does not say where to deliver
is a phone call waiting to happen.

**This one document is in English, and the quotation is not.** Everything
customer-facing is Indonesian because the customers are. Suppliers are not: the
chain comes from Jiangsu, and a purchase order headed KEPADA — PEMASOK with
its quantities under NAMA BARANG is a document the person filling the order
cannot read. Nothing here should be translated back.

**Money always carries its currency.** The columns say which, and the total
repeats it. A vendor in China quoting USD and reading `1.800.000` as their own
number is the mistake this exists to prevent — so the formatting follows the
currency too, dots for rupiah and a decimal point for everything else.
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
    footer_label = "PURCHASE ORDER"


def money(amount, currency: str) -> str:
    """A figure written the way its own currency is written.

    Rupiah has no minor unit in practice and groups with dots — 1.800.000.
    Everything else groups with commas and keeps two decimals — 1,800.00. Using
    the Indonesian form for a dollar price turns 1,800.00 into 1.800.000, which
    is three orders of magnitude of argument with a vendor.
    """
    amount = float(amount or 0)
    sign = "-" if amount < 0 else ""
    if (currency or "IDR").upper() == "IDR":
        return sign + f"{abs(amount):,.0f}".replace(",", ".")
    return sign + f"{abs(amount):,.2f}"


def build_supplier_po_pdf(
    *, number: str, po_date: str, supplier_name: str, supplier_address: str,
    supplier_pic: str, supplier_phone: str, supplier_email: str,
    ship_to_label: str, ship_to_address: str,
    project_code: str | None, lead_days: int | None,
    rows: list[dict], total: float, notes: str | None,
    issued_by: str, issuer_signature: bytes | None = None,
    currency: str = "IDR",
) -> bytes:
    buf = BytesIO()
    doc = _Doc(
        buf, pagesize=A4,
        leftMargin=MARGIN_X, rightMargin=MARGIN_X,
        topMargin=18 * mm + HEADER_H - 18 * mm, bottomMargin=FOOTER_H + 14 * mm,
        title=f"Purchase Order {number}",
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
        """Two flat grey panels. Never nest a table in a cell here — reportlab
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
    flow.append(Paragraph("PURCHASE ORDER", title))
    flow.append(_OrangeRule(width=40 * mm, thickness=2.2))
    flow.append(Spacer(1, 5 * mm))

    cur = (currency or "IDR").upper()

    sup_html = f"<b>{supplier_name.upper()}</b>"
    if supplier_address:
        sup_html += "<br/>" + supplier_address.replace("\n", "<br/>")
    if supplier_pic:
        sup_html += f'<br/><font color="#55585E">Attn</font>&nbsp;&nbsp;: {supplier_pic}'
    if supplier_phone:
        sup_html += f'<br/><font color="#55585E">Phone</font> : {supplier_phone}'
    if supplier_email:
        sup_html += f'<br/><font color="#55585E">Email</font> : {supplier_email}'

    info = (f'<font color="#55585E">PO NO.</font>&nbsp;&nbsp;&nbsp;&nbsp;:&nbsp;&nbsp;<b>{number}</b>'
            f'<br/><font color="#55585E">DATE</font>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;:&nbsp;&nbsp;{po_date}'
            f'<br/><font color="#55585E">CURRENCY</font>&nbsp;&nbsp;:&nbsp;&nbsp;<b>{cur}</b>')
    if project_code:
        info += (f'<br/><font color="#55585E">PROJECT</font>&nbsp;&nbsp;&nbsp;'
                 f':&nbsp;&nbsp;{project_code}')
    if lead_days is not None:
        info += (f'<br/><font color="#55585E">LEAD TIME</font>&nbsp;'
                 f':&nbsp;&nbsp;{lead_days} days')

    flow.append(panel_pair("TO — SUPPLIER", sup_html, "PO DETAILS", info))
    flow.append(Spacer(1, 4 * mm))
    flow.append(panel_pair(
        f"SHIP TO — {ship_to_label.upper()}",
        (ship_to_address or "—").replace("\n", "<br/>"),
        "TERMS",
        f"All prices are in <b>{cur}</b>, inclusive of tax as agreed.<br/>"
        "Please quote this PO number on your delivery note and invoice.",
    ))
    flow.append(Spacer(1, 5 * mm))

    head = ["NO", "DESCRIPTION", "QTY", f"UNIT PRICE ({cur})", f"AMOUNT ({cur})"]
    data = [[Paragraph(f'<font color="#FFFFFF"><b>{h}</b></font>', cell) for h in head]]
    for i, r in enumerate(rows, 1):
        qty = float(r.get("qty") or 0)
        unit = float(r.get("unit_price") or 0)
        data.append([
            Paragraph(str(i), cell),
            Paragraph(str(r.get("description") or "—"), cell),
            Paragraph(f"{qty:g} {r.get('uom') or ''}".strip(), cell),
            Paragraph(money(unit, cur), cell),
            Paragraph(money(float(r.get("amount") or qty * unit), cur), cell),
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
        # The total repeats the currency rather than relying on the column
        # header above it — this is the line a vendor's finance office reads.
        [["", Paragraph(f"<b>TOTAL {cur}</b>", cell),
          Paragraph(f"<b>{money(total, cur)}</b>", cell)]],
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

    if (notes or "").strip():
        flow.append(Paragraph("NOTES", lbl))
        flow.append(Table(
            [[Paragraph(notes.strip().replace("\n", "<br/>"), panel_body)]],
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

    from app.services.signature import fitted_flowable
    _ink = (fitted_flowable(issuer_signature, max_w_mm=(content_w * 0.40) / mm,
                            max_h_mm=16)
            if issuer_signature else None)
    flow.append(Table(
        [[Paragraph("Yours sincerely,", small)],
         [_ink if _ink is not None else Spacer(1, 16 * mm)],
         [Paragraph(f"<b>{issued_by or '—'}</b>", body)],
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

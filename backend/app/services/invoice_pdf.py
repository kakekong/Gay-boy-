"""The invoice the customer is asked to pay.

Modelled on the sheet PT Transmisi Enjinering already sends — the one headed
PERFORMA INVOICE with the BCA account printed under the lines:

    Kepada Yth / Alamat
    Jakarta, <date> and the customer's order number
    Banyaknya | Nama Barang | Harga Satuan | Jumlah
    Sub Bruto / PPn / Sub Total
    the bank account to transfer to, and "Hormat kami"

Two decisions worth stating.

**The lines are the customer's own order, not a re-derivation.** They come
off the customer's PO where there is one — same words, same quantities — so
the invoice can be checked against the order without translation.

**The lines are only printed when they add up to what is being billed.** An
invoice's amount can be corrected after issue (a revised quantity, tax the
customer is exempt from), and once it has been, the order lines no longer
explain the figure. Printing them anyway would produce a sheet whose middle
contradicts its total, so when they disagree the sheet states the job as one
line at the invoiced amount instead. A document that adds up is worth more
than a document with detail in it.

The faktur pajak number goes on when finance signs off, and prints here
because that is the number the customer's tax people will ask for.
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
    footer_label = "INVOICE"


# How far the lines may drift from the invoiced amount before they stop
# explaining it. Rupiah, so a hundred covers rounding on a tax split without
# covering an actual edit.
_TOLERANCE = 100.0


def lines_explain_total(rows: list[dict], amount: float) -> bool:
    """Whether these order lines still add up to what is being billed."""
    total = sum(float(r.get("qty") or 0) * float(r.get("unit_price") or 0)
                for r in rows)
    return abs(total - float(amount or 0)) <= _TOLERANCE


def build_invoice_pdf(
    *, number: str, issue_date: str, due_date: str | None,
    customer_name: str, customer_address: str,
    order_number: str | None, project_code: str | None,
    invoice_type: str, rows: list[dict],
    amount: float, tax_amount: float, total: float,
    faktur_pajak_no: str | None,
    bank_name: str, bank_account_no: str, bank_account_name: str,
    bank_branch: str,
    issued_by: str, issuer_signature: bytes | None = None,
) -> bytes:
    buf = BytesIO()
    doc = _Doc(
        buf, pagesize=A4,
        leftMargin=MARGIN_X, rightMargin=MARGIN_X,
        topMargin=18 * mm + HEADER_H - 18 * mm, bottomMargin=FOOTER_H + 14 * mm,
        title=f"Invoice {number}",
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

    kind = (invoice_type or "final").lower()
    heading = "INVOICE UANG MUKA" if kind == "dp" else "INVOICE"

    flow: list = []
    flow.append(Paragraph(heading, title))
    flow.append(_OrangeRule(width=40 * mm, thickness=2.2))
    flow.append(Spacer(1, 5 * mm))

    to_html = f"<b>{(customer_name or '—').upper()}</b>"
    if (customer_address or "").strip():
        to_html += "<br/>" + customer_address.strip().replace("\n", "<br/>")

    meta = (f'<font color="#55585E">NO.</font>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;'
            f'&nbsp;:&nbsp;&nbsp;<b>{number}</b>'
            f'<br/><font color="#55585E">TANGGAL</font>&nbsp;:&nbsp;&nbsp;{issue_date}')
    if due_date:
        meta += (f'<br/><font color="#55585E">JATUH TEMPO</font>&nbsp;:&nbsp;&nbsp;'
                 f"{due_date}")
    if order_number:
        meta += (f'<br/><font color="#55585E">NO. ORDER</font>&nbsp;:&nbsp;&nbsp;'
                 f"{order_number}")
    if project_code:
        meta += (f'<br/><font color="#55585E">PROYEK</font>&nbsp;&nbsp;&nbsp;:&nbsp;&nbsp;'
                 f"{project_code}")
    if faktur_pajak_no:
        meta += (f'<br/><font color="#55585E">FAKTUR PAJAK</font>&nbsp;:&nbsp;&nbsp;'
                 f"{faktur_pajak_no}")
    flow.append(panel_pair("KEPADA YTH", to_html, "INFORMASI INVOICE", meta))
    flow.append(Spacer(1, 5 * mm))

    printable = [r for r in (rows or [])
                 if float(r.get("qty") or 0) or float(r.get("unit_price") or 0)]
    if kind == "dp" or not printable or not lines_explain_total(printable, amount):
        printable = [{
            "description": ("Uang muka pekerjaan" if kind == "dp"
                            else (f"Pekerjaan {project_code}" if project_code
                                  else "Pekerjaan sesuai pesanan")),
            "qty": 1, "uom": "LOT", "unit_price": float(amount or 0),
        }]

    head = ["BANYAKNYA", "NAMA BARANG", "HARGA SATUAN", "JUMLAH"]
    data = [[Paragraph(f'<font color="#FFFFFF"><b>{h}</b></font>', cell) for h in head]]
    for r in printable:
        qty = float(r.get("qty") or 0)
        unit = float(r.get("unit_price") or 0)
        data.append([
            Paragraph(f"{qty:g} {(r.get('uom') or 'PCS').upper()}", cell),
            Paragraph(str(r.get("description") or "—"), cell),
            Paragraph(_idr_plain(unit), cell),
            Paragraph(_idr_plain(qty * unit), cell),
        ])
    col_w = [content_w * 0.13, content_w * 0.47, content_w * 0.20, content_w * 0.20]
    flow.append(Table(data, colWidths=col_w, repeatRows=1, style=TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.4, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 1.9 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.9 * mm),
        ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
    ])))

    def money_row(label, value, bold=False):
        text = f"<b>{label}</b>" if bold else label
        figure = f"<b>{_idr_plain(value)}</b>" if bold else _idr_plain(value)
        return [Paragraph(text, cell), Paragraph(figure, cell)]

    flow.append(Table(
        [[""] + money_row("SUB BRUTO", amount),
         [""] + money_row("PPN", tax_amount),
         [""] + money_row("SUB TOTAL", total, bold=True)],
        colWidths=[content_w * 0.60, content_w * 0.20, content_w * 0.20],
        style=TableStyle([
            ("BACKGROUND", (1, 0), (-1, -1), PANEL),
            ("GRID", (1, 0), (-1, -1), 0.4, RULE),
            ("ALIGN", (2, 0), (2, -1), "RIGHT"),
            ("TOPPADDING", (0, 0), (-1, -1), 1.8 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1.8 * mm),
            ("LEFTPADDING", (1, 0), (-1, -1), 2 * mm),
            ("RIGHTPADDING", (1, 0), (-1, -1), 2 * mm),
        ]),
    ))
    flow.append(Spacer(1, 6 * mm))

    # Where the money goes, and who is asking for it — side by side, the way
    # the sheet has always been laid out.
    from app.services.signature import fitted_flowable
    bank_html = ""
    if bank_account_no:
        bank_html = (
            "<font color=\"#55585E\">Pembayaran dapat ditransfer ke:</font>"
            f'<br/><font color="#55585E">A/C</font>&nbsp;&nbsp;&nbsp;:&nbsp;&nbsp;'
            f"<b>{bank_account_no}</b>"
            f'<br/><font color="#55585E">A/N</font>&nbsp;&nbsp;&nbsp;:&nbsp;&nbsp;'
            f"{bank_account_name}"
            f'<br/><font color="#55585E">BANK</font>&nbsp;:&nbsp;&nbsp;'
            f"{bank_name}" + (f" — {bank_branch}" if bank_branch else "")
        )
    else:
        bank_html = ('<font color="#55585E">— rekening pembayaran belum diatur —'
                     "</font>")

    _ink = (fitted_flowable(issuer_signature, max_w_mm=(content_w * 0.34) / mm,
                            max_h_mm=15)
            if issuer_signature else None)
    flow.append(Table(
        [[Paragraph(bank_html, panel_body), "", Paragraph("Hormat kami,", small)],
         ["", "", _ink if _ink is not None else Spacer(1, 15 * mm)],
         ["", "", Paragraph(f"<b>{issued_by or '—'}</b>", body)],
         ["", "", Paragraph("PT. Transmisi Enjinering", small)]],
        colWidths=[content_w * 0.52, content_w * 0.14, content_w * 0.34],
        style=TableStyle([
            ("SPAN", (0, 0), (0, 3)),
            ("VALIGN", (0, 0), (0, 0), "TOP"),
            ("BACKGROUND", (0, 0), (0, 3), PANEL),
            ("LEFTPADDING", (0, 0), (0, -1), 5 * mm),
            ("RIGHTPADDING", (0, 0), (0, -1), 5 * mm),
            ("TOPPADDING", (0, 0), (0, -1), 4 * mm),
            ("BOTTOMPADDING", (0, 0), (0, -1), 4 * mm),
            ("LEFTPADDING", (1, 0), (-1, -1), 0),
            ("RIGHTPADDING", (1, 0), (-1, -1), 0),
            ("TOPPADDING", (1, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (1, 0), (-1, -1), 0),
            ("LINEBELOW", (2, 1), (2, 1), 0.5, colors.HexColor("#9AA0A8")),
        ]),
    ))

    doc.build(flow)
    return buf.getvalue()

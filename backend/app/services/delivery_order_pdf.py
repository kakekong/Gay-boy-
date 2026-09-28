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
Remarks by hand every time. The address the sheet is made out to is the one
picked when it was raised (site, office, tax address, or typed), and the
part code prints in front of each description.

**Page two is the Surat Jalan Ekspedisi** — the letter the expedition
company carries: "mohon kirimkan barang kami sebanyak N peti", one row per
peti with what is in it and the customer's PO number, the consignee with
their U/P, three signature boxes (us, the expedition, the receiver), and the
note asking for the signed white copy back at the office.
"""

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageBreak, PageTemplate, Paragraph, Spacer, Table,
    TableStyle,
)

from app.services.quotation_pdf import (
    FOOTER_H, HEADER_H, INK, INK_SOFT, MARGIN_X, NAVY, PANEL, RULE,
    _draw_frame_and_chrome, _OrangeRule,
)


class _Doc(BaseDocTemplate):
    footer_label = "SURAT JALAN"


_ONES = ["", "SATU", "DUA", "TIGA", "EMPAT", "LIMA", "ENAM", "TUJUH",
         "DELAPAN", "SEMBILAN", "SEPULUH", "SEBELAS"]


def terbilang(n: int) -> str:
    """A small whole number in Indonesian words, as the letter writes it."""
    n = int(n)
    if n < 12:
        return _ONES[n] or "NOL"
    if n < 20:
        return f"{_ONES[n - 10]} BELAS"
    if n < 100:
        tens, ones = divmod(n, 10)
        return f"{_ONES[tens]} PULUH" + (f" {_ONES[ones]}" if ones else "")
    if n < 200:
        return "SERATUS" + (f" {terbilang(n - 100)}" if n - 100 else "")
    if n < 1000:
        h, r = divmod(n, 100)
        return f"{_ONES[h]} RATUS" + (f" {terbilang(r)}" if r else "")
    return str(n)


def default_packages(rows: list[dict], po_number: str | None) -> list[dict]:
    """One peti per line when nobody listed the packages by hand."""
    out = []
    for i, r in enumerate(rows, 1):
        qty = float(r.get("qty") or 0)
        uom = (r.get("uom") or "").upper()
        name = " ".join(x for x in (r.get("sku"), r.get("description")) if x)
        out.append({"label": f"PETI {i}", "description": name,
                    "qty": f"{qty:g} {uom}".strip(),
                    "note": f"PO NO: {po_number}" if po_number else None})
    return out


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
    attention: str | None = None,
    packages: list[dict] | None = None,
    return_note: str | None = None,
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
    if attention:
        to_html += f'<br/><font color="#55585E">U/P</font> : {attention}'
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
            # The part code first, then the name — "IPK301494 CHAIN FEEDER …",
            # the way the company's own sheets write it.
            Paragraph(" ".join(x for x in (r.get("sku"), r.get("description") or "—")
                               if x), cell),
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

    # ══ Page two: the Surat Jalan Ekspedisi ═════════════════════════════════
    pkgs = [p for p in (packages or []) if (p.get("description") or p.get("qty"))]
    if not pkgs:
        pkgs = default_packages(rows, po_number)
    flow.append(PageBreak())
    flow.append(Paragraph("SURAT JALAN EKSPEDISI", title))
    flow.append(Paragraph(
        f'<font size="9" color="#55585E">{number}</font>',
        ParagraphStyle("sub2", parent=body, alignment=1)))
    flow.append(_OrangeRule(width=40 * mm, thickness=2.2))
    flow.append(Spacer(1, 4 * mm))
    flow.append(Paragraph(f"JAKARTA, {do_date.upper()}",
                          ParagraphStyle("date", parent=body, alignment=2)))
    flow.append(Spacer(1, 3 * mm))
    flow.append(Paragraph("KEPADA YTH :", body))
    flow.append(Paragraph(f"<b>{(courier or 'EKSPEDISI ..........................').upper()}</b>",
                          body))
    flow.append(Spacer(1, 4 * mm))
    n = len(pkgs)
    flow.append(Paragraph(
        f"MOHON KIRIMKAN BARANG KAMI SEBANYAK : <b>{n} ({terbilang(n)}) PETI</b> "
        "SEBAGAI BERIKUT :", body))
    flow.append(Spacer(1, 2.5 * mm))
    ehead = ["PETI NO", "NAMA BARANG", "QTY", "KETERANGAN"]
    edata = [[Paragraph(f'<font color="#FFFFFF"><b>{h}</b></font>', cell) for h in ehead]]
    for i, pk in enumerate(pkgs, 1):
        edata.append([
            Paragraph(pk.get("label") or f"PETI {i}", cell),
            Paragraph(str(pk.get("description") or "—"), cell),
            Paragraph(str(pk.get("qty") or ""), cell),
            Paragraph(str(pk.get("note") or (f"PO NO: {po_number}" if po_number else "")),
                      cell),
        ])
    flow.append(Table(edata, colWidths=[content_w * 0.11, content_w * 0.45,
                                        content_w * 0.18, content_w * 0.26],
                      repeatRows=1, style=TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.4, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 1.6 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6 * mm),
        ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
    ])))
    flow.append(Spacer(1, 5 * mm))
    consignee = f"<b>KEPADA :</b><br/><b>{(customer_name or '—').upper()}</b>"
    if (customer_address or "").strip():
        consignee += "<br/>" + customer_address.strip().replace("\n", "<br/>")
    if attention:
        consignee += f"<br/><b>U/P : {attention.upper()}</b>"
    flow.append(Paragraph(consignee, body))
    flow.append(Spacer(1, 5 * mm))
    flow.append(Paragraph("TERIMA KASIH ATAS PERHATIAN DAN KERJA SAMANYA.", body))
    flow.append(Spacer(1, 6 * mm))
    e_ink = (fitted_flowable(preparer_signature, max_w_mm=box_w / mm, max_h_mm=14)
             if preparer_signature else None)
    flow.append(Table(
        [[Paragraph("Hormat kami,", small), "",
          Paragraph("Diterima oleh,", small), "",
          Paragraph("Penerima barang,", small)],
         [e_ink if e_ink is not None else Spacer(1, 14 * mm), "",
          Spacer(1, 14 * mm), "", Spacer(1, 14 * mm)],
         [Paragraph(f"<b>{prepared_by or '—'}</b>", body), "",
          Paragraph("&nbsp;", body), "", Paragraph("&nbsp;", body)],
         [Paragraph("PT. Transmisi Enjinering", small), "",
          Paragraph(f'<font color="#55585E">{(courier or "Ekspedisi")}</font>', small), "",
          Paragraph(f'<font color="#55585E">{(customer_name or "")}</font>', small)]],
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
    ))
    if return_note:
        flow.append(Spacer(1, 6 * mm))
        flow.append(Paragraph(f"<b>NB :</b> {return_note}", small))

    doc.build(flow)
    return buf.getvalue()

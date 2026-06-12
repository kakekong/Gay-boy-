"""Generic PDF / Excel export for tabular data (reports + KPIs).

A 'section' is a titled table:
    {"name": "P&L", "headers": ["Metric", "Value"], "rows": [["Revenue", "Rp 1.000.000"], ...]}

Both renderers take a document title + a list of sections and return raw
bytes. Used by the Reports and KPI export endpoints so they share one
consistent layout (mirrors the quotation export styling).
"""

from datetime import UTC, datetime
from io import BytesIO


def _fmt_cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        # Whole numbers render without trailing .0
        return f"{v:,.2f}".rstrip("0").rstrip(".") if v % 1 else f"{int(v):,}"
    return str(v)


def render_pdf(title: str, sections: list[dict]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    )

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=14 * mm, rightMargin=14 * mm,
        topMargin=14 * mm, bottomMargin=14 * mm,
        title=title,
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Title"], fontSize=18, alignment=0)
    section_style = ParagraphStyle(
        "section", parent=styles["BodyText"], fontSize=11,
        fontName="Helvetica-Bold", textColor=colors.HexColor("#1f2937"),
        spaceBefore=8, spaceAfter=3,
    )
    label = ParagraphStyle(
        "label", parent=styles["BodyText"], textColor=colors.grey,
        fontSize=8, leading=10,
    )
    flow: list = []

    flow.append(Paragraph("<b>Transmisi Eng</b>", h1))
    flow.append(Paragraph(title, styles["BodyText"]))
    flow.append(Paragraph(
        "Generated " + datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"), label,
    ))
    flow.append(Spacer(1, 5 * mm))

    for sec in sections:
        flow.append(Paragraph(sec["name"], section_style))
        headers = sec["headers"]
        data = [headers] + [[_fmt_cell(c) for c in row] for row in sec["rows"]]
        if len(data) == 1:
            data.append(["—"] * len(headers))
        tbl = Table(data, repeatRows=1)
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef0f4")),
            ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
            ("FONT", (0, 1), (-1, -1), "Helvetica", 8.5),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("ALIGN", (0, 0), (0, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#cbd1dc")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f8fa")]),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
        ]))
        flow.append(tbl)
        flow.append(Spacer(1, 4 * mm))

    doc.build(flow)
    return buf.getvalue()


def render_xlsx(title: str, sections: list[dict]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment

    wb = Workbook()
    first = True
    bold = Font(bold=True)
    header_fill = PatternFill("solid", fgColor="EEF0F4")
    right = Alignment(horizontal="right")

    for sec in sections:
        ws = wb.active if first else wb.create_sheet()
        first = False
        ws.title = (sec["name"] or "Sheet")[:31].replace("/", "-")

        ws["A1"] = "Transmisi Eng"
        ws["A1"].font = Font(bold=True, size=14)
        ws["A2"] = title
        ws["A2"].font = bold
        ws["A3"] = "Generated " + datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

        row = 5
        headers = sec["headers"]
        for col_idx, h in enumerate(headers, start=1):
            cell = ws.cell(row=row, column=col_idx, value=h)
            cell.font = bold
            cell.fill = header_fill
        row += 1
        for r in sec["rows"]:
            for col_idx, v in enumerate(r, start=1):
                cell = ws.cell(row=row, column=col_idx, value=v)
                if col_idx > 1 and isinstance(v, (int, float)):
                    cell.alignment = right
            row += 1

        # Reasonable column widths
        for col_idx, h in enumerate(headers, start=1):
            width = max(12, min(48, len(str(h)) + 4))
            ws.column_dimensions[chr(64 + col_idx) if col_idx <= 26 else "A"].width = width

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()

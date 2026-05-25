from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.approval import (
    decide,
    evaluate_discount,
    request_approval,
)
from app.core.audit import record as audit_record
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.permissions import Role, can_approve_quotation
from app.models.account import Account
from app.models.approval import ApprovalRequest, ApprovalStatus
from app.models.crm import Activity, Customer, Reminder
from app.models.quotation import Quotation, QuotationItem
from app.models.user import User
from app.schemas.quotation import (
    QuotationAccountLinks,
    QuotationCreate,
    QuotationDecide,
    QuotationOut,
)
from app.services import ledger
from app.services.numbering import next_quotation_number

router = APIRouter()


def _recalc(q: Quotation, items: list[QuotationItem]) -> None:
    subtotal = sum(float(it.qty) * float(it.unit_price) for it in items)
    discount_amount = subtotal * float(q.discount_pct) / 100.0
    after_discount = subtotal - discount_amount
    tax = after_discount * float(q.tax_pct) / 100.0
    q.subtotal = subtotal
    q.discount_amount = discount_amount
    q.total = after_discount + tax
    for it in items:
        it.line_total = float(it.qty) * float(it.unit_price)


@router.post("", response_model=QuotationOut, status_code=201)
async def create_quotation(
    payload: QuotationCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    number = await next_quotation_number(db)
    q = Quotation(
        number=number,
        customer_id=payload.customer_id,
        variant=payload.variant,
        sales_pic_id=user.id,
        discount_pct=payload.discount_pct,
        tax_pct=payload.tax_pct,
        valid_until=payload.valid_until,
        notes=payload.notes,
        status="draft",
        created_by=user.id, updated_by=user.id,
    )
    db.add(q)
    await db.flush()
    items = [
        QuotationItem(quotation_id=q.id, **i.model_dump())
        for i in payload.items
    ]
    db.add_all(items)
    _recalc(q, items)
    await db.flush()
    return await _load(q.id, db)


@router.post("/{q_id}/submit", response_model=QuotationOut)
async def submit_quotation(
    q_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = await db.get(Quotation, q_id)
    if not q:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if q.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only draft can be submitted")

    rule = evaluate_discount(float(q.discount_pct))
    if rule.required_role is None:
        q.status = "approved"
    else:
        q.status = "pending_approval"
        await request_approval(
            db,
            target_type="quotation",
            target_id=q.id,
            requested_by=user.id,
            required_role=rule.required_role,
            reason=rule.reason,
            payload={"discount_pct": float(q.discount_pct), "total": float(q.total)},
        )
    await audit_record(db, actor=user, action="submit", entity="quotation",
                       entity_id=q.id, before={"status": "draft"},
                       after={"status": q.status})
    await db.flush()
    return await _load(q.id, db)


@router.post("/{q_id}/approve", response_model=QuotationOut)
async def approve_quotation(q_id: UUID, payload: QuotationDecide,
                            db: AsyncSession = Depends(get_db),
                            user: User = Depends(get_current_user)):
    if not can_approve_quotation(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Only manager or director can approve quotations")
    q = await db.get(Quotation, q_id)
    if not q:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quotation not found")
    if q.status not in ("pending_approval", "draft", "rejected"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot approve a quotation in status '{q.status}'",
        )
    # Decide any pending approval request that's still open; missing or
    # already-decided requests are fine — we still set the quotation status.
    req = await db.scalar(
        select(ApprovalRequest).where(
            ApprovalRequest.target_type == "quotation",
            ApprovalRequest.target_id == q_id,
            ApprovalRequest.status == ApprovalStatus.PENDING.value,
        )
    )
    if req:
        try:
            await decide(db, request_id=req.id, decider_id=user.id,
                         decider_role=Role(user.role), approve=True,
                         notes=payload.notes)
        except PermissionError as e:
            raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e
    q.status = "approved"
    await audit_record(db, actor=user, action="approve", entity="quotation",
                       entity_id=q.id, after={"status": "approved"})
    return await _load(q.id, db)


@router.post("/{q_id}/reject", response_model=QuotationOut)
async def reject_quotation(q_id: UUID, payload: QuotationDecide,
                           db: AsyncSession = Depends(get_db),
                           user: User = Depends(get_current_user)):
    if not can_approve_quotation(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Only manager or director can reject quotations")
    q = await db.get(Quotation, q_id)
    if not q:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quotation not found")
    if q.status not in ("pending_approval", "draft", "approved"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot reject a quotation in status '{q.status}'",
        )
    req = await db.scalar(
        select(ApprovalRequest).where(
            ApprovalRequest.target_type == "quotation",
            ApprovalRequest.target_id == q_id,
            ApprovalRequest.status == ApprovalStatus.PENDING.value,
        )
    )
    if req:
        try:
            await decide(db, request_id=req.id, decider_id=user.id,
                         decider_role=Role(user.role), approve=False,
                         notes=payload.notes)
        except PermissionError as e:
            raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e
    q.status = "rejected"
    await audit_record(db, actor=user, action="reject", entity="quotation",
                       entity_id=q.id, after={"status": "rejected",
                                              "notes": payload.notes})
    return await _load(q.id, db)


@router.post("/{q_id}/won", response_model=QuotationOut)
async def mark_won(q_id: UUID, db: AsyncSession = Depends(get_db),
                   user: User = Depends(get_current_user)):
    q = await db.get(Quotation, q_id)
    if not q:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    q.status = "won"
    # Auto-create project (deferred to service)
    from app.services.project_factory import create_project_from_quotation
    await create_project_from_quotation(db, q, user)
    # Auto-post to the ledger (idempotent)
    try:
        await ledger.post_quotation(db, q)
    except Exception:
        # Don't block the won flow if posting fails (e.g. missing accounts)
        pass
    await audit_record(db, actor=user, action="won", entity="quotation",
                       entity_id=q.id, after={"status": "won", "total": float(q.total or 0)})
    return await _load(q.id, db)


@router.post("/{q_id}/lost", response_model=QuotationOut)
async def mark_lost(q_id: UUID, reason: str,
                    db: AsyncSession = Depends(get_db),
                    user: User = Depends(get_current_user)):
    q = await db.get(Quotation, q_id)
    if not q:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    q.status = "lost"
    q.notes = (q.notes or "") + f"\n[lost @ {datetime.now(UTC).isoformat()}] {reason}"
    await audit_record(db, actor=user, action="lost", entity="quotation",
                       entity_id=q.id, after={"status": "lost", "reason": reason})
    return await _load(q.id, db)


async def _load(q_id: UUID, db: AsyncSession) -> Quotation:
    return await db.scalar(
        select(Quotation)
        .options(selectinload(Quotation.items))
        .where(Quotation.id == q_id)
    )


@router.get("", response_model=list[QuotationOut])
async def list_quotations(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    status_eq: str | None = None,
    customer_id: UUID | None = None,
    limit: int = 50,
):
    stmt = (
        select(Quotation)
        .options(selectinload(Quotation.items))
        .order_by(Quotation.created_at.desc())
        .limit(limit)
    )
    if Role(user.role) == Role.SALES:
        stmt = stmt.where(Quotation.sales_pic_id == user.id)
    if status_eq:
        stmt = stmt.where(Quotation.status == status_eq)
    if customer_id:
        stmt = stmt.where(Quotation.customer_id == customer_id)
    rows = (await db.scalars(stmt)).all()
    return [QuotationOut.model_validate(r) for r in rows]


@router.get("/stats")
async def stats(db: AsyncSession = Depends(get_db),
                user: User = Depends(get_current_user)):
    total = await db.scalar(select(func.count(Quotation.id)))
    return {"total": total or 0}


def _idr(n) -> str:
    n = float(n or 0)
    sign = "-" if n < 0 else ""
    s = f"{abs(n):,.0f}".replace(",", ".")
    return f"{sign}Rp {s}"


async def _quotation_bundle(db: AsyncSession, q_id: UUID) -> tuple[Quotation, list, Customer | None]:
    q = await db.get(Quotation, q_id)
    if not q:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quotation not found")
    items = (await db.scalars(
        select(QuotationItem).where(QuotationItem.quotation_id == q.id)
        .order_by(QuotationItem.position.asc())
    )).all()
    cust = await db.get(Customer, q.customer_id) if q.customer_id else None
    return q, items, cust


@router.get("/{q_id}/export.pdf")
async def export_quotation_pdf(
    q_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from io import BytesIO
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    )

    q, items, cust = await _quotation_bundle(db, q_id)
    if Role(user.role) == Role.SALES and q.sales_pic_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN)

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=15*mm, rightMargin=15*mm,
        topMargin=15*mm, bottomMargin=15*mm,
        title=f"Quotation {q.number}",
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Title"], fontSize=18, alignment=0)
    body = styles["BodyText"]
    label = ParagraphStyle("label", parent=body, textColor=colors.grey, fontSize=8, leading=10)
    flow: list = []

    flow.append(Paragraph("<b>Transmisi Eng</b>", h1))
    flow.append(Paragraph(f"Quotation <b>{q.number}</b>", body))
    flow.append(Spacer(1, 6*mm))

    meta = [
        ["Customer", cust.company_name if cust else "—"],
        ["Industry", (cust.industry if cust else "—").title()],
        ["Variant", (q.variant or "—").title()],
        ["Status", (q.status or "—").replace("_", " ").title()],
        ["Issued", q.created_at.strftime("%Y-%m-%d") if q.created_at else "—"],
        ["Valid until", q.valid_until.strftime("%Y-%m-%d") if q.valid_until else "—"],
    ]
    t = Table(meta, colWidths=[35*mm, 130*mm])
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
        ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 9),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.grey),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    flow.append(t)
    flow.append(Spacer(1, 6*mm))

    flow.append(Paragraph("<b>Line items</b>", body))
    flow.append(Spacer(1, 2*mm))
    rows = [["#", "Description", "Qty", "Unit", "Unit price", "Line total"]]
    for i, it in enumerate(items, start=1):
        rows.append([
            str(i),
            it.description or "",
            f"{float(it.qty or 0):g}",
            it.unit or "",
            _idr(it.unit_price),
            _idr(float(it.qty or 0) * float(it.unit_price or 0)),
        ])
    items_table = Table(
        rows,
        colWidths=[10*mm, 80*mm, 15*mm, 15*mm, 30*mm, 30*mm],
    )
    items_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef0f4")),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEABOVE", (0, 1), (-1, 1), 0.5, colors.HexColor("#cbd1dc")),
        ("LINEBELOW", (0, -1), (-1, -1), 0.5, colors.HexColor("#cbd1dc")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    flow.append(items_table)
    flow.append(Spacer(1, 4*mm))

    subtotal = float(q.subtotal or 0)
    disc_amt = subtotal * (float(q.discount_pct or 0) / 100.0)
    tax = float(q.tax_amount or 0)
    total = float(q.total or 0)
    totals = [
        ["Subtotal", _idr(subtotal)],
        [f"Discount ({float(q.discount_pct or 0):.1f}%)", f"−{_idr(disc_amt)}"],
        ["Tax", _idr(tax)],
        ["TOTAL", _idr(total)],
    ]
    t2 = Table(totals, colWidths=[150*mm, 30*mm])
    t2.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -2), "Helvetica", 9),
        ("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 11),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LINEABOVE", (0, -1), (-1, -1), 1, colors.black),
        ("TOPPADDING", (0, -1), (-1, -1), 4),
    ]))
    flow.append(t2)
    flow.append(Spacer(1, 8*mm))

    if q.notes:
        flow.append(Paragraph("<b>Notes</b>", body))
        flow.append(Paragraph(q.notes.replace("\n", "<br/>"), body))

    flow.append(Spacer(1, 12*mm))
    flow.append(Paragraph(
        "Generated by Transmisi Eng. Prices in IDR. "
        "Quotation valid for the period above.",
        label,
    ))
    doc.build(flow)
    pdf = buf.getvalue()
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="quotation-{q.number}.pdf"',
        },
    )


@router.get("/{q_id}/export.xlsx")
async def export_quotation_excel(
    q_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from io import BytesIO
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

    q, items, cust = await _quotation_bundle(db, q_id)
    if Role(user.role) == Role.SALES and q.sales_pic_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN)

    wb = Workbook()
    ws = wb.active
    ws.title = f"Quotation {q.number}"[:31]
    bold = Font(bold=True)
    title_font = Font(bold=True, size=16)
    header_fill = PatternFill("solid", fgColor="EEF0F4")
    thin = Side(border_style="thin", color="CBD1DC")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    right = Alignment(horizontal="right")

    ws["A1"] = "Transmisi Eng"
    ws["A1"].font = title_font
    ws.merge_cells("A1:F1")
    ws["A2"] = f"Quotation {q.number}"
    ws["A2"].font = bold
    ws.merge_cells("A2:F2")

    row = 4
    for label, value in [
        ("Customer",      cust.company_name if cust else "—"),
        ("Industry",      (cust.industry if cust else "—").title()),
        ("Variant",       (q.variant or "—").title()),
        ("Status",        (q.status or "—").replace("_", " ").title()),
        ("Issued",        q.created_at.strftime("%Y-%m-%d") if q.created_at else "—"),
        ("Valid until",   q.valid_until.strftime("%Y-%m-%d") if q.valid_until else "—"),
    ]:
        ws.cell(row=row, column=1, value=label).font = bold
        ws.cell(row=row, column=2, value=value)
        row += 1

    row += 1
    ws.cell(row=row, column=1, value="Line items").font = bold
    row += 1
    headers = ["#", "Description", "Qty", "Unit", "Unit price (IDR)", "Line total (IDR)"]
    for col_idx, h in enumerate(headers, start=1):
        cell = ws.cell(row=row, column=col_idx, value=h)
        cell.font = bold
        cell.fill = header_fill
        cell.border = box
    row += 1
    for i, it in enumerate(items, start=1):
        line_total = float(it.qty or 0) * float(it.unit_price or 0)
        vals = [
            i,
            it.description or "",
            float(it.qty or 0),
            it.unit or "",
            float(it.unit_price or 0),
            line_total,
        ]
        for col_idx, v in enumerate(vals, start=1):
            cell = ws.cell(row=row, column=col_idx, value=v)
            cell.border = box
            if col_idx >= 3:
                cell.alignment = right
            if col_idx in (5, 6):
                cell.number_format = '"Rp" #,##0'
        row += 1

    # Totals block
    subtotal = float(q.subtotal or 0)
    disc_amt = subtotal * (float(q.discount_pct or 0) / 100.0)
    tax = float(q.tax_amount or 0)
    total = float(q.total or 0)
    row += 1
    for label, value, fmt in [
        ("Subtotal",                                      subtotal, '"Rp" #,##0'),
        (f"Discount ({float(q.discount_pct or 0):.1f}%)", -disc_amt, '"Rp" #,##0'),
        ("Tax",                                           tax,      '"Rp" #,##0'),
        ("TOTAL",                                         total,    '"Rp" #,##0'),
    ]:
        ws.cell(row=row, column=5, value=label).font = bold
        cell = ws.cell(row=row, column=6, value=value)
        cell.font = bold
        cell.number_format = fmt
        cell.alignment = right
        row += 1

    # Column widths
    widths = [5, 50, 8, 8, 18, 18]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[chr(64 + i)].width = w

    if q.notes:
        row += 1
        ws.cell(row=row, column=1, value="Notes").font = bold
        row += 1
        ws.cell(row=row, column=1, value=q.notes)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=6)
        ws.cell(row=row, column=1).alignment = Alignment(wrap_text=True, vertical="top")

    buf = BytesIO()
    wb.save(buf)
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="quotation-{q.number}.xlsx"',
        },
    )


@router.get("/{q_id}", response_model=QuotationOut)
async def get_quotation(
    q_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = await _load(q_id, db)
    if not q:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quotation not found")
    if Role(user.role) == Role.SALES and q.sales_pic_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Out of scope")
    return q


# ─── Follow-ups ──────────────────────────────────────────────────────────────

class FollowUpIn(BaseModel):
    notes: str
    next_at: datetime | None = None
    next_channel: str = "dashboard"


async def _scoped_quote(q_id: UUID, db: AsyncSession, user: User) -> Quotation:
    q = await db.get(Quotation, q_id)
    if not q:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quotation not found")
    if Role(user.role) == Role.SALES and q.sales_pic_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Out of scope")
    return q


@router.post("/{q_id}/followup", status_code=201)
async def log_followup(
    q_id: UUID,
    payload: FollowUpIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = await _scoped_quote(q_id, db, user)
    if not payload.notes or not payload.notes.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Notes required.")

    activity = Activity(
        customer_id=q.customer_id,
        user_id=user.id,
        type="follow_up",
        direction="outbound",
        occurred_at=datetime.now(UTC),
        notes=payload.notes,
        meta={"quotation_id": str(q_id), "quotation_number": q.number},
    )
    db.add(activity)
    await db.flush()

    reminder_id: str | None = None
    if payload.next_at:
        rem = Reminder(
            customer_id=q.customer_id,
            user_id=user.id,
            kind="follow_up",
            due_at=payload.next_at,
            channel=payload.next_channel,
            message=f"Follow up on quotation {q.number}",
            status="pending",
        )
        db.add(rem)
        await db.flush()
        reminder_id = str(rem.id)

    return {
        "activity_id": str(activity.id),
        "reminder_id": reminder_id,
        "occurred_at": activity.occurred_at,
    }


@router.get("/{q_id}/followups")
async def list_followups(
    q_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = await _scoped_quote(q_id, db, user)

    # Activities: anything tagged with this quotation_id, plus generic
    # follow_up / quotation_sent / negotiation on the same customer after
    # the quotation was created.
    act_stmt = (
        select(Activity)
        .where(Activity.customer_id == q.customer_id)
        .order_by(Activity.occurred_at.desc())
        .limit(200)
    )
    activities = []
    for a in (await db.scalars(act_stmt)).all():
        tagged = bool(a.meta) and a.meta.get("quotation_id") == str(q_id)
        is_related_type = a.type in ("follow_up", "quotation_sent", "negotiation")
        after_quote = a.occurred_at >= q.created_at
        if tagged or (is_related_type and after_quote):
            activities.append({
                "id": str(a.id),
                "type": a.type,
                "direction": a.direction,
                "occurred_at": a.occurred_at,
                "notes": a.notes,
                "user_id": str(a.user_id) if a.user_id else None,
                "tagged": tagged,
            })

    # Pending reminders for the same customer
    rem_stmt = (
        select(Reminder)
        .where(Reminder.customer_id == q.customer_id, Reminder.status == "pending")
        .order_by(Reminder.due_at.asc())
    )
    reminders = [
        {
            "id": str(r.id),
            "kind": r.kind,
            "channel": r.channel,
            "due_at": r.due_at,
            "message": r.message,
        }
        for r in (await db.scalars(rem_stmt)).all()
    ]
    return {"activities": activities, "reminders": reminders}


@router.patch("/{q_id}/reminders/{reminder_id}/done")
async def followup_reminder_done(
    q_id: UUID,
    reminder_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _scoped_quote(q_id, db, user)
    rem = await db.get(Reminder, reminder_id)
    if not rem:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reminder not found")
    rem.status = "done"
    return {"ok": True}


# ─── Account links + ledger posting ──────────────────────────────────────────


@router.get("/{q_id}/account-links")
async def get_account_links(
    q_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = await _scoped_quote(q_id, db, user)
    amounts = ledger.compute_amounts(q)

    out_links = []
    for role, default in ledger.DEFAULTS.items():
        no = getattr(q, f"account_{role}_no") or default
        acc = await db.scalar(select(Account).where(Account.account_no == no))
        out_links.append({
            "role": role,
            "account_no": no,
            "account_name": acc.name if acc else None,
            "account_type": acc.account_type if acc else None,
            "current_balance": float(acc.balance or 0) if acc else None,
            "amount_to_post": amounts.get(role, 0),
        })
    return {
        "links": out_links,
        "is_posted": q.is_posted,
        "posted_at": q.posted_at,
        "posted_snapshot": q.posted_snapshot,
        "amounts": amounts,
    }


@router.patch("/{q_id}/account-links", response_model=QuotationOut)
async def update_account_links(
    q_id: UUID,
    payload: QuotationAccountLinks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = await _scoped_quote(q_id, db, user)
    if q.is_posted:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Cannot change account links after posting. Reverse first.",
        )
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(q, k, v)
    await db.flush()
    return await _load(q.id, db)


@router.post("/{q_id}/post-ledger", response_model=QuotationOut)
async def post_to_ledger(
    q_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = await _scoped_quote(q_id, db, user)
    await ledger.post_quotation(db, q)
    return await _load(q.id, db)


@router.post("/{q_id}/reverse-ledger", response_model=QuotationOut)
async def reverse_from_ledger(
    q_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = await _scoped_quote(q_id, db, user)
    await ledger.reverse_quotation(db, q)
    return await _load(q.id, db)

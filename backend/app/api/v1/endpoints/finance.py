"""Finance: invoice, payment, AR/AP, tax."""

import csv
import io
import re
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.permissions import Role, require
from app.models.crm import Customer
from app.models.finance import Invoice, OUTSTANDING_INVOICE_STATUSES, Payment
from app.models.user import User

# Finance data (AR aging, tax, payments) is confidential — restrict the whole
# router to the finance line and management. Sales/HR/purchasing/external roles
# have no business here. Mirrors the /finance + payment-verification sidebar gate.
router = APIRouter(
    # Admin is scoped to projects/ops/inventory — the finance router is
    # off-limits for them. Finance + manager oversight + director stay.
    dependencies=[Depends(require(Role.FINANCE, Role.MANAGER, Role.DIRECTOR))]
)

# Admin runs the customer-facing close-out — issue the invoice + delivery
# order, then put the faktur pajak number on it. That one act lives at a
# /finance/* path, so it gets its own router rather than admitting admin to
# AR aging, tax reports and payment verification along with it. Everything
# else in this file stays behind the router gate above.
invoice_desk = APIRouter(
    dependencies=[Depends(require(Role.FINANCE, Role.MANAGER, Role.DIRECTOR,
                                  Role.ADMIN))]
)


@router.get("/invoices/pending")
async def list_pending_invoices(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Finance's approval queue: every invoice waiting for finance sign-off,
    with the customer + project context they need to act on it. Includes any
    files already attached so finance can preview before approving."""
    from app.api.v1.endpoints.attachments import _attachment_visible_to
    from app.models.attachment import Attachment
    from app.models.crm import Customer
    from app.models.operation import Project

    rows = (await db.scalars(
        select(Invoice).where(Invoice.status == "pending_finance")
        .order_by(Invoice.issue_date.asc().nullslast(), Invoice.created_at.asc())
    )).all()
    if not rows:
        return []

    cust_ids = {r.customer_id for r in rows if r.customer_id}
    proj_ids = {r.project_id for r in rows if r.project_id}
    inv_ids = [r.id for r in rows]

    customers = {
        c.id: c for c in (await db.scalars(
            select(Customer).where(Customer.id.in_(cust_ids))
        )).all()
    } if cust_ids else {}
    projects = {
        p.id: p for p in (await db.scalars(
            select(Project).where(Project.id.in_(proj_ids))
        )).all()
    } if proj_ids else {}

    files_by_inv: dict = {}
    can_see_files = _attachment_visible_to("invoice", Role(_user.role))
    if can_see_files and inv_ids:
        for a in (await db.scalars(
            select(Attachment).where(
                Attachment.owner_type == "invoice",
                Attachment.owner_id.in_(inv_ids),
            ).order_by(Attachment.created_at.asc())
        )).all():
            files_by_inv.setdefault(a.owner_id, []).append({
                "id": str(a.id), "filename": a.filename,
                "download_url": f"/api/v1/attachments/{a.id}/download",
            })

    out = []
    for inv in rows:
        cust = customers.get(inv.customer_id)
        proj = projects.get(inv.project_id)
        out.append({
            "id": str(inv.id), "number": inv.number,
            "issue_date": inv.issue_date, "due_date": inv.due_date,
            "amount": float(inv.amount or 0),
            "tax_amount": float(inv.tax_amount or 0),
            "total": float(inv.total or 0),
            "customer_id": str(inv.customer_id) if inv.customer_id else None,
            "customer_name": cust.company_name if cust else None,
            "project_id": str(inv.project_id) if inv.project_id else None,
            "project_code": proj.code if proj else None,
            "files": files_by_inv.get(inv.id, []),
        })
    return out


@invoice_desk.post("/invoices/{invoice_id}/approve")
async def approve_invoice(
    invoice_id: UUID,
    faktur_pajak_no: str = Form(..., description="Faktur pajak number"),
    faktur_pajak_file: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Sign an invoice off with its faktur pajak number.

    Finance or admin: the two of them share the customer-facing close-out,
    and the number comes off the same document as the invoice it belongs to.
    It was finance-only on the theory that an admin misclick could corrupt
    the tax record — but the record is corrected by editing it, and keeping
    admin out only meant the invoice they issued sat waiting for someone
    else to type a number they already had in front of them.

    This is a document approval only — it does NOT post to the transaction
    journal. Revenue/AR recognition stays driven by the quotation posting and
    payment flows, so invoicing and the ledger remain decoupled.
    """
    fp_no = (faktur_pajak_no or "").strip()
    if not fp_no:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Faktur pajak number is required to approve.")

    inv = await db.get(Invoice, invoice_id)
    if not inv:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found")
    if inv.status == "approved":
        return {"ok": True, "status": inv.status, "already": True}

    from app.api.v1.endpoints.operation import _save_attachment
    from app.models.operation import Project, advance_project_status

    inv.faktur_pajak_no = fp_no
    inv.faktur_pajak_status = "issued"
    inv.status = "approved"
    inv.approved_by = user.id
    inv.approved_at = datetime.now(UTC)

    if faktur_pajak_file is not None:
        await _save_attachment(
            db, file=faktur_pajak_file, owner_type="invoice",
            owner_id=inv.id, user=user, label="faktur_pajak",
        )

    project = await db.get(Project, inv.project_id) if inv.project_id else None
    if project:
        advance_project_status(project, "invoiced")
    await db.flush()
    return {"ok": True, "status": inv.status,
            "faktur_pajak_no": inv.faktur_pajak_no,
            "faktur_pajak_status": inv.faktur_pajak_status}


@router.post("/invoices/{invoice_id}/reject")
async def reject_invoice(
    invoice_id: UUID,
    reason: str = Form(..., description="Why the invoice is being rejected (shown to admin)"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Finance rejects a pending invoice — sends it back to admin with a
    reason. Admin can then re-issue with corrections. No ledger effect."""
    reason = (reason or "").strip()
    if not reason:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Rejection reason is required.")
    inv = await db.get(Invoice, invoice_id)
    if not inv:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found")
    if inv.status not in ("pending_finance", "draft"):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Can't reject an invoice in status '{inv.status}'.")
    inv.status = "rejected"
    inv.approved_by = user.id            # who acted
    inv.approved_at = datetime.now(UTC)  # when
    inv.notes = ((inv.notes or "") + f"\n[rejected by {user.full_name}] {reason}").strip()
    await db.flush()
    return {"ok": True, "status": inv.status, "reason": reason}


@router.delete("/invoices/{invoice_id}", status_code=204)
async def delete_invoice(
    invoice_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete an invoice + its faktur-pajak record entirely.

    Finance's escape hatch for duplicates and test data — the button lives
    on the project page. Blocked when the invoice already has verified
    payments (would corrupt the ledger). Attachments and pending payment
    claims tied to the invoice are cleaned up alongside it.
    """
    if Role(user.role) not in (Role.FINANCE, Role.DIRECTOR):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only finance or the director can delete an invoice.",
        )
    inv = await db.get(Invoice, invoice_id)
    if not inv:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found")

    # Guard rail: refuse if there's any actual verified payment on it —
    # otherwise deleting the invoice orphans a ledger entry.
    paid = await db.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0))
        .where(Payment.invoice_id == invoice_id)
    ) or 0
    if float(paid) > 0:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This invoice already has verified payments — reverse the "
            "payment first (or reject it) before deleting the invoice, "
            "otherwise the ledger will be left unbalanced.",
        )

    # Remove pending / rejected payment claims — cascading through DB would
    # miss them because PaymentClaim doesn't cascade-delete on invoice.
    from app.models.attachment import Attachment
    from app.models.payment_claim import PaymentClaim
    for c in (await db.scalars(
        select(PaymentClaim).where(PaymentClaim.invoice_id == invoice_id)
    )).all():
        await db.delete(c)

    # Drop the file rows too. The blobs on disk stay behind; delete via the
    # /attachments endpoint if the physical files need cleaning as well.
    for a in (await db.scalars(
        select(Attachment).where(
            Attachment.owner_type == "invoice",
            Attachment.owner_id == invoice_id,
        )
    )).all():
        await db.delete(a)

    await db.delete(inv)
    await db.flush()
    from app.core.audit import record as audit_record
    await audit_record(
        db, actor=user, action="delete", entity="invoice",
        entity_id=invoice_id,
        before={"number": inv.number, "status": inv.status,
                "faktur_pajak_no": inv.faktur_pajak_no,
                "total": float(inv.total or 0)},
    )
    return None


@router.get("/efaktur.csv")
async def efaktur_export(
    period: str | None = Query(None, description="Masa pajak YYYY-MM (default: current month)"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Export approved output invoices with a Faktur Pajak number as an
    e-Faktur bulk-import CSV (FK/OF layout) for one masa pajak.

    Only invoices that finance has approved AND that carry a faktur number
    are included. Amounts are whole rupiah (e-Faktur has no decimals). DPP
    comes from the invoice amount, PPN from tax_amount.

    NOTE: e-Faktur's exact import schema varies by app version — verify the
    column set against your installed e-Faktur before importing; ping me to
    adjust separators/columns/KODE_JENIS if it differs.
    """
    # Resolve masa pajak window.
    today = date.today()
    if period:
        try:
            y, m = period.split("-")
            year, month = int(y), int(m)
            if not (1 <= month <= 12):
                raise ValueError
        except ValueError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "period must be YYYY-MM")
    else:
        year, month = today.year, today.month
    start = date(year, month, 1)
    end = date(year + (month == 12), (month % 12) + 1, 1)

    rows = (await db.scalars(
        select(Invoice).where(
            Invoice.status == "approved",
            Invoice.faktur_pajak_no.is_not(None),
        )
    )).all()

    def in_masa(inv: Invoice) -> bool:
        d = inv.issue_date or (inv.approved_at.date() if inv.approved_at else None)
        return bool(d and start <= d <= end - timedelta(days=1))

    rows = [r for r in rows if in_masa(r)]

    # Preload customers for NPWP / name / address.
    cust_ids = {r.customer_id for r in rows if r.customer_id}
    customers: dict = {}
    if cust_ids:
        for cst in (await db.scalars(select(Customer).where(Customer.id.in_(cust_ids)))).all():
            customers[cst.id] = cst

    def digits(s: str | None) -> str:
        return re.sub(r"\D", "", s or "")

    buf = io.StringIO()
    w = csv.writer(buf)
    # Schema declaration rows (the e-Faktur importer reads these headers).
    w.writerow(["FK", "KD_JENIS_TRANSAKSI", "FG_PENGGANTI", "NOMOR_FAKTUR",
                "MASA_PAJAK", "TAHUN_PAJAK", "TANGGAL_FAKTUR", "NPWP", "NAMA",
                "ALAMAT_LENGKAP", "JUMLAH_DPP", "JUMLAH_PPN", "JUMLAH_PPNBM",
                "ID_KETERANGAN_TAMBAHAN", "FG_UANG_MUKA", "UANG_MUKA_DPP",
                "UANG_MUKA_PPN", "UANG_MUKA_PPNBM", "REFERENSI"])
    w.writerow(["LT", "NPWP", "NAMA", "JALAN", "BLOK", "NOMOR", "RT", "RW",
                "KECAMATAN", "KELURAHAN", "KABUPATEN", "PROPINSI", "KODE_POS",
                "NOMOR_TELEPON"])
    w.writerow(["OF", "KODE_OBJEK", "NAMA", "HARGA_SATUAN", "JUMLAH_BARANG",
                "HARGA_TOTAL", "DISKON", "DPP", "PPN", "TARIF_PPNBM", "PPNBM"])

    for inv in rows:
        cst = customers.get(inv.customer_id)
        d = inv.issue_date or (inv.approved_at.date() if inv.approved_at else today)
        dpp = int(round(float(inv.amount or 0)))
        ppn = int(round(float(inv.tax_amount or 0)))
        npwp = digits(cst.tax_id if cst else None)
        nama = (cst.tax_name if cst and cst.tax_name else
                (cst.company_name if cst else "")) or ""
        alamat = (cst.tax_address if cst and cst.tax_address else
                  (cst.company_address if cst else "")) or ""
        # FK header row for this invoice.
        w.writerow(["FK", "01", "0", digits(inv.faktur_pajak_no),
                    str(month), str(year), d.strftime("%d/%m/%Y"),
                    npwp, nama, alamat, dpp, ppn, 0, "", "0", 0, 0, 0,
                    inv.number])
        # Single OF line = the whole invoice (line-level detail isn't stored).
        obj = (inv.notes or "Barang/Jasa").splitlines()[0][:80]
        w.writerow(["OF", "", obj, dpp, 1, dpp, 0, dpp, ppn, 0, 0])

    fname = f"efaktur-{year}-{month:02d}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/ar/aging")
async def ar_aging(db: AsyncSession = Depends(get_db),
                   _user: User = Depends(get_current_user)):
    """AR aging buckets: 0-30, 31-60, 61-90, 90+ days past due.

    Any invoice that's been issued (approved by finance) and isn't fully
    paid counts as outstanding. Missing 'approved' from this filter was
    why the Finance dashboard showed Rp 0 outstanding even when a huge
    unpaid approved invoice existed.
    """
    today = date.today()
    buckets = {"0-30": 0.0, "31-60": 0.0, "61-90": 0.0, "90+": 0.0, "current": 0.0}
    rows = (await db.scalars(
        select(Invoice).where(
            Invoice.status.in_(OUTSTANDING_INVOICE_STATUSES)
        )
    )).all()
    if not rows:
        return buckets
    # Subtract any verified payments so a partially-paid invoice only
    # ages the outstanding remainder, not the full total.
    inv_ids = [r.id for r in rows]
    paid_by_inv: dict = {}
    for row in (await db.execute(
        select(Payment.invoice_id, func.coalesce(func.sum(Payment.amount), 0))
        .where(Payment.invoice_id.in_(inv_ids))
        .group_by(Payment.invoice_id)
    )).all():
        paid_by_inv[row[0]] = float(row[1] or 0)
    for inv in rows:
        outstanding = max(0.0, float(inv.total or 0) - paid_by_inv.get(inv.id, 0.0))
        if outstanding <= 0:
            continue
        if not inv.due_date:
            # No due date: park as 'current' rather than dropping it.
            buckets["current"] += outstanding
            continue
        delta = (today - inv.due_date).days
        if delta < 0:
            buckets["current"] += outstanding
        elif delta <= 30:
            buckets["0-30"] += outstanding
        elif delta <= 60:
            buckets["31-60"] += outstanding
        elif delta <= 90:
            buckets["61-90"] += outstanding
        else:
            buckets["90+"] += outstanding
    return buckets


@router.post("/reminders/run")
async def run_payment_reminders(db: AsyncSession = Depends(get_db),
                                _user: User = Depends(get_current_user)):
    """Identify invoices needing reminders. The actual WA send is done by n8n."""
    today = date.today()
    upcoming = today + timedelta(days=3)
    rows = (await db.scalars(
        select(Invoice).where(
            Invoice.status.in_(OUTSTANDING_INVOICE_STATUSES),
            Invoice.due_date <= upcoming,
        )
    )).all()
    return {"to_remind": [
        {"invoice_id": str(r.id), "number": r.number,
         "customer_id": str(r.customer_id), "due_date": r.due_date,
         "total": float(r.total)} for r in rows
    ]}


@router.get("/tax/report")
async def tax_report(period: str = "current_month",
                     db: AsyncSession = Depends(get_db),
                     _user: User = Depends(get_current_user)):
    # Previously summed EVERY invoice in every status (including rejected and
    # draft) while echoing back the requested period — a period-scoped number
    # that wasn't period-scoped at all.
    today = date.today()
    if period in (None, "", "current_month"):
        start = today.replace(day=1)
        end = date(today.year + (today.month == 12),
                   (today.month % 12) + 1, 1)
    else:
        try:
            y, m = period.split("-")
            start = date(int(y), int(m), 1)
            end = date(int(y) + (int(m) == 12), (int(m) % 12) + 1, 1)
        except (ValueError, AttributeError):
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "period must be 'current_month' or YYYY-MM")
    total_tax = await db.scalar(
        select(func.coalesce(func.sum(Invoice.tax_amount), 0)).where(
            Invoice.status == "approved",
            Invoice.issue_date.is_not(None),
            Invoice.issue_date >= start,
            Invoice.issue_date < end,
        )
    )
    return {"period": period, "from": start, "to": end - timedelta(days=1),
            "tax_collected": float(total_tax or 0)}


@router.post("/payments")
async def record_payment(invoice_id: UUID, amount: float, method: str | None = None,
                         reference: str | None = None,
                         db: AsyncSession = Depends(get_db),
                         user: User = Depends(get_current_user)):
    """Legacy payment entry — delegates to the real manual-payment flow.

    This used to insert a bare Payment row: no invoice validation, no ledger
    post, no invoice-status recompute and no project advance. That produced
    "ghost" payments — the project page and AR aging counted them as paid while
    Cash/Piutang never moved and the invoice never reached 'paid'. It now runs
    the exact same code as POST /payments/manual so both paths behave
    identically.
    """
    from app.api.v1.endpoints.payments import (
        ManualPaymentIn, record_manual_payment,
    )
    return await record_manual_payment(
        payload=ManualPaymentIn(
            invoice_id=invoice_id, amount=amount,
            method=method, reference=reference,
        ),
        db=db, me=user,
    )


# ─── Estimated finance ───────────────────────────────────────────────────────
# The forward-looking picture: money the ledger hasn't recognised yet because
# the source document isn't finalised. Two buckets feed it —
#   1. Won quotations not yet posted to the ledger (committed revenue).
#   2. Open quotations still in the pipeline (not finalised sales).
# plus pending payroll (salaries not yet posted) on the cost side.

_PIPELINE_STATUSES = ("draft", "pending_approval", "approved", "sent")


async def _estimated_payload(db: AsyncSession) -> dict:
    from app.models.crm import Customer
    from app.models.quotation import Quotation
    from app.models.salary import Salary
    from app.services.ledger import compute_amounts

    won = (await db.scalars(
        select(Quotation).where(
            Quotation.status == "won", Quotation.is_posted.is_(False)
        ).order_by(Quotation.created_at.desc())
    )).all()
    pipeline = (await db.scalars(
        select(Quotation).where(Quotation.status.in_(_PIPELINE_STATUSES))
        .order_by(Quotation.created_at.desc())
    )).all()
    salaries = (await db.scalars(
        select(Salary).where(Salary.is_posted.is_(False))
        .order_by(Salary.period.desc())
    )).all()

    cust_ids = {q.customer_id for q in (*won, *pipeline) if q.customer_id}
    names: dict = {}
    if cust_ids:
        for c in (await db.scalars(select(Customer).where(Customer.id.in_(cust_ids)))).all():
            names[c.id] = c.company_name

    def _q_rows(qs: list) -> tuple[list, dict]:
        rows, tot = [], {"revenue": 0.0, "tax": 0.0, "receivable": 0.0}
        for q in qs:
            a = compute_amounts(q)
            tot["revenue"] += a["revenue"]
            tot["tax"] += a["tax"]
            tot["receivable"] += a["receivable"]
            rows.append({
                "id": str(q.id), "number": q.number, "status": q.status,
                "customer_name": names.get(q.customer_id),
                "total": float(q.total or 0),
                "revenue": a["revenue"], "tax": a["tax"],
            })
        return rows, tot

    won_rows, won_tot = _q_rows(won)
    pipe_rows, pipe_tot = _q_rows(pipeline)

    payroll_rows, payroll_tot = [], 0.0
    for s in salaries:
        net = float(s.net_pay or 0)
        payroll_tot += net
        payroll_rows.append({
            "id": str(s.id), "period": s.period, "status": s.status,
            "gross": float(s.gross_salary or 0), "net": net,
        })

    est_revenue = won_tot["revenue"] + pipe_tot["revenue"]
    return {
        "won_unposted": {"rows": won_rows, "totals": won_tot},
        "pipeline": {"rows": pipe_rows, "totals": pipe_tot},
        "unposted_payroll": {"rows": payroll_rows, "total": payroll_tot},
        "summary": {
            "committed_revenue": won_tot["revenue"],
            "pipeline_revenue": pipe_tot["revenue"],
            "estimated_revenue": est_revenue,
            "estimated_tax": won_tot["tax"] + pipe_tot["tax"],
            "estimated_receivable": won_tot["receivable"] + pipe_tot["receivable"],
            "pending_payroll": payroll_tot,
            "net_estimated": est_revenue - payroll_tot,
        },
    }


@router.get("/estimated")
async def estimated_finance(db: AsyncSession = Depends(get_db),
                            _user: User = Depends(get_current_user)):
    return await _estimated_payload(db)


def _idr(n: float) -> str:
    return "Rp " + f"{int(round(n or 0)):,}".replace(",", ".")


def _estimated_sections(p: dict) -> list[dict]:
    s = p["summary"]
    return [
        {"name": "Summary", "headers": ["Metric", "Amount"], "rows": [
            ["Committed revenue (won, unposted)", _idr(s["committed_revenue"])],
            ["Pipeline revenue (not finalised)", _idr(s["pipeline_revenue"])],
            ["Estimated revenue", _idr(s["estimated_revenue"])],
            ["Estimated tax", _idr(s["estimated_tax"])],
            ["Estimated receivable", _idr(s["estimated_receivable"])],
            ["Pending payroll", _idr(s["pending_payroll"])],
            ["Net estimated", _idr(s["net_estimated"])],
        ]},
        {"name": "Won — awaiting posting",
         "headers": ["Quotation", "Customer", "Revenue", "Tax", "Total"],
         "rows": [[r["number"], r["customer_name"] or "—", _idr(r["revenue"]),
                   _idr(r["tax"]), _idr(r["total"])] for r in p["won_unposted"]["rows"]]},
        {"name": "Pipeline — not finalised",
         "headers": ["Quotation", "Customer", "Status", "Est. revenue", "Total"],
         "rows": [[r["number"], r["customer_name"] or "—", r["status"],
                   _idr(r["revenue"]), _idr(r["total"])] for r in p["pipeline"]["rows"]]},
        {"name": "Pending payroll",
         "headers": ["Period", "Status", "Gross", "Net"],
         "rows": [[r["period"], r["status"], _idr(r["gross"]), _idr(r["net"])]
                  for r in p["unposted_payroll"]["rows"]]},
    ]


@router.get("/estimated/export.pdf")
async def estimated_export_pdf(db: AsyncSession = Depends(get_db),
                               _user: User = Depends(get_current_user)):
    from app.services.tabular_export import render_pdf
    sections = _estimated_sections(await _estimated_payload(db))
    data = render_pdf("Estimated finance", sections)
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="estimated-finance.pdf"'})


@router.get("/estimated/export.xlsx")
async def estimated_export_xlsx(db: AsyncSession = Depends(get_db),
                                _user: User = Depends(get_current_user)):
    from app.services.tabular_export import render_xlsx
    sections = _estimated_sections(await _estimated_payload(db))
    data = render_xlsx("Estimated finance", sections)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="estimated-finance.xlsx"'},
    )

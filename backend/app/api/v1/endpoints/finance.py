"""Finance: invoice, payment, AR/AP, tax."""

from datetime import date, timedelta

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.permissions import Role, require
from app.models.finance import Invoice, Payment
from app.models.user import User

# Finance data (AR aging, tax, payments) is confidential — restrict the whole
# router to the finance line and management. Sales/HR/purchasing/external roles
# have no business here. Mirrors the /finance + payment-verification sidebar gate.
router = APIRouter(
    dependencies=[Depends(require(Role.FINANCE, Role.ADMIN, Role.MANAGER, Role.DIRECTOR))]
)


@router.get("/ar/aging")
async def ar_aging(db: AsyncSession = Depends(get_db),
                   _user: User = Depends(get_current_user)):
    """AR aging buckets: 0-30, 31-60, 61-90, 90+ days past due."""
    today = date.today()
    buckets = {"0-30": 0.0, "31-60": 0.0, "61-90": 0.0, "90+": 0.0, "current": 0.0}
    rows = (await db.scalars(
        select(Invoice).where(Invoice.status.in_(["issued", "partial", "overdue"]))
    )).all()
    for inv in rows:
        if not inv.due_date:
            continue
        delta = (today - inv.due_date).days
        amount = float(inv.total)
        if delta < 0:
            buckets["current"] += amount
        elif delta <= 30:
            buckets["0-30"] += amount
        elif delta <= 60:
            buckets["31-60"] += amount
        elif delta <= 90:
            buckets["61-90"] += amount
        else:
            buckets["90+"] += amount
    return buckets


@router.post("/reminders/run")
async def run_payment_reminders(db: AsyncSession = Depends(get_db),
                                _user: User = Depends(get_current_user)):
    """Identify invoices needing reminders. The actual WA send is done by n8n."""
    today = date.today()
    upcoming = today + timedelta(days=3)
    rows = (await db.scalars(
        select(Invoice).where(
            Invoice.status.in_(["issued", "partial"]),
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
    total_tax = await db.scalar(select(func.coalesce(func.sum(Invoice.tax_amount), 0)))
    return {"period": period, "tax_collected": float(total_tax or 0)}


@router.post("/payments")
async def record_payment(invoice_id: str, amount: float, method: str | None = None,
                         reference: str | None = None,
                         db: AsyncSession = Depends(get_db),
                         _user: User = Depends(get_current_user)):
    p = Payment(invoice_id=invoice_id, amount=amount, method=method, reference=reference)
    db.add(p)
    await db.flush()
    return {"id": str(p.id), "ok": True}


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

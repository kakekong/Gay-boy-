"""KPI rollups for sales, purchasing, operation, finance."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.permissions import Role, require
from app.models.crm import Customer
from app.models.finance import Invoice
from app.models.operation import Project
from app.models.quotation import Quotation
from app.models.user import User

router = APIRouter()


@router.get("/sales")
async def sales_kpi(range_days: int = 30,
                    db: AsyncSession = Depends(get_db),
                    user: User = Depends(get_current_user)):
    since = datetime.now(UTC) - timedelta(days=range_days)
    is_sales = Role(user.role) == Role.SALES

    leads_q = select(func.count(Customer.id)).where(Customer.created_at >= since)
    if is_sales:
        leads_q = leads_q.where(Customer.sales_pic_id == user.id)
    new_leads = await db.scalar(leads_q)

    quotes_q = select(func.count(Quotation.id)).where(Quotation.created_at >= since)
    won_q = select(func.count(Quotation.id)).where(
        Quotation.status == "won", Quotation.updated_at >= since
    )
    if is_sales:
        # Quotation carries the sales rep directly (sales_pic_id).
        quotes_q = quotes_q.where(Quotation.sales_pic_id == user.id)
        won_q = won_q.where(Quotation.sales_pic_id == user.id)
    quotes = await db.scalar(quotes_q)
    won = await db.scalar(won_q)
    lead_to_quote = (quotes / new_leads) if new_leads else 0
    quote_to_win = (won / quotes) if quotes else 0
    return {
        "range_days": range_days,
        "new_leads": new_leads or 0,
        "quotations": quotes or 0,
        "won": won or 0,
        "lead_to_quote_rate": round(lead_to_quote, 3),
        "quote_to_win_rate": round(quote_to_win, 3),
    }


@router.get("/operation")
async def operation_kpi(db: AsyncSession = Depends(get_db),
                        _user: User = Depends(get_current_user)):
    on_time = await db.scalar(
        select(func.count(Project.id)).where(
            Project.actual_delivery.is_not(None),
            Project.actual_delivery <= Project.target_delivery,
        )
    )
    late = await db.scalar(
        select(func.count(Project.id)).where(
            Project.actual_delivery.is_not(None),
            Project.actual_delivery > Project.target_delivery,
        )
    )
    total = (on_time or 0) + (late or 0)
    return {
        "on_time": on_time or 0,
        "late": late or 0,
        "on_time_rate": round((on_time or 0) / total, 3) if total else 0,
    }


@router.get("/purchasing")
async def purchasing_kpi(_user: User = Depends(get_current_user)):
    return {"avg_lead_time_days": None, "qc_pass_rate": None, "drawing_approval_days_avg": None}


@router.get("/finance")
async def finance_kpi(db: AsyncSession = Depends(get_db),
                      user: User = Depends(get_current_user)):
    is_sales = Role(user.role) == Role.SALES
    paid_q = select(func.coalesce(func.sum(Invoice.total), 0)).where(Invoice.status == "paid")
    out_q = select(func.coalesce(func.sum(Invoice.total), 0)).where(
        Invoice.status.in_(["issued", "partial", "overdue"])
    )
    if is_sales:
        # Sales only sees the AR / collected for their own customers.
        own = select(Customer.id).where(Customer.sales_pic_id == user.id)
        paid_q = paid_q.where(Invoice.customer_id.in_(own))
        out_q = out_q.where(Invoice.customer_id.in_(own))
    paid = await db.scalar(paid_q)
    outstanding = await db.scalar(out_q)
    return {"collected": float(paid or 0), "outstanding": float(outstanding or 0)}


# ─── Export (PDF / Excel) — director only ───────────────────────────────────

def _pretty(k: str) -> str:
    return k.replace("_", " ").title()


def _pretty_val(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:,.0f}" if v >= 1000 else f"{v:g}"
    return str(v)


async def _build_kpi_export(ext: str, db: AsyncSession, user: User) -> Response:
    sales = await sales_kpi(range_days=30, db=db, user=user)
    ops = await operation_kpi(db=db, _user=user)
    purch = await purchasing_kpi(_user=user)
    fin = await finance_kpi(db=db, user=user)

    def section(name: str, data: dict) -> dict:
        return {
            "name": name,
            "headers": ["Metric", "Value"],
            "rows": [[_pretty(k), _pretty_val(v)] for k, v in data.items()],
        }

    sections = [
        section("Sales", sales),
        section("Operation", ops),
        section("Purchasing", purch),
        section("Finance", fin),
    ]

    from app.services.tabular_export import render_pdf, render_xlsx
    if ext == "pdf":
        data = render_pdf("KPI dashboard", sections)
        media = "application/pdf"
    else:
        data = render_xlsx("KPI dashboard", sections)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return Response(
        content=data, media_type=media,
        headers={"Content-Disposition": f'attachment; filename="kpi.{ext}"'},
    )


@router.get("/export.pdf")
async def export_kpi_pdf(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require(Role.DIRECTOR)),
):
    return await _build_kpi_export("pdf", db, user)


@router.get("/export.xlsx")
async def export_kpi_xlsx(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require(Role.DIRECTOR)),
):
    return await _build_kpi_export("xlsx", db, user)

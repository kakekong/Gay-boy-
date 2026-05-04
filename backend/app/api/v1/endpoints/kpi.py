"""KPI rollups for sales, purchasing, operation, finance."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.crm import Customer
from app.models.finance import Invoice
from app.models.operation import Project
from app.models.quotation import Quotation
from app.models.user import User

router = APIRouter()


@router.get("/sales")
async def sales_kpi(range_days: int = 30,
                    db: AsyncSession = Depends(get_db),
                    _user: User = Depends(get_current_user)):
    since = datetime.now(UTC) - timedelta(days=range_days)
    new_leads = await db.scalar(
        select(func.count(Customer.id)).where(Customer.created_at >= since)
    )
    quotes = await db.scalar(
        select(func.count(Quotation.id)).where(Quotation.created_at >= since)
    )
    won = await db.scalar(
        select(func.count(Quotation.id)).where(
            Quotation.status == "won", Quotation.updated_at >= since
        )
    )
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
                      _user: User = Depends(get_current_user)):
    paid = await db.scalar(
        select(func.coalesce(func.sum(Invoice.total), 0)).where(Invoice.status == "paid")
    )
    outstanding = await db.scalar(
        select(func.coalesce(func.sum(Invoice.total), 0)).where(
            Invoice.status.in_(["issued", "partial", "overdue"])
        )
    )
    return {"collected": float(paid or 0), "outstanding": float(outstanding or 0)}

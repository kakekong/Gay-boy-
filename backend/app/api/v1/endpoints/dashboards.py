"""Executive + AI Command Center dashboards."""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import deal_risk, profit_engine, smart_reminder
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.permissions import Role, require_min
from app.models.crm import Customer
from app.models.quotation import Quotation
from app.models.user import User

router = APIRouter()


@router.get("/executive")
async def executive(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_min(Role.MANAGER)),
):
    pipeline_value = await db.scalar(
        select(func.coalesce(func.sum(Quotation.total), 0)).where(
            Quotation.status.in_(["draft", "pending_approval", "approved", "sent"])
        )
    )
    won = await db.scalar(
        select(func.coalesce(func.sum(Quotation.total), 0)).where(Quotation.status == "won")
    )
    top_customers = (await db.execute(
        select(Customer.company_name, Customer.lifetime_value)
        .order_by(Customer.lifetime_value.desc())
        .limit(10)
    )).all()
    return {
        "pipeline_value": float(pipeline_value or 0),
        "won_revenue": float(won or 0),
        "top_customers": [
            {"company": c, "lifetime_value": float(v or 0)} for c, v in top_customers
        ],
    }


@router.get("/ai-command")
async def ai_command(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    at_risk = await deal_risk.list_at_risk(db, limit=10)
    actions = await smart_reminder.top_actions_for(db, user_id=user.id, limit=10)
    profit_alerts = await profit_engine.alerts(db, limit=10)
    return {
        "at_risk_deals": at_risk,
        "top_priority_actions": actions,
        "profit_alerts": profit_alerts,
        "forecast_vs_reality": await _forecast_vs_reality(db),
        "recommendations": [
            {"kind": "upsell", "text": "PT Cement A — likely needs chain replacement in 3 months"},
            {"kind": "supplier", "text": "Switch supplier for bearing X — QC fail rate 18% last 90d"},
        ],
    }


async def _forecast_vs_reality(db: AsyncSession):
    forecast = await db.scalar(
        select(func.coalesce(func.sum(Quotation.total), 0)).where(
            Quotation.status.in_(["approved", "sent"])
        )
    )
    reality = await db.scalar(
        select(func.coalesce(func.sum(Quotation.total), 0)).where(Quotation.status == "won")
    )
    return {"forecast": float(forecast or 0), "reality": float(reality or 0)}

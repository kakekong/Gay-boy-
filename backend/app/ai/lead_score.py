"""Lead Scoring AI.

Heuristic + (later) learned model. Implementation here is the heuristic
baseline that runs cold-start, before enough labels exist.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crm import Activity, Customer
from app.models.quotation import Quotation


_INDUSTRY_BASELINE = {
    "mining": 0.32, "pltu": 0.28, "fertilizer": 0.30, "sugar": 0.25,
    "cement": 0.34, "pulp_paper": 0.27, "food": 0.22, "other": 0.20,
}


async def compute(db: AsyncSession, customer_id: UUID) -> dict:
    customer = await db.get(Customer, customer_id)
    if not customer:
        return {"error": "not_found"}

    industry_baseline = _INDUSTRY_BASELINE.get(customer.industry, 0.2)

    activities = (await db.scalars(
        select(Activity).where(Activity.customer_id == customer_id)
        .order_by(Activity.occurred_at.desc()).limit(50)
    )).all()

    response_speed_hours = _avg_response_lag_hours(activities) or 24.0
    follow_up_consistency = min(len(activities) / 10.0, 1.0)

    open_quote_total = await db.scalar(
        select(func.coalesce(func.sum(Quotation.total), 0))
        .where(Quotation.customer_id == customer_id,
               Quotation.status.in_(["draft", "pending_approval", "approved", "sent"]))
    )
    project_value_log = _safe_log(float(open_quote_total or 0)) / 9.0

    historical_conversion = await _historical_conversion(db, customer.sales_pic_id)

    contributions = {
        "industry_baseline": industry_baseline * 100 * 0.20,
        "response_speed":    max(0.0, (24 - response_speed_hours) / 24) * 100 * 0.15,
        "follow_up_consistency": follow_up_consistency * 100 * 0.10,
        "project_value":     project_value_log * 100 * 0.20,
        "historical_conversion": historical_conversion * 100 * 0.15,
        "engagement_breadth": min(len({a.user_id for a in activities}) / 3, 1) * 100 * 0.10,
        "pipeline_velocity": 0.5 * 100 * 0.10,  # placeholder until industry-median table exists
    }
    score = int(round(sum(contributions.values())))
    score = max(0, min(100, score))

    drivers = sorted(
        ({"feature": k, "contribution": round(v, 1)} for k, v in contributions.items()),
        key=lambda x: -x["contribution"],
    )
    action = _recommended_action(drivers[0]["feature"], score)
    return {
        "customer_id": str(customer_id),
        "score": score,
        "drivers": drivers,
        "recommended_action": action,
        "computed_at": datetime.now(UTC).isoformat(),
        "model_version": "heuristic-v1",
    }


async def get_latest(db: AsyncSession, customer_id: UUID) -> dict:
    return await compute(db, customer_id)


def _avg_response_lag_hours(activities) -> float | None:
    pairs, last_inbound = [], None
    for a in reversed(activities):
        if a.direction == "inbound":
            last_inbound = a.occurred_at
        elif a.direction == "outbound" and last_inbound:
            pairs.append((a.occurred_at - last_inbound).total_seconds() / 3600.0)
            last_inbound = None
    return sum(pairs) / len(pairs) if pairs else None


async def _historical_conversion(db: AsyncSession, sales_pic_id) -> float:
    if not sales_pic_id:
        return 0.25
    won = await db.scalar(
        select(func.count(Quotation.id))
        .where(Quotation.sales_pic_id == sales_pic_id, Quotation.status == "won")
    )
    lost = await db.scalar(
        select(func.count(Quotation.id))
        .where(Quotation.sales_pic_id == sales_pic_id, Quotation.status == "lost")
    )
    total = (won or 0) + (lost or 0)
    return ((won or 0) / total) if total else 0.25


def _recommended_action(top_feature: str, score: int) -> str:
    if score >= 70:
        return "Push to close: schedule final negotiation within 5 days."
    if top_feature == "response_speed":
        return "Sales response time is the limiting factor — assign SLA reminder."
    if top_feature == "follow_up_consistency":
        return "Schedule weekly cadence; missing consistent touchpoints."
    if top_feature == "project_value":
        return "Increase quotation depth: propose detailed variant."
    return "Schedule technical meeting within 7 days."


def _safe_log(x: float) -> float:
    import math
    return 0.0 if x <= 1 else math.log10(x)

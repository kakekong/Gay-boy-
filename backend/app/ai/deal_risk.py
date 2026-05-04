"""Deal Risk Detector — Early Warning System.

Computes risk score per open deal. See docs/06-ai-logic-design.md §6.4.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crm import Activity, Customer
from app.models.quotation import Quotation


_OPEN_STATES = ("draft", "pending_approval", "approved", "sent")


async def scan_all(db: AsyncSession) -> dict:
    quotations = (await db.scalars(
        select(Quotation).where(Quotation.status.in_(_OPEN_STATES))
    )).all()
    out = []
    for q in quotations:
        out.append(await _score_quotation(db, q))
    return {"scanned": len(out), "items": out}


async def list_at_risk(db: AsyncSession, limit: int = 20) -> list[dict]:
    res = await scan_all(db)
    items = sorted(res["items"], key=lambda x: -x["risk_value"])
    return [i for i in items if i["risk_level"] != "low"][:limit]


async def _score_quotation(db: AsyncSession, q: Quotation) -> dict:
    customer = await db.get(Customer, q.customer_id)
    last_act_at = await db.scalar(
        select(func.max(Activity.occurred_at)).where(Activity.customer_id == q.customer_id)
    )
    days_idle = (datetime.now(UTC) - (last_act_at or q.created_at)).days

    revisions = await db.scalar(
        select(func.count(Quotation.id)).where(
            Quotation.customer_id == q.customer_id,
            Quotation.parent_id.isnot(None),
        )
    ) or 0

    discount_drift = max(0.0, float(q.discount_pct) - 5.0) / 20.0  # > 5% adds risk
    activity_count = await db.scalar(
        select(func.count(Activity.id)).where(
            Activity.customer_id == q.customer_id,
            Activity.occurred_at >= datetime.now(UTC) - timedelta(days=14),
        )
    ) or 0
    activity_below = 1.0 if activity_count < 2 else 0.0

    contributions = [
        ("days_idle", min(days_idle / 14.0, 1.0) * 0.30),
        ("quote_revisions", min(revisions / 4.0, 1.0) * 0.20),
        ("discount_drift", discount_drift * 0.20),
        ("activity_below_threshold", activity_below * 0.20),
        ("similar_lost_pattern", 0.0 * 0.10),  # plug embedding similarity later
    ]
    risk_value = sum(v for _, v in contributions)
    if risk_value < 0.35:
        level = "low"
    elif risk_value < 0.65:
        level = "medium"
    else:
        level = "high"

    return {
        "deal_id": str(q.id),
        "deal_number": q.number,
        "customer_id": str(q.customer_id),
        "customer_name": customer.company_name if customer else None,
        "discount_pct": float(q.discount_pct),
        "risk_value": round(risk_value, 3),
        "risk_level": level,
        "reasons": [
            {"factor": k, "contribution": round(v, 3)} for k, v in contributions if v > 0
        ],
        "recommended_action": _action_for(level, days_idle, float(q.discount_pct)),
    }


def _action_for(level: str, days_idle: int, discount_pct: float) -> str:
    if level == "high":
        if days_idle > 7:
            return "Follow up within 24 hours; escalate to manager."
        if discount_pct > 12:
            return "Offer revised pricing; ask director for guidance."
        return "Schedule site visit this week."
    if level == "medium":
        return "Add a follow-up activity in the next 48 hours."
    return "Healthy — keep cadence."

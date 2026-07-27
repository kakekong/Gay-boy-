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

router = APIRouter(
    # Internal-only surface. External portal accounts (customer /
    # supplier, hierarchy tier 0) must never reach the CRM, pricing,
    # calendar or notification data — they have /portal/* instead.
    dependencies=[Depends(require_min(Role.SALES))]
)


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


@router.get("/my-queue")
async def my_queue(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """The current user's personal action queue: their own quotations that
    need a next step (submit / chase to Won) plus reminders that are due.
    Scoped to the signed-in user regardless of role — it's *my* queue."""
    from datetime import UTC, datetime

    from app.models.crm import Reminder

    PER_BUCKET = 8

    async def _bucket(*statuses: str) -> tuple[list[dict], int]:
        base = select(Quotation).where(
            Quotation.sales_pic_id == user.id,
            Quotation.status.in_(statuses),
        )
        total = await db.scalar(
            select(func.count()).select_from(base.subquery())
        )
        rows = (await db.scalars(
            base.order_by(Quotation.created_at.desc()).limit(PER_BUCKET)
        )).all()
        cust_ids = {q.customer_id for q in rows if q.customer_id}
        names: dict = {}
        if cust_ids:
            for c in (await db.scalars(
                select(Customer).where(Customer.id.in_(cust_ids))
            )).all():
                names[c.id] = c.company_name
        items = [
            {
                "id": str(q.id),
                "number": q.number,
                "customer_name": names.get(q.customer_id),
                "total": float(q.total or 0),
                "status": q.status,
                "created_at": q.created_at,
            }
            for q in rows
        ]
        return items, int(total or 0)

    drafts, drafts_n = await _bucket("draft", "rejected")
    pending, pending_n = await _bucket("pending_approval")
    approved, approved_n = await _bucket("approved")

    # Reminders that are due now (or overdue) and still pending, mine only.
    now = datetime.now(UTC)
    rem_base = select(Reminder).where(
        Reminder.user_id == user.id,
        Reminder.status == "pending",
        Reminder.due_at <= now,
    )
    rem_n = await db.scalar(select(func.count()).select_from(rem_base.subquery()))
    rem_rows = (await db.scalars(
        rem_base.order_by(Reminder.due_at.asc()).limit(PER_BUCKET)
    )).all()
    rem_cust_ids = {r.customer_id for r in rem_rows if r.customer_id}
    rem_names: dict = {}
    if rem_cust_ids:
        for c in (await db.scalars(
            select(Customer).where(Customer.id.in_(rem_cust_ids))
        )).all():
            rem_names[c.id] = c.company_name
    reminders_due = [
        {
            "id": str(r.id),
            "kind": r.kind,
            "due_at": r.due_at,
            "message": r.message,
            "channel": r.channel,
            "customer_id": str(r.customer_id) if r.customer_id else None,
            "customer_name": rem_names.get(r.customer_id) if r.customer_id else None,
        }
        for r in rem_rows
    ]

    return {
        "drafts": drafts,
        "pending_approval": pending,
        "approved": approved,
        "reminders_due": reminders_due,
        "counts": {
            "drafts": drafts_n,
            "pending_approval": pending_n,
            "approved": approved_n,
            "reminders_due": int(rem_n or 0),
        },
    }


@router.get("/ai-command")
async def ai_command(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Sales only ever see their own data — their personal priority actions,
    # but none of the company-wide analytics (other reps' at-risk deals,
    # profit alerts, or the whole-company forecast).
    actions = await smart_reminder.top_actions_for(db, user_id=user.id, limit=10)
    if Role(user.role) == Role.SALES:
        return {
            "at_risk_deals": [],
            "top_priority_actions": actions,
            "profit_alerts": [],
            "forecast_vs_reality": {"forecast": 0.0, "reality": 0.0},
            "recommendations": [],
            "scoped_to_self": True,
        }
    at_risk = await deal_risk.list_at_risk(db, limit=10)
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

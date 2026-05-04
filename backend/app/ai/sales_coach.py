"""Sales Performance AI Coach."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crm import Activity
from app.models.quotation import Quotation


async def advise(db: AsyncSession, user_id: UUID) -> dict:
    won = await db.scalar(
        select(func.count(Quotation.id)).where(
            Quotation.sales_pic_id == user_id, Quotation.status == "won"
        )
    ) or 0
    lost = await db.scalar(
        select(func.count(Quotation.id)).where(
            Quotation.sales_pic_id == user_id, Quotation.status == "lost"
        )
    ) or 0
    total = won + lost
    win_rate = (won / total) if total else 0

    activities_30d = await db.scalar(
        select(func.count(Activity.id)).where(Activity.user_id == user_id)
    ) or 0

    bullets = []
    if win_rate < 0.20 and total >= 5:
        bullets.append("Win rate below team baseline — try shorter quotation variant first.")
    if activities_30d < 30 and total > 0:
        bullets.append("Touchpoint cadence is low; aim for 3+ activities per active deal/week.")
    if not bullets:
        bullets.append("On track. Keep cadence and document closing tactics in KB.")
    return {
        "user_id": str(user_id),
        "win_rate": round(win_rate, 3),
        "won": won, "lost": lost,
        "activities": activities_30d,
        "coaching": bullets,
    }

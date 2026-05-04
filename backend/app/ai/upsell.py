"""Opportunity Expansion AI."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crm import Customer
from app.models.operation import Project


_INDUSTRY_HEURISTICS = {
    "cement": [
        ("Chain replacement (12 in)", "12-18 month wear cycle"),
        ("Bearing kit", "frequent replacement; bundle to lock-in"),
    ],
    "mining": [
        ("Wear-resistant liner", "high abrasion environment"),
        ("Idler set", "common consumable"),
    ],
    "pltu": [
        ("Coal feeder spare", "annual outage replenishment"),
        ("Mill liner refurb", "scheduled mid-life refurb"),
    ],
}


async def for_customer(db: AsyncSession, customer_id: UUID) -> dict:
    customer = await db.get(Customer, customer_id)
    if not customer:
        return {"error": "not_found"}
    finished = (await db.scalars(
        select(Project).where(Project.customer_id == customer_id,
                              Project.status.in_(["delivered", "invoiced", "paid", "closed"]))
    )).all()

    suggestions = []
    for product, reason in _INDUSTRY_HEURISTICS.get(customer.industry, []):
        suggestions.append({
            "product": product,
            "reason": reason,
            "suggested_window_days": 90 if not finished else 30,
            "suggested_message": f"Hi {customer.pic_name or 'Bapak/Ibu'}, "
                                 f"berdasarkan riwayat project, kami sarankan review "
                                 f"kebutuhan {product.lower()}. Bisa kami diskusikan?"
        })
    return {"customer_id": str(customer_id), "suggestions": suggestions}

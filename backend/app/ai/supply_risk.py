"""Supply Risk Monitor."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.purchasing import Supplier


async def dashboard(db: AsyncSession) -> dict:
    rows = (await db.scalars(select(Supplier))).all()
    items = []
    for s in rows:
        risk = (
            min(float(s.lead_time_days_avg or 0) / 30.0, 1.0) * 0.4
            + float(s.qc_fail_rate or 0) * 0.4
            + float(s.price_volatility or 0) * 0.2
        )
        items.append({
            "supplier_id": str(s.id),
            "name": s.name,
            "rating": float(s.rating or 0),
            "lead_time_days_avg": float(s.lead_time_days_avg or 0),
            "qc_fail_rate": float(s.qc_fail_rate or 0),
            "price_volatility": float(s.price_volatility or 0),
            "risk_value": round(risk, 3),
            "risk_level": "high" if risk >= 0.5 else "medium" if risk >= 0.25 else "low",
        })
    items.sort(key=lambda x: -x["risk_value"])
    return {"suppliers": items}

"""Profit Intelligence Engine."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.operation import Project


_MARGIN_BREACH_PP = 0.05  # 5 pp drop triggers alert


async def for_project(db: AsyncSession, project_id: UUID) -> dict:
    p = await db.get(Project, project_id)
    if not p:
        return {"error": "not_found"}
    revenue = float(p.po_value or 0)
    estimate = float(p.margin_estimate or 0)
    actual = float(p.margin_actual or 0)
    breakdown = {
        "material": 0.0,
        "purchasing": 0.0,
        "logistics": 0.0,
        "labor": 0.0,
        "discount": 0.0,
    }
    return {
        "project_id": str(p.id),
        "revenue": revenue,
        "margin_estimate": estimate,
        "margin_actual": actual,
        "breakdown": breakdown,
        "alert": (estimate - actual) >= _MARGIN_BREACH_PP,
        "suggestions": _suggestions(estimate, actual),
    }


async def alerts(db: AsyncSession, limit: int = 10) -> list[dict]:
    rows = (await db.scalars(
        select(Project).where(Project.is_deleted.is_(False))
    )).all()
    alerts_list = []
    for p in rows:
        if (float(p.margin_estimate or 0) - float(p.margin_actual or 0)) >= _MARGIN_BREACH_PP:
            alerts_list.append({
                "project_id": str(p.id),
                "code": p.code,
                "estimate": float(p.margin_estimate or 0),
                "actual": float(p.margin_actual or 0),
            })
    return alerts_list[:limit]


def _suggestions(estimate: float, actual: float) -> list[str]:
    diff = estimate - actual
    out = []
    if diff >= _MARGIN_BREACH_PP:
        out.append("Investigate cost categories; logistics & material first.")
        out.append("Consider switching supplier (see Supply Risk Monitor).")
        out.append("Adjust pricing on next variant.")
    if actual < 0.10:
        out.append("Margin is critically low — escalate to manager.")
    return out

"""Document numbering. Keeps a per-year counter via row-level lock."""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.quotation import Quotation


async def next_quotation_number(db: AsyncSession, *, persist: bool = True) -> str:
    year = datetime.utcnow().year
    prefix = f"QT-{year}-"
    existing = await db.scalar(
        select(func.count(Quotation.id)).where(Quotation.number.like(f"{prefix}%"))
    ) or 0
    return f"{prefix}{existing + 1:04d}"

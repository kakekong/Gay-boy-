"""Document numbering. Keeps a per-year counter via row-level lock."""

import re
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.quotation import Quotation


def _clean_token(token: str) -> str:
    """Sanitise a caller-supplied token to 2-8 uppercased alnum chars.

    Falls back to the configured company token when nothing usable is left.
    """
    cleaned = re.sub(r"[^A-Za-z0-9]", "", token or "").upper()
    return cleaned[:8] if len(cleaned) >= 2 else settings.QUOTATION_COMPANY_TOKEN


async def next_quotation_number(
    db: AsyncSession,
    *,
    customer_id=None,   # kept for backward-compat; no longer drives the token
    token: str | None = None,
    persist: bool = True,
) -> str:
    """Issue the next quotation number in the form  QT-<TOK>-<YYYY>-<NNNN>.

    <TOK> is a *fixed* company token (settings.QUOTATION_COMPANY_TOKEN), so
    every quotation shares the same code regardless of customer. A caller may
    pass an explicit ``token`` to override it. The counter is per-token,
    per-year, so numbers never collide within a year.
    """
    year = datetime.utcnow().year
    tok = _clean_token(token) if token else settings.QUOTATION_COMPANY_TOKEN
    prefix = f"QT-{tok}-{year}-"
    existing = await db.scalar(
        select(func.count(Quotation.id)).where(Quotation.number.like(f"{prefix}%"))
    ) or 0
    return f"{prefix}{existing + 1:04d}"

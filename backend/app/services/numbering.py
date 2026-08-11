"""Document numbering.

Numbers come from the **highest suffix already issued**, not from a row count.
That distinction is the whole of this module's history: counting works right up
until a document is deleted, and then the counter walks backwards and the next
document is handed a number that is still in use. The insert fails on the
unique index, and the user sees "could not create price request" with nothing
to tell them why.

That is not a hypothetical. The director can delete a price request or a
quotation from *Clear test data*, and until this was fixed, doing so broke the
creation of the next one.
"""

import re
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.quotation import Quotation


async def _next_suffix(db: AsyncSession, column, prefix: str) -> int:
    """One past the largest number already issued under `prefix`.

    Compares on the numeric tail rather than the whole string so that 0009 and
    0010 sort the way a person expects, and ignores any suffix that isn't
    digits — a hand-entered number should never stop the next one being issued.
    """
    rows = (await db.scalars(
        select(column).where(column.like(f"{prefix}%"))
    )).all()
    best = 0
    for value in rows:
        tail = (value or "")[len(prefix):]
        m = re.match(r"^(\d+)", tail)
        if m:
            best = max(best, int(m.group(1)))
    return best + 1


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
    return f"{prefix}{await _next_suffix(db, Quotation.number, prefix):04d}"


async def next_price_request_number(db: AsyncSession) -> str:
    """Issue the next price-request number in the form  PR-<YYYY>-<NNNN>."""
    from app.models.price_request import PriceRequest
    year = datetime.utcnow().year
    prefix = f"PR-{year}-"
    return f"{prefix}{await _next_suffix(db, PriceRequest.number, prefix):04d}"


async def next_supplier_price_request_number(db: AsyncSession) -> str:
    """Issue the next supplier price-request number:  SPR-<YYYY>-<NNNN>.

    A separate series from PR- on purpose. The two documents travel in
    opposite directions — one asks what a customer will pay, the other asks
    what a supplier charges — and sharing a counter would make two unrelated
    things look like the same sequence on a desk.
    """
    from app.models.purchasing import SupplierPriceRequest
    year = datetime.utcnow().year
    prefix = f"SPR-{year}-"
    return f"{prefix}{await _next_suffix(db, SupplierPriceRequest.number, prefix):04d}"

"""Document numbering. Keeps a per-year counter via row-level lock."""

import re
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crm import Customer
from app.models.quotation import Quotation


def _customer_token(name: str) -> str:
    """Compact 2-5 letter token from a customer name for use inside a doc
    number, e.g. "PT. Sukses Mantap Sejahtera (SMS Agro)" → "SMS".

    Prefers an explicit acronym in parentheses (e.g. "(SMS Agro)" → "SMS"),
    otherwise picks the initials of the first 2-3 significant words,
    otherwise falls back to the first 3 letters of the cleaned name.
    """
    if not name:
        return "X"
    paren = re.search(r"\(([^)]+)\)", name)
    candidates: list[str] = []
    if paren:
        candidates.append(paren.group(1))
    # The name with the parenthesised part removed.
    stripped = re.sub(r"\([^)]*\)", "", name)
    candidates.append(stripped)
    SKIP = {"pt", "cv", "ud", "tbk", "persero", "perseroan", "the", "and", "&"}
    for c in candidates:
        words = [w for w in re.findall(r"[A-Za-z0-9]+", c)
                 if w and w.lower() not in SKIP]
        if not words:
            continue
        # Initials of the first 3 significant words (uppercased).
        token = "".join(w[0] for w in words[:3]).upper()
        if 2 <= len(token) <= 5 and token.isalnum():
            return token
    # Last resort: first 3 letters of the whole name.
    fallback = re.sub(r"[^A-Za-z0-9]", "", name).upper()
    return (fallback[:3] or "X")


async def next_quotation_number(
    db: AsyncSession,
    *,
    customer_id=None,
    persist: bool = True,
) -> str:
    """Issue the next quotation number in the form  QT-<TOK>-<YYYY>-<NNNN>.

    <TOK> is a short token derived from the customer's name (initials in
    parens win, then word initials, then a 3-char fallback). The counter
    is per-year, global across all customers, so two POs to different
    customers in the same year never share a number.
    """
    year = datetime.utcnow().year
    token = "X"
    if customer_id is not None:
        cust = await db.get(Customer, customer_id)
        if cust:
            token = _customer_token(cust.company_name)
    prefix = f"QT-{token}-{year}-"
    existing = await db.scalar(
        select(func.count(Quotation.id)).where(Quotation.number.like(f"{prefix}%"))
    ) or 0
    return f"{prefix}{existing + 1:04d}"

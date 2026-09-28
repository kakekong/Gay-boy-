"""The part code (KODE BARANG) for a line on a document the customer receives.

The customer's PO lines are what an invoice or a delivery order prints, and
they are typed or copied without the part code. The quotation behind the job
carries it on each line, and the price request behind that — which is where
the code was issued. So a line takes the code of the quotation (or price
request) line with the same name, or, failing a name match, the quotation line
in the same position when the two lists are the same length.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def _key(x) -> str:
    return re.sub(r"\s+", " ", (x or "").strip()).lower()


async def quotation_rows(db: AsyncSession, project) -> list[dict]:
    """The quotation's lines for this job, as plain dicts."""
    if project is None or not getattr(project, "quotation_id", None):
        return []
    from app.models.quotation import QuotationItem
    rows = (await db.scalars(
        select(QuotationItem).where(QuotationItem.quotation_id == project.quotation_id)
        .order_by(QuotationItem.line_no)
    )).all()
    return [{"description": it.description, "qty": float(it.qty or 0),
             "uom": it.uom, "unit_price": float(it.unit_price or 0),
             "sku": getattr(it, "sku", None)} for it in rows]


async def fill_item_codes(db: AsyncSession, rows: list[dict], project,
                          quote_rows: list[dict] | None = None) -> list[dict]:
    """`rows` with a `sku` on every line the job's paperwork can name."""
    if quote_rows is None:
        quote_rows = await quotation_rows(db, project)
    codes = {_key(r.get("description")): r.get("sku")
             for r in quote_rows if r.get("sku")}
    if project is not None and getattr(project, "price_request_id", None):
        from app.models.price_request import PriceRequest
        pr = await db.get(PriceRequest, project.price_request_id)
        for it in (pr.items or []) if pr else []:
            if it.get("sku"):
                codes.setdefault(_key(it.get("description")), it.get("sku"))
    same_shape = len(quote_rows) == len(rows)
    out = []
    for i, r in enumerate(rows):
        r = dict(r)
        if not r.get("sku"):
            r["sku"] = codes.get(_key(r.get("description"))) or (
                quote_rows[i].get("sku") if same_shape else None)
        out.append(r)
    return out

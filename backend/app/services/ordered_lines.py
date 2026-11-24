"""Which lines of a price request the customer actually ordered.

A quotation can carry ten lines and the customer's PO order three of them —
sales ticks the lines on the PO when they file it, and each PO line keeps the
quotation line it stands for (`line_no`). A quotation made from a price
request numbers its lines as the request does, so a PO line's `line_no` is
the price request line it ordered.

Everything downstream of the PO should follow it: what purchasing sources,
what suppliers are asked to quote, what is invoiced. This answers the one
question they all need — "was this line ordered?" — in one place.

`None` means "no way to tell, treat every line as ordered": no customer PO
yet, or one whose lines were typed in fresh with no quotation line behind
them. Then nothing is held back, exactly as before.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def ordered_line_nos(db: AsyncSession, price_request_id: UUID | str | None) -> set[int] | None:
    from app.models.customer_po import CustomerPO
    from app.models.operation import Project
    from app.models.quotation import Quotation

    if not price_request_id:
        return None
    pr_id = UUID(str(price_request_id))
    # The customer PO for this request: on the project it became, or against
    # any quotation (revisions included) made from it.
    project_ids = list((await db.scalars(
        select(Project.id).where(Project.price_request_id == pr_id))).all())
    quote_ids = list((await db.scalars(
        select(Quotation.id).where(Quotation.price_request_id == pr_id))).all())
    if not project_ids and not quote_ids:
        return None
    conds = []
    if project_ids:
        conds.append(CustomerPO.project_id.in_(project_ids))
    if quote_ids:
        conds.append(CustomerPO.quotation_id.in_(quote_ids))
    from sqlalchemy import or_
    po = (await db.scalars(
        select(CustomerPO).where(or_(*conds), CustomerPO.status != "rejected")
        .order_by(CustomerPO.created_at.desc()).limit(1))).first()
    if po is None:
        return None
    nos = {int(it["line_no"]) for it in (po.items or [])
           if isinstance(it, dict) and it.get("line_no") not in (None, "")}
    return nos or None


def is_ordered(line_no, ordered: set[int] | None) -> bool:
    if ordered is None or line_no in (None, ""):
        return True
    try:
        return int(line_no) in ordered
    except (TypeError, ValueError):
        return True

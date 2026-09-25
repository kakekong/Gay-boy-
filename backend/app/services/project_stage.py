"""Delivered before invoiced — decided from what happened, not event order.

The pipeline reads `… packaging → delivered → invoiced → paid`: the goods
reach the customer and the invoice follows them. The two events do not
always arrive in that order, though — finance can approve an invoice while
the truck is still out. So neither event moves the project on its own.
Both call `settle_delivery_and_invoice`, which looks at the facts:

* delivered — admin confirmed the customer received it, or every delivery
  order on the job is delivered;
* invoiced — a non-deposit invoice on the job has been approved.

Delivered alone puts the job at `delivered`; both put it at `invoiced`; an
invoice alone moves nothing, so a job invoiced early still shows that it is
waiting to be delivered. The one-off re-sort of existing projects in
`scripts/seed.py` applies the same rule in SQL.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

INVOICED_STATUSES = ("approved", "partial", "issued", "overdue", "paid")


async def delivery_done(db: AsyncSession, project) -> bool:
    from app.models.operation import DeliveryOrder

    if project.customer_received_at is not None:
        return True
    total, open_ = (await db.execute(
        select(func.count(DeliveryOrder.id),
               func.count(DeliveryOrder.id).filter(DeliveryOrder.status != "delivered"))
        .where(DeliveryOrder.project_id == project.id)
    )).one()
    return bool(total) and not open_


async def invoice_done(db: AsyncSession, project) -> bool:
    from app.models.finance import Invoice

    return bool(await db.scalar(
        select(func.count(Invoice.id)).where(
            Invoice.project_id == project.id,
            Invoice.type != "dp",
            Invoice.status.in_(INVOICED_STATUSES),
        )
    ))


async def settle_delivery_and_invoice(db: AsyncSession, project) -> str:
    """Move the project forward to where delivery + invoicing put it."""
    from app.models.operation import advance_project_status

    delivered = await delivery_done(db, project)
    if delivered:
        advance_project_status(project, "delivered")
        if await invoice_done(db, project):
            advance_project_status(project, "invoiced")
    return project.status


async def stage_before_payment(db: AsyncSession, project) -> str:
    """Where a job goes back to when its payment is reversed: `invoiced` if
    it was delivered, otherwise the stage before delivery."""
    return "invoiced" if await delivery_done(db, project) else "packaging"

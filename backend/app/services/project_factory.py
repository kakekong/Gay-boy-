"""Where a project comes from.

**A job starts when the deal is Won.** That is the moment the customer has
said yes and put their order behind it — Won cannot be clicked without their
PO on file — so it is the moment the work becomes real and everyone
downstream needs somewhere to hang drawings, purchase orders and dates. It
used to wait for the director to approve the customer PO as well, which put
a second signature between "we won this" and "we can start", and left sales
looking at a won deal with no project against it.

The customer PO's own approval still matters; it just is not what mints the
project any more. When it lands it attaches to the project already there.

One exception, and it is deliberate: a **down-payment order** keeps its
gate. The whole point of a DP is that we do not start until the deposit
arrives, so for those the project appears when sales confirm the money
landed — see `customer_pos.confirm_dp_received`.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.orchestrator import emit
from app.models.customer_po import CustomerPO
from app.models.operation import Project
from app.models.quotation import Quotation
from app.models.user import User


async def project_for_quotation(db: AsyncSession, quotation_id) -> Project | None:
    """The live project already raised against this quotation, if any."""
    if not quotation_id:
        return None
    return await db.scalar(
        select(Project).where(
            Project.quotation_id == quotation_id,
            Project.is_deleted.is_(False),
        ).order_by(Project.created_at.asc()).limit(1)
    )


async def _backing_po(db: AsyncSession, quotation_id) -> CustomerPO | None:
    """The customer's order behind this quotation.

    The earliest one still standing: that is the order the Won was called on.
    A later PO against the same quote is an addition to a job that already
    exists, not a second job.
    """
    if not quotation_id:
        return None
    return await db.scalar(
        select(CustomerPO).where(
            CustomerPO.quotation_id == quotation_id,
            CustomerPO.status.notin_(("rejected", "cancelled")),
        ).order_by(CustomerPO.created_at.asc()).limit(1)
    )


async def create_project(
    db: AsyncSession, *, user: User, customer_id, quotation_id=None,
    price_request_id=None, po: CustomerPO | None = None,
) -> Project:
    """Mint a project. Callers decide *when*; this decides what it looks like.

    No work order is created here. Purchasing raises the receiving order by
    confirming the delivery date (`operation.confirm_delivery`), which is the
    step that actually knows when goods turn up.
    """
    from app.services.numbering import next_project_code

    project = Project(
        code=await next_project_code(db),
        customer_id=customer_id,
        quotation_id=quotation_id,
        price_request_id=price_request_id,
        po_number=po.number if po else None,
        po_date=po.po_date if po else None,
        po_value=po.total if po else None,
        status="new",
        created_by=user.id, updated_by=user.id,
    )
    db.add(project)
    await db.flush()
    return project


async def ensure_project_for_quotation(
    db: AsyncSession, q: Quotation, user: User
) -> Project | None:
    """The project for a Won quotation, created if this is the first ask.

    Returns None when the job is a down-payment order — those wait for the
    deposit — or when there is no customer order behind the quotation at all,
    which `mark_won` refuses anyway but this must not assume.
    """
    existing = await project_for_quotation(db, q.id)
    if existing:
        return existing

    po = await _backing_po(db, q.id)
    if po is None:
        return None
    if po.is_downpayment:
        # The deposit gate owns this one. Starting the job here would be the
        # exact thing a down-payment exists to prevent.
        return None

    project = await create_project(
        db, user=user, customer_id=q.customer_id, quotation_id=q.id,
        price_request_id=q.price_request_id, po=po,
    )
    if po.project_id is None:
        po.project_id = project.id
    await emit(db, "quotation.won", {
        "quotation_id": str(q.id), "project_id": str(project.id),
    })
    return project

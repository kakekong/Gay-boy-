"""One customer PO per deal, and taking a PO away without taking its job.

Two POs against one deal used to be allowed on purpose — staged orders — and
the only guard was the exact number. So a PO typed twice with a digit wrong
(911805889 / 9118005889) went through as two orders, both were approved, and
both hung off the same project. There was also no way to remove the wrong
one: the data-maintenance delete treated a project as a child of its PO,
from when approving the PO was what created the project. It isn't any more —
marking the quotation Won does — so deleting a PO took down a job that never
belonged to it.

This module holds both halves:

* `existing_po_for_deal` — the PO already on file for a quotation or any
  revision of it, which is what makes a second one a refusal.
* `release_from_project` — undo what a PO gave its project before the PO
  goes: the project's printed number, date and value move to the PO that is
  left, or the number and date clear if none is. The value stays, because it
  is what the job is invoiced against, and it came from the deal as much as
  from the paper.
"""

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def quote_family_ids(db: AsyncSession, quotation_id: UUID | None) -> set[UUID]:
    """The quotation plus every revision above and below it — one deal."""
    from app.models.quotation import Quotation

    if not quotation_id:
        return set()
    root = await db.get(Quotation, quotation_id)
    if root is None:
        return {quotation_id}
    seen = {root.id}
    while root.parent_id and root.parent_id not in seen:
        parent = await db.get(Quotation, root.parent_id)
        if parent is None:
            break
        root = parent
        seen.add(root.id)
    family, frontier = {root.id}, {root.id}
    while frontier:
        kids = set((await db.scalars(
            select(Quotation.id).where(Quotation.parent_id.in_(frontier))
        )).all()) - family
        family |= kids
        frontier = kids
    return family | seen


async def existing_po_for_deal(db: AsyncSession, quotation_id: UUID | None,
                               exclude_id: UUID | None = None):
    """The customer PO already filed against this deal, if there is one."""
    from app.models.customer_po import CustomerPO

    family = await quote_family_ids(db, quotation_id)
    if not family:
        return None
    stmt = (select(CustomerPO)
            .where(CustomerPO.quotation_id.in_(family))
            .order_by(CustomerPO.created_at.asc()))
    if exclude_id:
        stmt = stmt.where(CustomerPO.id != exclude_id)
    return (await db.scalars(stmt)).first()


async def _survivor(db: AsyncSession, po):
    """The PO that is left once `po` goes: same project, else same deal.
    Approved first, then the oldest — the one the paperwork already names."""
    from app.models.customer_po import CustomerPO

    stmt = select(CustomerPO).where(CustomerPO.id != po.id)
    if po.project_id:
        stmt = stmt.where(CustomerPO.project_id == po.project_id)
    else:
        family = await quote_family_ids(db, po.quotation_id)
        if not family:
            return None
        stmt = stmt.where(CustomerPO.quotation_id.in_(family))
    rows = (await db.scalars(stmt.order_by(CustomerPO.created_at.asc()))).all()
    return next((r for r in rows if r.status == "approved"), rows[0] if rows else None)


async def release_from_project(db: AsyncSession, po, *, relink_invoices: bool) -> dict:
    """Take back what `po` gave its project, before `po` is deleted.

    With `relink_invoices`, invoices issued against this PO move to the PO
    that is left; with none left they would lose their order, so the delete
    is refused instead. The data-maintenance path passes False — it deletes
    those invoices along with the PO, and says so in its preview.
    """
    from app.models.finance import Invoice
    from app.models.operation import Project

    survivor = await _survivor(db, po)
    out = {"survivor": survivor.number if survivor else None,
           "project_repointed": False, "invoices_moved": 0}

    if relink_invoices:
        invoices = (await db.scalars(
            select(Invoice).where(Invoice.customer_po_id == po.id))).all()
        if invoices and survivor is None:
            nums = ", ".join(sorted(i.number or str(i.id)[:8] for i in invoices))
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Invoice {nums} was issued against this PO, and there is no "
                "other PO on the deal to move it to. Delete or void the invoice "
                "first.")
        for inv in invoices:
            inv.customer_po_id = survivor.id
        out["invoices_moved"] = len(invoices)

    project = await db.get(Project, po.project_id) if po.project_id else None
    if project is not None and project.po_number == po.number:
        # The project's paperwork names this PO. Point it at the one that is
        # left, or clear the number and date if nothing is.
        if survivor is not None:
            project.po_number = survivor.number
            project.po_date = survivor.po_date
            if survivor.total:
                project.po_value = survivor.total
        else:
            project.po_number = None
            project.po_date = None
        out["project_repointed"] = True
    if project is not None:
        out["project_code"] = project.code
    await db.flush()
    return out

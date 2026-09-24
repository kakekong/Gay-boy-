"""Giving a purchasing PO its project — at creation, or any time after.

A PO used to need a project before it could exist. That is the wrong way
round for a real buying desk: stock gets ordered ahead of a job, a vendor's
minimum order covers more than one, a PO goes out while the customer's paper
is still being signed. The order is real before anyone knows which job it
belongs to.

So a PO can now be raised without one, and given one later. Everything that
creating a PO *with* a project used to do has to happen at that later moment
instead, or the PO ends up linked in name only:

* its lines are stamped with the job, which is what the project page and the
  per-job cost roll-up read;
* `project_ids` — every job the PO feeds — is recomputed from those lines;
* it picks up the job's price request if it had none, so cost can be traced;
* the job moves to the purchasing stage, forward only, exactly as a PO raised
  against it would have moved it.

One helper does all of it so the director's direct edit and an approved
request apply the same thing. Which vendor serves which job is the director's
decision, so for everyone else this runs only when the director approves it.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession


async def resolve_project(db: AsyncSession, project_id):
    """The project a caller named, or None. Refuses one that doesn't exist."""
    from fastapi import HTTPException, status

    from app.models.operation import Project

    if project_id in (None, ""):
        return None
    pid = project_id if isinstance(project_id, UUID) else UUID(str(project_id))
    project = await db.get(Project, pid)
    if project is None or getattr(project, "is_deleted", False):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown project")
    return project


async def assign_po_project(db: AsyncSession, po, project) -> dict:
    """Point `po` at `project` (or at nothing) and carry the consequences.

    Lines that named the PO's old project — or no project at all — move with
    it. Lines explicitly on a *different* job stay where they are: on an order
    feeding several jobs those were placed deliberately, and re-pointing the
    header is not a reason to scramble them.
    """
    from app.models.operation import advance_project_status

    old = str(po.project_id) if po.project_id else None
    new = str(project.id) if project is not None else None

    items = []
    moved = 0
    for it in (po.items or []):
        row = dict(it) if isinstance(it, dict) else it
        if isinstance(row, dict):
            line_pid = str(row.get("project_id")) if row.get("project_id") else None
            if line_pid in (None, old):
                row["project_id"] = new
                row["project_code"] = project.code if project is not None else None
                moved += 1
        items.append(row)
    po.items = items
    po.project_id = project.id if project is not None else None

    ids = {str(i.get("project_id")) for i in items
           if isinstance(i, dict) and i.get("project_id")}
    if new:
        ids.add(new)
    po.project_ids = sorted(ids)

    if project is not None:
        # Trace cost back to the job's price request, same order of preference
        # creating the PO would have used: the job's own link, then its
        # quotation's.
        if not po.price_request_id:
            pr_id = project.price_request_id
            if not pr_id and project.quotation_id:
                from app.models.quotation import Quotation
                quote = await db.get(Quotation, project.quotation_id)
                pr_id = quote.price_request_id if quote else None
            if pr_id:
                po.price_request_id = pr_id
        # A PO against a job is what puts the job into purchasing. Forward
        # only — a job already past it is not dragged back.
        if po.status != "cancelled":
            advance_project_status(project, "purchasing")

    await db.flush()
    return {"from": old, "to": new, "lines_moved": moved,
            "project_code": project.code if project is not None else None}

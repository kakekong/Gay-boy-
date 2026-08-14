"""Convert won quotation into project + work order."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.orchestrator import emit
from app.models.operation import Project, WorkOrder
from app.models.quotation import Quotation
from app.models.user import User


async def create_project_from_quotation(
    db: AsyncSession, q: Quotation, user: User
) -> Project:
    from app.services.numbering import next_project_code
    project = Project(
        code=await next_project_code(db),
        customer_id=q.customer_id,
        quotation_id=q.id,
        po_value=q.total,
        status="new",
        created_by=user.id, updated_by=user.id,
    )
    db.add(project)
    await db.flush()
    db.add(WorkOrder(project_id=project.id, code=f"WO-{project.code}-01", stage="receiving"))
    await emit(db, "quotation.won", {"quotation_id": str(q.id), "project_id": str(project.id)})
    return project

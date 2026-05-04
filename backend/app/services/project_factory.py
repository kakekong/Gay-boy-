"""Convert won quotation into project + work order."""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.orchestrator import emit
from app.models.operation import Project, WorkOrder
from app.models.quotation import Quotation
from app.models.user import User


async def create_project_from_quotation(
    db: AsyncSession, q: Quotation, user: User
) -> Project:
    year = datetime.utcnow().year
    prefix = f"PRJ-{year}-"
    seq = await db.scalar(
        select(func.count(Project.id)).where(Project.code.like(f"{prefix}%"))
    ) or 0
    project = Project(
        code=f"{prefix}{seq + 1:04d}",
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

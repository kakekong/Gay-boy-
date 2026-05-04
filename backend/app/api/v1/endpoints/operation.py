"""Operation: projects, work orders, drawings, deliveries."""

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.operation import Project
from app.models.user import User

router = APIRouter()


@router.get("/projects")
async def list_projects(db: AsyncSession = Depends(get_db),
                        _user: User = Depends(get_current_user)):
    rows = (await db.scalars(
        select(Project).where(Project.is_deleted.is_(False)).order_by(Project.created_at.desc())
    )).all()
    return [
        {
            "id": str(p.id), "code": p.code, "customer_id": str(p.customer_id),
            "status": p.status, "po_value": float(p.po_value),
            "target_delivery": p.target_delivery, "actual_delivery": p.actual_delivery,
            "margin_estimate": float(p.margin_estimate), "margin_actual": float(p.margin_actual),
        } for p in rows
    ]


@router.get("/projects/{project_id}")
async def get_project(project_id: UUID,
                      db: AsyncSession = Depends(get_db),
                      _user: User = Depends(get_current_user)):
    p = await db.get(Project, project_id)
    if not p:
        return None
    return {
        "id": str(p.id), "code": p.code, "status": p.status,
        "po_number": p.po_number, "po_value": float(p.po_value),
    }


@router.post("/projects/{project_id}/delivery")
async def create_delivery(project_id: UUID, _user: User = Depends(get_current_user)):
    return {"project_id": str(project_id), "status": "todo"}

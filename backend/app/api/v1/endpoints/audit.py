"""Audit log viewer — admin / director only."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.permissions import Role, require, require_min
from app.models.audit import AuditLog
from app.models.user import User

router = APIRouter(
    # Internal-only surface. External portal accounts (customer /
    # supplier, hierarchy tier 0) must never reach the CRM, pricing,
    # calendar or notification data — they have /portal/* instead.
    dependencies=[Depends(require_min(Role.SALES))]
)
_admin_or_director = require(Role.ADMIN, Role.DIRECTOR)


@router.get("")
async def list_audit(
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_admin_or_director),
    entity: str | None = None,
    actor_id: UUID | None = None,
    action: str | None = None,
    limit: int = Query(100, ge=1, le=500),
):
    stmt = select(AuditLog).order_by(AuditLog.occurred_at.desc()).limit(limit)
    if entity:
        stmt = stmt.where(AuditLog.entity == entity)
    if actor_id:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)

    rows = (await db.scalars(stmt)).all()
    # Resolve actor names
    actor_ids = {r.actor_id for r in rows if r.actor_id}
    actors: dict[UUID, User] = {}
    if actor_ids:
        users = (await db.scalars(select(User).where(User.id.in_(actor_ids)))).all()
        actors = {u.id: u for u in users}

    return [
        {
            "id": str(r.id),
            "actor_id": str(r.actor_id) if r.actor_id else None,
            "actor_name": actors.get(r.actor_id).full_name if r.actor_id and actors.get(r.actor_id) else None,
            "actor_role": actors.get(r.actor_id).role if r.actor_id and actors.get(r.actor_id) else None,
            "action": r.action,
            "entity": r.entity,
            "entity_id": str(r.entity_id),
            "before": r.before,
            "after": r.after,
            "occurred_at": r.occurred_at,
        }
        for r in rows
    ]


@router.get("/entities")
async def list_entities(
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_admin_or_director),
):
    """Distinct entity types in the audit log."""
    rows = await db.scalars(select(AuditLog.entity).distinct())
    return sorted({e for e in rows if e})


@router.get("/actions")
async def list_actions(
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_admin_or_director),
):
    rows = await db.scalars(select(AuditLog.action).distinct())
    return sorted({a for a in rows if a})

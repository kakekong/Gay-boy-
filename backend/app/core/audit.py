"""Tiny audit helper. Call from any endpoint that mutates an entity.

Records to the audit_log table:
    actor, action, entity, entity_id, before, after, occurred_at.
The viewer endpoint reads this table.
"""

import json
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.user import User


def _json_safe(v: Any) -> Any:
    """Make values JSON-serializable for the JSONB before/after columns."""
    if v is None:
        return None
    if isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, dict):
        return {k: _json_safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_json_safe(x) for x in v]
    try:
        return str(v)
    except Exception:
        return None


def _to_dict(d: dict | None) -> dict:
    return {k: _json_safe(v) for k, v in (d or {}).items()}


async def record(
    db: AsyncSession,
    *,
    actor: User | None,
    action: str,
    entity: str,
    entity_id: UUID | str | None,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    """Fire-and-forget audit row. Never raises (audit must not block work)."""
    try:
        db.add(AuditLog(
            actor_id=actor.id if actor else None,
            action=action,
            entity=entity,
            entity_id=entity_id,
            before=_to_dict(before),
            after=_to_dict(after),
        ))
    except Exception:
        pass

"""Comment / chat threads on quotations and POs (customer + supplier).

A lightweight discussion thread keyed by (owner_type, owner_id). Any
authenticated internal user can read + post; the same role boundaries that
gate the parent entity still apply at the entity's own endpoints.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.comment import EntityComment
from app.models.user import User

router = APIRouter()

ALLOWED_OWNERS = {"quotation", "customer_po", "supplier_po"}


class CommentIn(BaseModel):
    owner_type: str
    owner_id: UUID
    body: str


def _out(c: EntityComment, author: User | None) -> dict:
    return {
        "id": str(c.id),
        "owner_type": c.owner_type,
        "owner_id": str(c.owner_id),
        "body": c.body,
        "author_id": str(c.author_id) if c.author_id else None,
        "author_name": author.full_name if author else None,
        "author_role": author.role if author else None,
        "created_at": c.created_at,
    }


@router.get("")
async def list_comments(
    owner_type: str,
    owner_id: UUID,
    db: AsyncSession = Depends(get_db),
    _me: User = Depends(get_current_user),
):
    if owner_type not in ALLOWED_OWNERS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid owner_type")
    rows = (await db.scalars(
        select(EntityComment)
        .where(EntityComment.owner_type == owner_type, EntityComment.owner_id == owner_id)
        .order_by(EntityComment.created_at.asc())
    )).all()
    # Batch-load authors
    author_ids = {c.author_id for c in rows if c.author_id}
    authors: dict[UUID, User] = {}
    if author_ids:
        for u in (await db.scalars(select(User).where(User.id.in_(author_ids)))).all():
            authors[u.id] = u
    return [_out(c, authors.get(c.author_id) if c.author_id else None) for c in rows]


@router.post("", status_code=201)
async def add_comment(
    payload: CommentIn,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    if payload.owner_type not in ALLOWED_OWNERS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid owner_type")
    body = (payload.body or "").strip()
    if not body:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Comment cannot be empty")
    c = EntityComment(
        owner_type=payload.owner_type,
        owner_id=payload.owner_id,
        author_id=me.id,
        body=body,
    )
    db.add(c)
    await db.flush()
    return _out(c, me)

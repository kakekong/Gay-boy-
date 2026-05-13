"""Tag management — HR + Director can create and assign tags.

Tags are reusable labels with colors. They're scoped (currently 'employee'
only, but the column supports adding customer/quotation tagging later).
Assignment is a many-to-many via user_tag_links.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.permissions import Role, require
from app.models.tag import Tag, UserTagLink
from app.models.user import User

router = APIRouter()
_hr_or_director = require(Role.HR, Role.DIRECTOR)


ALLOWED_COLORS = [
    "brand", "emerald", "amber", "violet", "red",
    "ink", "blue", "cyan", "lime", "teal", "orange", "pink",
]


class TagIn(BaseModel):
    name: str
    color: str = "brand"
    description: str | None = None
    scope: str = "employee"


class TagPatch(BaseModel):
    name: str | None = None
    color: str | None = None
    description: str | None = None


class TagOut(BaseModel):
    id: UUID
    name: str
    color: str
    description: str | None
    scope: str
    usage_count: int = 0

    model_config = {"from_attributes": True}


# ─── Tag CRUD ────────────────────────────────────────────────────────────────

@router.get("", response_model=list[TagOut])
async def list_tags(
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_hr_or_director),
    scope: str | None = None,
):
    stmt = select(Tag).order_by(Tag.name.asc())
    if scope:
        stmt = stmt.where(Tag.scope == scope)
    rows = (await db.scalars(stmt)).all()
    # usage counts
    counts: dict[UUID, int] = {}
    if rows:
        ids = [r.id for r in rows]
        result = await db.execute(
            select(UserTagLink.tag_id, func.count(UserTagLink.user_id))
            .where(UserTagLink.tag_id.in_(ids))
            .group_by(UserTagLink.tag_id)
        )
        counts = {tid: cnt for tid, cnt in result.all()}
    return [
        TagOut(
            id=r.id, name=r.name, color=r.color, description=r.description,
            scope=r.scope, usage_count=counts.get(r.id, 0),
        )
        for r in rows
    ]


@router.post("", response_model=TagOut, status_code=201)
async def create_tag(
    payload: TagIn,
    db: AsyncSession = Depends(get_db),
    u: User = Depends(_hr_or_director),
):
    if payload.color not in ALLOWED_COLORS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Color must be one of: {', '.join(ALLOWED_COLORS)}",
        )
    if not payload.name.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Name required.")
    existing = await db.scalar(select(Tag).where(Tag.name == payload.name.strip()))
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Tag name already exists.")
    t = Tag(
        name=payload.name.strip(),
        color=payload.color,
        description=payload.description,
        scope=payload.scope,
        created_by=u.id,
    )
    db.add(t)
    await db.flush()
    return TagOut(id=t.id, name=t.name, color=t.color, description=t.description,
                  scope=t.scope, usage_count=0)


@router.patch("/{tag_id}", response_model=TagOut)
async def update_tag(
    tag_id: UUID,
    payload: TagPatch,
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_hr_or_director),
):
    t = await db.get(Tag, tag_id)
    if not t:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    data = payload.model_dump(exclude_unset=True)
    if "color" in data and data["color"] not in ALLOWED_COLORS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid color.")
    if "name" in data:
        if not data["name"].strip():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Name required.")
        dup = await db.scalar(
            select(Tag).where(Tag.name == data["name"].strip(), Tag.id != tag_id)
        )
        if dup:
            raise HTTPException(status.HTTP_409_CONFLICT, "Tag name already exists.")
        data["name"] = data["name"].strip()
    for k, v in data.items():
        setattr(t, k, v)
    await db.flush()
    return TagOut(id=t.id, name=t.name, color=t.color, description=t.description,
                  scope=t.scope, usage_count=0)


@router.delete("/{tag_id}", status_code=204)
async def delete_tag(
    tag_id: UUID,
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_hr_or_director),
):
    t = await db.get(Tag, tag_id)
    if not t:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    # cascade in DB will remove all links
    await db.delete(t)
    return None


# ─── User ↔ tag attachment ──────────────────────────────────────────────────

class AttachIn(BaseModel):
    tag_id: UUID


@router.get("/users/{user_id}", response_model=list[TagOut])
async def list_user_tags(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_hr_or_director),
):
    rows = (await db.scalars(
        select(Tag).join(UserTagLink, UserTagLink.tag_id == Tag.id)
        .where(UserTagLink.user_id == user_id)
        .order_by(Tag.name.asc())
    )).all()
    return [
        TagOut(id=r.id, name=r.name, color=r.color, description=r.description,
               scope=r.scope, usage_count=0)
        for r in rows
    ]


@router.post("/users/{user_id}", status_code=201)
async def attach_tag(
    user_id: UUID,
    payload: AttachIn,
    db: AsyncSession = Depends(get_db),
    u: User = Depends(_hr_or_director),
):
    user = await db.get(User, user_id)
    tag = await db.get(Tag, payload.tag_id)
    if not user or not tag:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User or tag not found")

    existing = await db.scalar(
        select(UserTagLink).where(
            UserTagLink.user_id == user_id,
            UserTagLink.tag_id == payload.tag_id,
        )
    )
    if existing:
        return {"ok": True, "already_attached": True}
    db.add(UserTagLink(user_id=user_id, tag_id=payload.tag_id, created_by=u.id))
    await db.flush()
    return {"ok": True}


@router.delete("/users/{user_id}/{tag_id}", status_code=204)
async def detach_tag(
    user_id: UUID,
    tag_id: UUID,
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_hr_or_director),
):
    await db.execute(
        delete(UserTagLink).where(
            UserTagLink.user_id == user_id, UserTagLink.tag_id == tag_id
        )
    )
    return None

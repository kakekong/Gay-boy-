"""Internal chat — direct messages between employees.

All authenticated users can chat with each other. Membership in a channel
is required to read/write its messages.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.permissions import Role
from app.models.chat import ChatChannel, ChatChannelMember, ChatMessage
from app.models.user import User

router = APIRouter()


# ─── Department / cross-department governance ─────────────────────────────────
# A "department" is a role group. Cross-department chats (members spanning more
# than one department) may only be started by a director or HR; the director can
# chat unrestricted, and silently monitor any cross-department channel.

_DEPARTMENTS = {
    "sales": "sales", "finance": "finance", "hr": "hr",
    "purchasing": "purchasing", "admin": "admin",
    "manager": "management", "director": "management",
    "customer": "external", "supplier": "external",
}


def _dept(role: str | None) -> str:
    return _DEPARTMENTS.get(role or "", role or "unknown")


def _is_cross_dept(roles) -> bool:
    return len({_dept(r) for r in roles}) > 1


def _may_start_cross_dept(role: str | None) -> bool:
    # Director, HR and managers may start cross-department chats. When HR or a
    # manager does, the director is notified and can view it silently.
    return role in ("director", "hr", "manager")


async def _channel_member_roles(db: AsyncSession, channel_id: UUID) -> list[str]:
    rows = (await db.execute(
        select(User.role)
        .join(ChatChannelMember, ChatChannelMember.user_id == User.id)
        .where(ChatChannelMember.channel_id == channel_id)
    )).all()
    return [r[0] for r in rows]


# ─── Schemas ─────────────────────────────────────────────────────────────────

class MessageIn(BaseModel):
    body: str


class MessageEdit(BaseModel):
    body: str


# ─── Helpers ─────────────────────────────────────────────────────────────────

async def _is_member(db: AsyncSession, channel_id: UUID, user_id: UUID) -> bool:
    return bool(await db.scalar(
        select(ChatChannelMember).where(
            ChatChannelMember.channel_id == channel_id,
            ChatChannelMember.user_id == user_id,
        )
    ))


async def _ensure_member(db: AsyncSession, channel_id: UUID, user_id: UUID) -> ChatChannelMember:
    m = await db.scalar(
        select(ChatChannelMember).where(
            ChatChannelMember.channel_id == channel_id,
            ChatChannelMember.user_id == user_id,
        )
    )
    if not m:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a member of this channel")
    return m


async def _ensure_can_read(db: AsyncSession, channel_id: UUID, me: User) -> None:
    """Membership is required to read a channel — except the director, who can
    silently monitor any channel without joining (no read-receipt is written)."""
    if Role(me.role) == Role.DIRECTOR:
        return
    await _ensure_member(db, channel_id, me.id)


# ─── Lightweight contact list (everyone can read) ────────────────────────────

@router.get("/contacts")
async def contacts(db: AsyncSession = Depends(get_db),
                   me: User = Depends(get_current_user)):
    """Minimal user list available to any logged-in user, for picking a chat partner."""
    rows = (await db.scalars(
        select(User).where(User.is_active.is_(True), User.id != me.id)
        .order_by(User.full_name.asc())
    )).all()
    return [
        {"id": str(u.id), "full_name": u.full_name, "role": u.role, "email": u.email}
        for u in rows
    ]


# ─── Channels (DM and groups) ────────────────────────────────────────────────

@router.get("/channels")
async def list_channels(db: AsyncSession = Depends(get_db),
                        me: User = Depends(get_current_user)):
    """All channels the current user is a member of, with last-message + unread."""
    member_rows = (await db.execute(
        select(ChatChannel, ChatChannelMember)
        .join(ChatChannelMember, ChatChannelMember.channel_id == ChatChannel.id)
        .where(ChatChannelMember.user_id == me.id)
        .order_by(ChatChannel.created_at.desc())
    )).all()

    out: list[dict] = []
    for ch, member in member_rows:
        # Last message
        last_msg = await db.scalar(
            select(ChatMessage)
            .where(ChatMessage.channel_id == ch.id, ChatMessage.deleted_at.is_(None))
            .order_by(ChatMessage.created_at.desc())
            .limit(1)
        )
        # Unread count
        unread = 0
        if last_msg:
            cutoff = member.last_read_at
            stmt = (
                select(func.count(ChatMessage.id))
                .where(
                    ChatMessage.channel_id == ch.id,
                    ChatMessage.user_id != me.id,
                    ChatMessage.deleted_at.is_(None),
                )
            )
            if cutoff:
                stmt = stmt.where(ChatMessage.created_at > cutoff)
            unread = await db.scalar(stmt) or 0

        # Other members (for DM titling)
        others = (await db.execute(
            select(User)
            .join(ChatChannelMember, ChatChannelMember.user_id == User.id)
            .where(
                ChatChannelMember.channel_id == ch.id,
                ChatChannelMember.user_id != me.id,
            )
        )).scalars().all()
        title = ch.name or (others[0].full_name if others else "(self)")

        out.append({
            "id": str(ch.id),
            "kind": ch.kind,
            "title": title,
            "members": [
                {"id": str(u.id), "full_name": u.full_name, "role": u.role}
                for u in others
            ],
            "last_message": {
                "body": last_msg.body if last_msg else None,
                "user_id": str(last_msg.user_id) if last_msg and last_msg.user_id else None,
                "at": last_msg.created_at if last_msg else None,
            } if last_msg else None,
            "unread": unread,
        })
    # Sort by last message recency (channels with no msgs go last)
    out.sort(key=lambda c: (c["last_message"]["at"] if c["last_message"] else datetime.min.replace(tzinfo=UTC)), reverse=True)
    return out


@router.get("/monitor")
async def monitor_cross_dept(db: AsyncSession = Depends(get_db),
                            me: User = Depends(get_current_user)):
    """Director-only: every cross-department channel/DM, so the director can
    silently oversee chats that span teams — including ones they're not in.
    Reading a channel from here writes no read-receipt and adds no membership."""
    if Role(me.role) != Role.DIRECTOR:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Director only")
    channels = (await db.scalars(
        select(ChatChannel).order_by(ChatChannel.created_at.desc())
    )).all()
    out: list[dict] = []
    for ch in channels:
        members = (await db.execute(
            select(User).join(ChatChannelMember, ChatChannelMember.user_id == User.id)
            .where(ChatChannelMember.channel_id == ch.id)
        )).scalars().all()
        if not _is_cross_dept([u.role for u in members]):
            continue
        creator = await db.get(User, ch.created_by) if ch.created_by else None
        last_msg = await db.scalar(
            select(ChatMessage).where(
                ChatMessage.channel_id == ch.id, ChatMessage.deleted_at.is_(None)
            ).order_by(ChatMessage.created_at.desc()).limit(1)
        )
        out.append({
            "id": str(ch.id),
            "kind": ch.kind,
            "title": ch.name or ", ".join(u.full_name for u in members),
            "created_by_name": creator.full_name if creator else None,
            "created_by_role": creator.role if creator else None,
            "members": [
                {"id": str(u.id), "full_name": u.full_name, "role": u.role}
                for u in members
            ],
            "last_message": {
                "body": last_msg.body, "at": last_msg.created_at,
            } if last_msg else None,
        })
    return out


@router.post("/dm/{user_id}")
async def get_or_create_dm(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    """Find or create a 1:1 DM channel between current user and target."""
    if user_id == me.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot DM yourself")
    other = await db.get(User, user_id)
    if not other or not other.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    # Cross-department DMs may only be started by a director or HR.
    if _is_cross_dept([me.role, other.role]) and not _may_start_cross_dept(me.role):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Cross-department chats can only be started by a director, manager, or HR.",
        )

    # Find a DM channel where both are members
    a_member = ChatChannelMember.__table__.alias("a")
    b_member = ChatChannelMember.__table__.alias("b")
    existing_id = await db.scalar(
        select(ChatChannel.id)
        .join(a_member, a_member.c.channel_id == ChatChannel.id)
        .join(b_member, b_member.c.channel_id == ChatChannel.id)
        .where(
            ChatChannel.kind == "dm",
            a_member.c.user_id == me.id,
            b_member.c.user_id == user_id,
        )
        .limit(1)
    )
    if existing_id:
        return {"id": str(existing_id), "kind": "dm", "title": other.full_name}

    ch = ChatChannel(kind="dm", created_by=me.id)
    db.add(ch)
    await db.flush()
    db.add_all([
        ChatChannelMember(channel_id=ch.id, user_id=me.id),
        ChatChannelMember(channel_id=ch.id, user_id=user_id),
    ])
    await db.flush()
    return {"id": str(ch.id), "kind": "dm", "title": other.full_name}


# ─── Messages ────────────────────────────────────────────────────────────────

@router.get("/channels/{channel_id}/messages")
async def list_messages(
    channel_id: UUID,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
    limit: int = Query(100, ge=1, le=500),
):
    await _ensure_can_read(db, channel_id, me)
    rows = (await db.scalars(
        select(ChatMessage)
        .where(ChatMessage.channel_id == channel_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
    )).all()
    rows = list(reversed(rows))

    # Resolve user names in one query
    user_ids = {m.user_id for m in rows if m.user_id}
    users: dict[UUID, User] = {}
    if user_ids:
        result = (await db.scalars(select(User).where(User.id.in_(user_ids)))).all()
        users = {u.id: u for u in result}

    return [
        {
            "id": str(m.id),
            "channel_id": str(m.channel_id),
            "user_id": str(m.user_id) if m.user_id else None,
            "user_name": users.get(m.user_id).full_name if m.user_id and users.get(m.user_id) else None,
            "body": m.body if not m.deleted_at else "[message deleted]",
            "created_at": m.created_at,
            "edited_at": m.edited_at,
            "deleted": bool(m.deleted_at),
            "is_mine": m.user_id == me.id,
        }
        for m in rows
    ]


@router.post("/channels/{channel_id}/messages", status_code=201)
async def send_message(
    channel_id: UUID,
    payload: MessageIn,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    await _ensure_member(db, channel_id, me.id)
    body = (payload.body or "").strip()
    if not body:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty message")
    if len(body) > 4000:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Message too long (max 4000)")
    m = ChatMessage(channel_id=channel_id, user_id=me.id, body=body)
    db.add(m)
    await db.flush()
    # Auto-mark current user's read pointer to "now"
    member = await db.scalar(
        select(ChatChannelMember).where(
            ChatChannelMember.channel_id == channel_id,
            ChatChannelMember.user_id == me.id,
        )
    )
    if member:
        member.last_read_at = datetime.now(UTC)
    return {
        "id": str(m.id),
        "channel_id": str(channel_id),
        "user_id": str(me.id),
        "user_name": me.full_name,
        "body": m.body,
        "created_at": m.created_at,
        "is_mine": True,
    }


@router.patch("/messages/{message_id}")
async def edit_message(
    message_id: UUID,
    payload: MessageEdit,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    m = await db.get(ChatMessage, message_id)
    if not m or m.deleted_at:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if m.user_id != me.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Can only edit your own messages")
    body = (payload.body or "").strip()
    if not body:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty message")
    m.body = body
    m.edited_at = datetime.now(UTC)
    return {"id": str(m.id), "edited_at": m.edited_at, "body": m.body}


@router.delete("/messages/{message_id}", status_code=204)
async def delete_message(
    message_id: UUID,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    m = await db.get(ChatMessage, message_id)
    if not m or m.deleted_at:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if m.user_id != me.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN)
    m.deleted_at = datetime.now(UTC)
    return None


@router.post("/channels/{channel_id}/read")
async def mark_read(
    channel_id: UUID,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    member = await _ensure_member(db, channel_id, me.id)
    member.last_read_at = datetime.now(UTC)
    return {"ok": True}


@router.get("/unread")
async def unread_total(
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    """Sum of unread messages across all the user's channels."""
    # All channels user is a member of
    members = (await db.scalars(
        select(ChatChannelMember).where(ChatChannelMember.user_id == me.id)
    )).all()
    total = 0
    for mem in members:
        stmt = (
            select(func.count(ChatMessage.id))
            .where(
                ChatMessage.channel_id == mem.channel_id,
                ChatMessage.user_id != me.id,
                ChatMessage.deleted_at.is_(None),
            )
        )
        if mem.last_read_at:
            stmt = stmt.where(ChatMessage.created_at > mem.last_read_at)
        total += await db.scalar(stmt) or 0
    return {"unread": total}


# ─── Group channels ──────────────────────────────────────────────────────────

class ChannelCreate(BaseModel):
    name: str
    member_ids: list[UUID] = []


@router.post("/channels", status_code=201)
async def create_channel(
    payload: ChannelCreate,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Channel name required")

    # Resolve the active members up front so we can check departments.
    member_set = set(payload.member_ids) | {me.id}
    members: list[User] = []
    for uid in member_set:
        u = await db.get(User, uid)
        if u and u.is_active:
            members.append(u)
    roles = [u.role for u in members]
    if _is_cross_dept(roles) and not _may_start_cross_dept(me.role):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Cross-department channels can only be started by a director, manager, or HR.",
        )

    ch = ChatChannel(name=name, kind="channel", created_by=me.id)
    db.add(ch)
    await db.flush()
    for u in members:
        db.add(ChatChannelMember(channel_id=ch.id, user_id=u.id))
    await db.flush()
    return {"id": str(ch.id), "name": ch.name, "kind": "channel"}


@router.get("/channels/{channel_id}/members")
async def list_members(
    channel_id: UUID,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    await _ensure_can_read(db, channel_id, me)
    rows = (await db.execute(
        select(User)
        .join(ChatChannelMember, ChatChannelMember.user_id == User.id)
        .where(ChatChannelMember.channel_id == channel_id)
        .order_by(User.full_name.asc())
    )).scalars().all()
    return [
        {"id": str(u.id), "full_name": u.full_name, "role": u.role}
        for u in rows
    ]


class MemberAdd(BaseModel):
    user_id: UUID


@router.post("/channels/{channel_id}/members", status_code=201)
async def add_member(
    channel_id: UUID,
    payload: MemberAdd,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    await _ensure_member(db, channel_id, me.id)
    ch = await db.get(ChatChannel, channel_id)
    if not ch or ch.kind != "channel":
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Can only add members to group channels")
    existing = await db.scalar(
        select(ChatChannelMember).where(
            ChatChannelMember.channel_id == channel_id,
            ChatChannelMember.user_id == payload.user_id,
        )
    )
    if existing:
        return {"ok": True, "already_member": True}
    # Adding someone from another department turns this into a cross-department
    # channel — same gate as creating one.
    new_user = await db.get(User, payload.user_id)
    if new_user:
        roles = await _channel_member_roles(db, channel_id)
        roles.append(new_user.role)
        if _is_cross_dept(roles) and not _may_start_cross_dept(me.role):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Only a director, manager, or HR can add a member from another department.",
            )
    db.add(ChatChannelMember(channel_id=channel_id, user_id=payload.user_id))
    await db.flush()
    return {"ok": True}


@router.delete("/channels/{channel_id}/members/{user_id}", status_code=204)
async def remove_member(
    channel_id: UUID,
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    await _ensure_member(db, channel_id, me.id)
    ch = await db.get(ChatChannel, channel_id)
    if not ch or ch.kind != "channel":
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Can only manage members of group channels")
    # Only the creator can remove others; anyone can remove themselves
    if user_id != me.id and ch.created_by != me.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Only the channel creator can remove other members")
    from sqlalchemy import delete as sqldelete
    await db.execute(
        sqldelete(ChatChannelMember).where(
            ChatChannelMember.channel_id == channel_id,
            ChatChannelMember.user_id == user_id,
        )
    )
    return None

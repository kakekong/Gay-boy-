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
from app.core.permissions import Role, require_min
from app.models.chat import ChatChannel, ChatChannelMember, ChatMessage
from app.models.user import User
from app.services.chat_policy import (
    ForwardIn,
    channel_member_roles as _channel_member_roles,
    deliver_forward,
    excerpt,
    existing_dm_id,
    is_cross_dept as _is_cross_dept,
    may_start_cross_dept as _may_start_cross_dept,
    resolve_dm,
)

router = APIRouter(
    # Internal-only surface. External portal accounts (customer /
    # supplier, hierarchy tier 0) must never reach the CRM, pricing,
    # calendar or notification data — they have /portal/* instead.
    dependencies=[Depends(require_min(Role.SALES))]
)

# Cross-department governance (which chats may span teams) lives in
# services/chat_policy.py, because forwarding a message into a new DM has to
# apply the same rule from the discussion-thread endpoints too.


# ─── Schemas ─────────────────────────────────────────────────────────────────

class MessageIn(BaseModel):
    body: str
    # Quoting another message in this channel, WhatsApp-style.
    reply_to_id: UUID | None = None


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


def _msg_out(m: ChatMessage, me: User, names: dict[UUID, str],
             quoted: ChatMessage | None) -> dict:
    """One message on the wire, including what it quotes and where it came from.

    The forward carries the *original* author's name but never the channel or
    document it was forwarded out of — see the comment on the model. A reader
    learns who wrote it, not where they wrote it.
    """
    return {
        "id": str(m.id),
        "channel_id": str(m.channel_id),
        "user_id": str(m.user_id) if m.user_id else None,
        "user_name": names.get(m.user_id) if m.user_id else None,
        "body": m.body if not m.deleted_at else "[message deleted]",
        "created_at": m.created_at,
        "edited_at": m.edited_at,
        "deleted": bool(m.deleted_at),
        "is_mine": m.user_id == me.id,
        "reply_to": {
            "id": str(quoted.id),
            "user_name": names.get(quoted.user_id) if quoted.user_id else None,
            "body": excerpt(quoted.body) if not quoted.deleted_at else "[message deleted]",
            "deleted": bool(quoted.deleted_at),
            "is_mine": quoted.user_id == me.id,
        } if quoted else None,
        "forwarded": {
            "author_name": names.get(m.forwarded_from_author_id)
            if m.forwarded_from_author_id else None,
        } if m.forwarded_from_kind else None,
    }


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
    """Find or create a 1:1 DM channel between current user and target.

    The department gate (and the reuse-an-existing-DM rule) lives in
    `resolve_dm`, shared with forwarding.
    """
    other = await db.get(User, user_id)
    if not other:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    channel_id = await resolve_dm(db, me, other)
    return {"id": str(channel_id), "kind": "dm", "title": other.full_name}


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

    # Quoted messages may sit outside the window we just loaded (replying to
    # something from last week), so fetch the missing ones by id.
    by_id = {m.id: m for m in rows}
    wanted_quotes = {m.reply_to_id for m in rows if m.reply_to_id} - set(by_id)
    if wanted_quotes:
        for q in (await db.scalars(
            select(ChatMessage).where(
                ChatMessage.id.in_(wanted_quotes),
                # Belt and braces: a quote must never pull in another channel.
                ChatMessage.channel_id == channel_id,
            )
        )).all():
            by_id[q.id] = q

    # Resolve every name we need in one query: authors, quoted authors, and the
    # original author of anything forwarded in.
    user_ids = {m.user_id for m in by_id.values() if m.user_id}
    user_ids |= {m.forwarded_from_author_id for m in rows if m.forwarded_from_author_id}
    names: dict[UUID, str] = {}
    if user_ids:
        for u in (await db.scalars(select(User).where(User.id.in_(user_ids)))).all():
            names[u.id] = u.full_name

    return [
        _msg_out(m, me, names, by_id.get(m.reply_to_id) if m.reply_to_id else None)
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

    # A quote is only ever a message from this same channel. Allowing any id
    # would let someone copy a line out of a conversation they were never in
    # simply by quoting it into one they are.
    quoted: ChatMessage | None = None
    if payload.reply_to_id:
        quoted = await db.get(ChatMessage, payload.reply_to_id)
        if not quoted or quoted.channel_id != channel_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "You can only reply to a message in this conversation")

    m = ChatMessage(channel_id=channel_id, user_id=me.id, body=body,
                    reply_to_id=quoted.id if quoted else None)
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

    # Instant device push to the other members (fire-and-forget so the
    # send stays snappy — the task opens its own DB session).
    from app.services.webpush import fire_and_forget, notify_chat_message
    channel = await db.get(ChatChannel, channel_id)
    fire_and_forget(notify_chat_message(
        channel_id=channel_id,
        sender_id=me.id,
        sender_name=me.full_name,
        channel_name=channel.name if channel else None,
        text=body,
    ))

    names = {me.id: me.full_name}
    if quoted and quoted.user_id and quoted.user_id != me.id:
        author = await db.get(User, quoted.user_id)
        if author:
            names[author.id] = author.full_name
    return _msg_out(m, me, names, quoted)


@router.get("/forward-targets")
async def forward_targets(
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    """Where the current user may forward something.

    Shared by both conversation surfaces. `can_dm` is false for a colleague in
    another department when the current user isn't allowed to open that
    conversation — the picker greys them out rather than letting the forward
    fail on send.
    """
    rows = (await db.execute(
        select(ChatChannel)
        .join(ChatChannelMember, ChatChannelMember.channel_id == ChatChannel.id)
        .where(ChatChannelMember.user_id == me.id)
        .order_by(ChatChannel.created_at.desc())
    )).scalars().all()

    channels: list[dict] = []
    for ch in rows:
        others = (await db.execute(
            select(User)
            .join(ChatChannelMember, ChatChannelMember.user_id == User.id)
            .where(ChatChannelMember.channel_id == ch.id,
                   ChatChannelMember.user_id != me.id)
        )).scalars().all()
        channels.append({
            "id": str(ch.id),
            "kind": ch.kind,
            "title": ch.name or (others[0].full_name if others else "(self)"),
            "member_count": len(others) + 1,
        })

    people = (await db.scalars(
        select(User).where(
            User.is_active.is_(True),
            User.id != me.id,
            User.role.notin_([Role.CUSTOMER.value, Role.SUPPLIER.value]),
        ).order_by(User.full_name)
    )).all()
    contacts: list[dict] = []
    for u in people:
        dm = await existing_dm_id(db, me.id, u.id)
        contacts.append({
            "id": str(u.id),
            "full_name": u.full_name,
            "role": u.role,
            "channel_id": str(dm) if dm else None,
            "can_dm": bool(dm) or not _is_cross_dept([me.role, u.role])
            or _may_start_cross_dept(me.role),
        })
    return {"channels": channels, "contacts": contacts}


@router.post("/messages/{message_id}/forward")
async def forward_message(
    message_id: UUID,
    payload: ForwardIn,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    """Pass a chat message on to other conversations.

    Reading the source is enough to forward it, so the director's monitor view
    can pass something on — but `deliver_forward` still requires membership of
    every destination, so nothing can be posted into a channel they never
    joined.
    """
    src = await db.get(ChatMessage, message_id)
    if not src or src.deleted_at:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found")
    await _ensure_can_read(db, src.channel_id, me)

    # Forwarding a forward keeps pointing at the true author, the way the
    # attribution on a paper trail should.
    return await deliver_forward(
        db, me=me, body=src.body,
        origin_kind=src.forwarded_from_kind or "chat",
        origin_id=src.forwarded_from_id or src.id,
        origin_author_id=src.forwarded_from_author_id or src.user_id,
        targets=payload,
    )


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

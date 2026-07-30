"""Who may talk to whom, and how a message gets copied somewhere else.

Two things live here because both conversation surfaces need them — the chat
page (`endpoints/chat.py`) and the discussion thread on a document
(`endpoints/comments.py`):

* **Department rules.** A conversation that spans teams may only be started by
  a director, manager or HR. Forwarding has to respect that: dropping a copy
  into a new DM with someone in another department is starting a
  cross-department conversation, whatever button it was reached from.

* **Forward delivery.** A forward always lands in *chat*, never on another
  document. That is deliberate — a chat is a place a person definitely has, so
  "send this to Budi" works whether or not Budi could open the quotation the
  message came from. It is also the same act as an @mention: the sender chooses
  to share the text, and only the text.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatChannel, ChatChannelMember, ChatMessage
from app.models.user import User

# A "department" is a role group.
DEPARTMENTS = {
    "sales": "sales", "finance": "finance", "hr": "hr",
    "purchasing": "purchasing", "admin": "admin",
    "manager": "management", "director": "management",
    "customer": "external", "supplier": "external",
}

# How much of a quoted message the preview carries. Long enough to recognise
# the message, short enough that a quote can't smuggle a whole thread into a
# conversation someone was never part of.
QUOTE_EXCERPT = 180

# Forwarding is for passing something on, not broadcasting it.
MAX_FORWARD_TARGETS = 10


def dept(role: str | None) -> str:
    return DEPARTMENTS.get(role or "", role or "unknown")


def is_cross_dept(roles) -> bool:
    return len({dept(r) for r in roles}) > 1


def may_start_cross_dept(role: str | None) -> bool:
    # Director, HR and managers may start cross-department chats. When HR or a
    # manager does, the director is notified and can view it silently.
    return role in ("director", "hr", "manager")


async def channel_member_roles(db: AsyncSession, channel_id: UUID) -> list[str]:
    rows = (await db.execute(
        select(User.role)
        .join(ChatChannelMember, ChatChannelMember.user_id == User.id)
        .where(ChatChannelMember.channel_id == channel_id)
    )).all()
    return [r[0] for r in rows]


async def is_member(db: AsyncSession, channel_id: UUID, user_id: UUID) -> bool:
    return bool(await db.scalar(
        select(ChatChannelMember.user_id).where(
            ChatChannelMember.channel_id == channel_id,
            ChatChannelMember.user_id == user_id,
        )
    ))


async def existing_dm_id(db: AsyncSession, a: UUID, b: UUID) -> UUID | None:
    a_member = ChatChannelMember.__table__.alias("a")
    b_member = ChatChannelMember.__table__.alias("b")
    return await db.scalar(
        select(ChatChannel.id)
        .join(a_member, a_member.c.channel_id == ChatChannel.id)
        .join(b_member, b_member.c.channel_id == ChatChannel.id)
        .where(ChatChannel.kind == "dm", a_member.c.user_id == a, b_member.c.user_id == b)
        .limit(1)
    )


async def resolve_dm(db: AsyncSession, me: User, other: User) -> UUID:
    """The 1:1 channel between two people, created if it doesn't exist yet.

    An existing DM is always reusable — the department gate is about *starting*
    a cross-team conversation, so once one exists both sides can keep using it.
    """
    if other.id == me.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot DM yourself")
    if not other.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    found = await existing_dm_id(db, me.id, other.id)
    if found:
        return found

    if is_cross_dept([me.role, other.role]) and not may_start_cross_dept(me.role):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Cross-department chats can only be started by a director, manager, or HR.",
        )
    ch = ChatChannel(kind="dm", created_by=me.id)
    db.add(ch)
    await db.flush()
    db.add_all([
        ChatChannelMember(channel_id=ch.id, user_id=me.id),
        ChatChannelMember(channel_id=ch.id, user_id=other.id),
    ])
    await db.flush()
    return ch.id


def excerpt(body: str) -> str:
    body = body or ""
    return body if len(body) <= QUOTE_EXCERPT else body[:QUOTE_EXCERPT - 1] + "…"


class ForwardIn(BaseModel):
    """Where a forward is going.

    `channel_ids` are existing conversations; `user_ids` are people, whose DM
    is found or created. `note` is the sender's own line, posted as a separate
    message after the forwarded copy so the two are never confused.
    """

    channel_ids: list[UUID] = []
    user_ids: list[UUID] = []
    note: str | None = None


async def deliver_forward(
    db: AsyncSession,
    *,
    me: User,
    body: str,
    origin_kind: str,
    origin_id: UUID,
    origin_author_id: UUID | None,
    targets: ForwardIn,
) -> dict:
    """Copy `body` into each destination as a forwarded message.

    The caller is responsible for proving it may *read* the source. This
    function proves it may *write* to each destination: membership for an
    existing channel (a director monitoring a channel they never joined can
    read it, but not post into it), and the department gate for a new DM.
    """
    channel_ids: list[UUID] = []
    seen: set[UUID] = set()

    for cid in targets.channel_ids:
        if cid in seen:
            continue
        ch = await db.get(ChatChannel, cid)
        if not ch:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
        if not await is_member(db, cid, me.id):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "You can only forward into conversations you are part of.",
            )
        seen.add(cid)
        channel_ids.append(cid)

    for uid in targets.user_ids:
        other = await db.get(User, uid)
        if not other:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
        # Portal accounts live outside the internal surfaces entirely.
        if other.role in ("customer", "supplier"):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Cannot forward to a customer or supplier account.",
            )
        cid = await resolve_dm(db, me, other)
        if cid not in seen:
            seen.add(cid)
            channel_ids.append(cid)

    if not channel_ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Pick at least one destination")
    if len(channel_ids) > MAX_FORWARD_TARGETS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Forward to at most {MAX_FORWARD_TARGETS} conversations at a time",
        )

    note = (targets.note or "").strip()
    delivered: list[dict] = []
    # created_at defaults to now(), which in Postgres is the *transaction*
    # timestamp — every row written here would tie and the forward could sort
    # after the note that follows it. Stamp them explicitly instead.
    stamp = datetime.now(UTC)
    step = 0

    for cid in channel_ids:
        msg = ChatMessage(
            channel_id=cid,
            user_id=me.id,
            body=body,
            created_at=stamp + timedelta(milliseconds=step),
            forwarded_from_kind=origin_kind,
            forwarded_from_id=origin_id,
            forwarded_from_author_id=origin_author_id,
        )
        db.add(msg)
        step += 1
        if note:
            db.add(ChatMessage(
                channel_id=cid, user_id=me.id, body=note,
                created_at=stamp + timedelta(milliseconds=step),
            ))
            step += 1
        await db.flush()
        delivered.append({"channel_id": str(cid), "message_id": str(msg.id)})

        # The sender has obviously read their own forward.
        member = await db.scalar(
            select(ChatChannelMember).where(
                ChatChannelMember.channel_id == cid,
                ChatChannelMember.user_id == me.id,
            )
        )
        if member:
            member.last_read_at = datetime.now(UTC)

    # A message leaving the document it was written on is worth a trail —
    # especially a discussion message, which may carry pricing or a customer
    # name into a chat with someone the document is closed to.
    from app.core.audit import record
    await record(
        db, actor=me, action="forward", entity=f"{origin_kind}_message",
        entity_id=origin_id,
        after={"channels": [d["channel_id"] for d in delivered],
               "original_author_id": origin_author_id, "with_note": bool(note)},
    )

    from app.services.webpush import fire_and_forget, notify_chat_message
    for cid in channel_ids:
        ch = await db.get(ChatChannel, cid)
        fire_and_forget(notify_chat_message(
            channel_id=cid,
            sender_id=me.id,
            sender_name=me.full_name,
            channel_name=ch.name if ch else None,
            text=body,
        ))

    return {"count": len(delivered), "delivered": delivered}

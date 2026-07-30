"""Discussion threads on deal and operations documents.

A thread is keyed by (owner_type, owner_id). Two things govern who may read
and post:

1. **The parent document.** If you cannot open the quotation, you cannot read
   its discussion. This used to be unenforced — any internal login could read
   (and post to) any thread by knowing an id, which leaked customer identity
   and pricing straight past the sales scoping and purchasing's
   customer-blindness.

2. **Mentions.** Being @-mentioned grants access to *that thread only*. This is
   the deliberate exception: it lets someone pull a colleague into a
   conversation they could never otherwise open — HR, or purchasing on a deal
   document — without giving them the document, its prices, or the customer
   record. The mentioned person reads and replies from their Mentions inbox.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.permissions import Role, require_min
from app.models.comment import CommentMention, EntityComment
from app.models.user import User
from app.services.chat_policy import ForwardIn, deliver_forward, excerpt

router = APIRouter(
    # Internal-only surface. External portal accounts (customer /
    # supplier, hierarchy tier 0) must never reach the CRM, pricing,
    # calendar or notification data — they have /portal/* instead.
    dependencies=[Depends(require_min(Role.SALES))]
)

ALLOWED_OWNERS = {
    "quotation", "customer_po", "supplier_po", "price_request",
    "project", "invoice",
}

# Which roles have any business in a given thread, before row-level scoping.
# Deliberately not the same as the attachment map: files on a quotation are
# director-only, but the *conversation* about a deal is how sales, finance and
# management coordinate. Purchasing is absent from every customer-facing thread
# — that is the customer-blindness rule, and a mention is the only way in.
_THREAD_ROLES: dict[str, set[Role]] = {
    "price_request": {Role.SALES, Role.PURCHASING, Role.MANAGER, Role.DIRECTOR},
    "quotation":     {Role.SALES, Role.ADMIN, Role.FINANCE, Role.MANAGER, Role.DIRECTOR},
    "customer_po":   {Role.SALES, Role.ADMIN, Role.FINANCE, Role.MANAGER, Role.DIRECTOR},
    "supplier_po":   {Role.PURCHASING, Role.MANAGER, Role.DIRECTOR},
    "project":       {Role.SALES, Role.PURCHASING, Role.ADMIN, Role.FINANCE,
                      Role.MANAGER, Role.DIRECTOR},
    "invoice":       {Role.SALES, Role.ADMIN, Role.FINANCE, Role.MANAGER, Role.DIRECTOR},
}


async def _sales_owns(db: AsyncSession, user: User, owner_type: str, owner_id: UUID) -> bool:
    """Row-level scope for sales: their own customers' documents only.

    Mirrors the check each entity's own detail endpoint already performs, so a
    thread is never reachable when the document behind it is not.
    """
    if owner_type == "price_request":
        from app.models.price_request import PriceRequest
        pr = await db.get(PriceRequest, owner_id)
        return bool(pr and not pr.is_deleted and pr.sales_pic_id == user.id)
    if owner_type == "quotation":
        from app.models.quotation import Quotation
        q = await db.get(Quotation, owner_id)
        return bool(q and q.sales_pic_id == user.id)
    if owner_type == "customer_po":
        from app.models.crm import Customer
        from app.models.customer_po import CustomerPO
        po = await db.get(CustomerPO, owner_id)
        if not po:
            return False
        cust = await db.get(Customer, po.customer_id) if po.customer_id else None
        return bool(cust and cust.sales_pic_id == user.id)
    if owner_type == "project":
        from app.models.crm import Customer
        from app.models.operation import Project
        p = await db.get(Project, owner_id)
        if not p or p.is_deleted:
            return False
        cust = await db.get(Customer, p.customer_id) if p.customer_id else None
        return bool(cust and cust.sales_pic_id == user.id)
    if owner_type == "invoice":
        from app.models.crm import Customer
        from app.models.finance import Invoice
        inv = await db.get(Invoice, owner_id)
        if not inv:
            return False
        cust = await db.get(Customer, inv.customer_id) if inv.customer_id else None
        return bool(cust and cust.sales_pic_id == user.id)
    # supplier_po has no sales audience at all.
    return False


async def _was_mentioned(db: AsyncSession, user: User,
                         owner_type: str, owner_id: UUID) -> bool:
    return bool(await db.scalar(
        select(CommentMention.id).where(
            CommentMention.user_id == user.id,
            CommentMention.owner_type == owner_type,
            CommentMention.owner_id == owner_id,
        ).limit(1)
    ))


async def _has_document_access(db: AsyncSession, user: User,
                               owner_type: str, owner_id: UUID) -> bool:
    """Would this person reach the thread *without* having been mentioned?

    Kept separate from _can_view_thread on purpose. Answering "can they open
    the page" with a function that counts the mention grant would say yes to
    everyone already mentioned — which would drop the composer's warning for
    exactly the people it exists to warn about, and offer them a document link
    that 403s.
    """
    role = Role(user.role)
    if role not in _THREAD_ROLES.get(owner_type, set()):
        return False
    # Sales is additionally scoped to its own customers; every other role in
    # the set sees the document, so it sees the conversation.
    return role != Role.SALES or await _sales_owns(db, user, owner_type, owner_id)


async def _can_view_thread(db: AsyncSession, user: User,
                           owner_type: str, owner_id: UUID) -> bool:
    if await _has_document_access(db, user, owner_type, owner_id):
        return True
    # The deliberate exception — see the module docstring.
    return await _was_mentioned(db, user, owner_type, owner_id)


async def _require_thread(db: AsyncSession, user: User,
                          owner_type: str, owner_id: UUID) -> None:
    if owner_type not in ALLOWED_OWNERS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid owner_type")
    if not await _can_view_thread(db, user, owner_type, owner_id):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "This discussion belongs to a document you don't have access to. "
            "Ask someone on it to @mention you.",
        )


class CommentIn(BaseModel):
    owner_type: str
    owner_id: UUID
    body: str
    # Explicit rather than parsed out of the body: names contain spaces and
    # punctuation, and a regex that guesses wrong would either miss a mention
    # or invent one. The composer knows exactly who was picked.
    mention_user_ids: list[UUID] = []
    # Quoting an earlier message in this same thread.
    reply_to_id: UUID | None = None


def _quote_out(q: EntityComment | None, names: dict[UUID, str],
               me: User | None = None) -> dict | None:
    if not q:
        return None
    return {
        "id": str(q.id),
        "author_name": names.get(q.author_id) if q.author_id else None,
        "body": excerpt(q.body),
        "is_mine": bool(me and q.author_id == me.id),
    }


def _out(c: EntityComment, author: User | None,
         mentions: list[User] | None = None,
         quoted: EntityComment | None = None,
         names: dict[UUID, str] | None = None,
         me: User | None = None) -> dict:
    return {
        "id": str(c.id),
        "owner_type": c.owner_type,
        "owner_id": str(c.owner_id),
        "body": c.body,
        "author_id": str(c.author_id) if c.author_id else None,
        "author_name": author.full_name if author else None,
        "author_role": author.role if author else None,
        "created_at": c.created_at,
        "mentions": [
            {"id": str(u.id), "name": u.full_name} for u in (mentions or [])
        ],
        "reply_to": _quote_out(quoted, names or {}, me),
        # Only ever the original author — never the thread it came from. See
        # the comment on the model: naming the origin would carry a document
        # number into a conversation that document is closed to.
        "forwarded": {
            "author_name": (names or {}).get(c.forwarded_from_author_id)
            if c.forwarded_from_author_id else None,
        } if c.forwarded_from_kind else None,
    }


@router.get("/mentionable")
async def mentionable_users(
    owner_type: str,
    owner_id: UUID,
    q: str | None = None,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    """Who the @ picker may offer.

    Every active internal colleague — the whole point is reaching someone who
    cannot open the page. `has_access` tells the composer which of them are
    already on the document, so it can warn that mentioning the others will
    show them this message.
    """
    await _require_thread(db, me, owner_type, owner_id)
    stmt = select(User).where(
        User.is_active.is_(True),
        User.role.notin_([Role.CUSTOMER.value, Role.SUPPLIER.value]),
        User.id != me.id,
    ).order_by(User.full_name)
    if q:
        stmt = stmt.where(User.full_name.ilike(f"%{q}%"))
    rows = (await db.scalars(stmt.limit(25))).all()
    out = []
    for u in rows:
        out.append({
            "id": str(u.id),
            "name": u.full_name,
            "role": u.role,
            "has_access": await _has_document_access(db, u, owner_type, owner_id),
        })
    return out


@router.get("/mentions")
async def my_mentions(
    unread_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    """The mentions inbox — where someone reads a thread they can't otherwise open."""
    stmt = (
        select(CommentMention, EntityComment)
        .join(EntityComment, CommentMention.comment_id == EntityComment.id)
        .where(CommentMention.user_id == me.id)
        .order_by(EntityComment.created_at.desc())
        .limit(100)
    )
    if unread_only:
        stmt = stmt.where(CommentMention.read_at.is_(None))
    rows = (await db.execute(stmt)).all()

    # The message being replied to, so a mention doesn't arrive without the
    # line it answers. Fetched by id: the inbox holds single comments, not
    # whole threads.
    quote_ids = {c.reply_to_id for _, c in rows if c.reply_to_id}
    quotes: dict[UUID, EntityComment] = {}
    if quote_ids:
        for q in (await db.scalars(
            select(EntityComment).where(EntityComment.id.in_(quote_ids))
        )).all():
            quotes[q.id] = q

    author_ids = {c.author_id for _, c in rows if c.author_id}
    author_ids |= {q.author_id for q in quotes.values() if q.author_id}
    authors: dict[UUID, User] = {}
    if author_ids:
        for u in (await db.scalars(select(User).where(User.id.in_(author_ids)))).all():
            authors[u.id] = u
    names = {uid: u.full_name for uid, u in authors.items()}

    out = []
    for m, c in rows:
        a = authors.get(c.author_id) if c.author_id else None
        out.append({
            "reply_to": _quote_out(
                quotes.get(c.reply_to_id) if c.reply_to_id else None, names, me,
            ),
            "id": str(m.id),
            "comment_id": str(c.id),
            "owner_type": c.owner_type,
            "owner_id": str(c.owner_id),
            "document": await _document_label(db, c.owner_type, c.owner_id),
            "body": c.body,
            "author_name": a.full_name if a else None,
            "author_role": a.role if a else None,
            "created_at": c.created_at,
            "read_at": m.read_at,
            # Whether the "open the document" link should exist at all. Showing
            # it to someone who only holds the thread just sends them into a
            # permission error.
            "can_open": await _has_document_access(db, me, c.owner_type, c.owner_id),
        })
    return out


@router.post("/mentions/{mention_id}/read")
async def mark_mention_read(
    mention_id: UUID,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    m = await db.get(CommentMention, mention_id)
    if not m or m.user_id != me.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if not m.read_at:
        m.read_at = datetime.now(UTC)
        await db.flush()
    return {"ok": True, "read_at": m.read_at}


async def _document_label(db: AsyncSession, owner_type: str, owner_id: UUID) -> str:
    """A human handle for the thread — the document number where there is one.

    Deliberately just the number: the mentions inbox must not become a side
    channel for the customer name or the value of the deal.
    """
    try:
        if owner_type == "price_request":
            from app.models.price_request import PriceRequest
            row = await db.get(PriceRequest, owner_id)
            return row.number if row else "price request"
        if owner_type == "quotation":
            from app.models.quotation import Quotation
            row = await db.get(Quotation, owner_id)
            return row.number if row else "quotation"
        if owner_type == "customer_po":
            from app.models.customer_po import CustomerPO
            row = await db.get(CustomerPO, owner_id)
            return row.number if row else "customer PO"
        if owner_type == "supplier_po":
            from app.models.purchasing import SupplierPO
            row = await db.get(SupplierPO, owner_id)
            return row.number if row else "supplier PO"
        if owner_type == "project":
            from app.models.operation import Project
            row = await db.get(Project, owner_id)
            return row.code if row else "project"
        if owner_type == "invoice":
            from app.models.finance import Invoice
            row = await db.get(Invoice, owner_id)
            return row.number if row else "invoice"
    except Exception:  # noqa: BLE001 — a label is never worth a 500
        pass
    return owner_type.replace("_", " ")


@router.get("")
async def list_comments(
    owner_type: str,
    owner_id: UUID,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    await _require_thread(db, me, owner_type, owner_id)
    rows = (await db.scalars(
        select(EntityComment)
        .where(EntityComment.owner_type == owner_type, EntityComment.owner_id == owner_id)
        .order_by(EntityComment.created_at.asc())
    )).all()

    # Batch-load authors and mentioned users
    author_ids = {c.author_id for c in rows if c.author_id}
    mention_rows = (await db.scalars(
        select(CommentMention).where(
            CommentMention.comment_id.in_([c.id for c in rows])
        )
    )).all() if rows else []
    by_comment: dict[UUID, list[UUID]] = {}
    for m in mention_rows:
        by_comment.setdefault(m.comment_id, []).append(m.user_id)

    people: dict[UUID, User] = {}
    wanted = author_ids | {uid for ids in by_comment.values() for uid in ids}
    wanted |= {c.forwarded_from_author_id for c in rows if c.forwarded_from_author_id}
    if wanted:
        for u in (await db.scalars(select(User).where(User.id.in_(wanted)))).all():
            people[u.id] = u
    names = {uid: u.full_name for uid, u in people.items()}

    # The whole thread is in `rows`, so a quote resolves without another query.
    by_id = {c.id: c for c in rows}

    return [
        _out(
            c,
            people.get(c.author_id) if c.author_id else None,
            [people[uid] for uid in by_comment.get(c.id, []) if uid in people],
            by_id.get(c.reply_to_id) if c.reply_to_id else None,
            names,
            me,
        )
        for c in rows
    ]


@router.post("", status_code=201)
async def add_comment(
    payload: CommentIn,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    await _require_thread(db, me, payload.owner_type, payload.owner_id)
    body = (payload.body or "").strip()
    if not body:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Comment cannot be empty")

    # A quote must belong to this same thread. Any other id and the reply would
    # lift a line out of a document the readers here may have no access to.
    quoted: EntityComment | None = None
    if payload.reply_to_id:
        quoted = await db.get(EntityComment, payload.reply_to_id)
        if (not quoted or quoted.owner_type != payload.owner_type
                or quoted.owner_id != payload.owner_id):
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "You can only reply to a message in this discussion")

    c = EntityComment(
        owner_type=payload.owner_type,
        owner_id=payload.owner_id,
        author_id=me.id,
        body=body,
        reply_to_id=quoted.id if quoted else None,
    )
    db.add(c)
    await db.flush()

    mentioned: list[User] = []
    if payload.mention_user_ids:
        wanted = set(payload.mention_user_ids) - {me.id}
        rows = (await db.scalars(
            select(User).where(
                User.id.in_(wanted),
                User.is_active.is_(True),
                # Portal accounts can never be mentioned — they have no way to
                # reach an internal thread and must not be handed one.
                User.role.notin_([Role.CUSTOMER.value, Role.SUPPLIER.value]),
            )
        )).all()
        for u in rows:
            db.add(CommentMention(
                comment_id=c.id, user_id=u.id,
                owner_type=payload.owner_type, owner_id=payload.owner_id,
            ))
            mentioned.append(u)
        await db.flush()

    # Instant device push to the thread's participants + stakeholders, and a
    # louder one to anybody named (fire-and-forget; own DB session).
    from app.services.webpush import fire_and_forget, notify_discussion_comment
    fire_and_forget(notify_discussion_comment(
        owner_type=payload.owner_type,
        owner_id=payload.owner_id,
        sender_id=me.id,
        sender_name=me.full_name,
        text=body,
        mentioned_ids=[u.id for u in mentioned],
    ))

    names = {me.id: me.full_name}
    if quoted and quoted.author_id and quoted.author_id != me.id:
        qa = await db.get(User, quoted.author_id)
        if qa:
            names[qa.id] = qa.full_name
    return _out(c, me, mentioned, quoted, names, me)


@router.post("/{comment_id}/forward")
async def forward_comment(
    comment_id: UUID,
    payload: ForwardIn,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    """Pass a discussion message on to a chat conversation.

    Destinations are chats, not other documents — a chat is somewhere the
    recipient definitely has, so this works whether or not they could open the
    document the message was written on. That is the same trade the @mention
    makes: the sender shares the text and nothing else. Every forward out of a
    document thread is written to the audit log.
    """
    c = await db.get(EntityComment, comment_id)
    if not c:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found")
    # Reading the thread is what licenses forwarding out of it — including for
    # someone who only holds it via a mention.
    await _require_thread(db, me, c.owner_type, c.owner_id)

    return await deliver_forward(
        db, me=me, body=c.body,
        origin_kind=c.forwarded_from_kind or "comment",
        origin_id=c.forwarded_from_id or c.id,
        origin_author_id=c.forwarded_from_author_id or c.author_id,
        targets=payload,
    )

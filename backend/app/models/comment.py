"""Generic comment thread attachable to any entity.

Used for the discussion thread on quotations, POs (customer + supplier),
price requests, projects and invoices. owner_type namespaces the thread;
owner_id ties it to the row.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPK


class EntityComment(Base, UUIDPK, TimestampMixin):
    __tablename__ = "entity_comments"

    # e.g. "quotation" | "customer_po" | "supplier_po" | "project" | "invoice"
    owner_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    owner_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    author_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)


class CommentMention(Base, UUIDPK, TimestampMixin):
    """Someone was @-mentioned in a comment.

    This is not just a notification record — it is the *permission*. Being
    mentioned grants read/reply access to that one thread, and nothing else:
    not the document, not its prices, not the customer behind it. That is what
    lets a sales rep pull HR or purchasing into a conversation they could never
    otherwise open, without punching a hole in the scoping rules everywhere
    else.

    `read_at` drives the bell: an unmentioned-and-unread row is what makes the
    notification appear, and clearing it is what makes it go away.
    """

    __tablename__ = "comment_mentions"
    __table_args__ = (
        UniqueConstraint("comment_id", "user_id", name="uq_comment_mention"),
    )

    comment_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("entity_comments.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # Denormalised from the comment so "which threads may I reach?" is one
    # index lookup rather than a join on every permission check.
    owner_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    owner_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

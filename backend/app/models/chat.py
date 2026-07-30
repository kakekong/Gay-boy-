from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPK


class ChatChannel(Base, UUIDPK, TimestampMixin):
    """A conversation. kind='dm' is a 1:1; kind='channel' is a named group."""

    __tablename__ = "chat_channels"

    name: Mapped[str | None] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(20), default="dm", nullable=False, index=True)
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


class ChatChannelMember(Base):
    __tablename__ = "chat_channel_members"

    channel_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("chat_channels.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ChatMessage(Base, UUIDPK):
    __tablename__ = "chat_messages"

    channel_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("chat_channels.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # A quoted reply, WhatsApp-style. Always a message in the *same* channel —
    # the API refuses anything else, because quoting across channels would
    # copy text out of a conversation the reader was never in. SET NULL rather
    # than CASCADE: deleting the quoted message must not delete the reply.
    reply_to_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("chat_messages.id", ondelete="SET NULL"), index=True
    )

    # Forward provenance. `kind` says which table the origin lives in
    # ("chat" | "comment") and `id` is that row — kept for the audit trail, and
    # deliberately *not* returned by the API: the reader is shown "Forwarded"
    # and the original author, never the document or channel it came from.
    # Naming the origin would leak a quotation number or a deal channel past
    # the scoping rules the rest of the app is careful about.
    forwarded_from_kind: Mapped[str | None] = mapped_column(String(20))
    forwarded_from_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    forwarded_from_author_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

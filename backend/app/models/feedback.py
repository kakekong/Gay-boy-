"""User feedback — a direct line from any account to the director."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import UUIDPK


class Feedback(Base, UUIDPK):
    __tablename__ = "feedback"

    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    # Snapshot of the sender's role at send time (role may change later).
    role: Mapped[str | None] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    # Which page the sender was on — helps the director reproduce issues.
    page: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(
        String(20), default="new", nullable=False, index=True  # new | resolved
    )
    resolved_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

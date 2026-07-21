from datetime import date as date_t
from uuid import UUID

from sqlalchemy import Date, ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPK


class DailyLog(Base, UUIDPK, TimestampMixin):
    """A free-form daily work journal — one row per user per date.

    Sits alongside Attendance (clock in/out) but answers *what* you did,
    not *when* you were here. Files attach via the polymorphic Attachment
    table (owner_type="daily_log", owner_id=this row's id); links are a
    small JSONB list of {label, url} so no extra table is needed.
    """

    __tablename__ = "daily_logs"
    __table_args__ = (UniqueConstraint("user_id", "date", name="uq_daily_log_user_date"),)

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    date: Mapped[date_t] = mapped_column(Date, nullable=False, index=True)
    body: Mapped[str | None] = mapped_column(Text)
    # [{ "label": "Design doc", "url": "https://…" }, …]
    links: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

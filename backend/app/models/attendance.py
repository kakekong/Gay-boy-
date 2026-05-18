from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPK


class Attendance(Base, UUIDPK, TimestampMixin):
    """One row per user per date. Status drives salary deductions."""

    __tablename__ = "attendances"
    __table_args__ = (UniqueConstraint("user_id", "date", name="uq_attendance_user_date"),)

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    clock_in:  Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    clock_out: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hours:     Mapped[float] = mapped_column(Numeric(6, 2), default=0, nullable=False)
    # present | absent | half_day | leave | wfh | sick | holiday
    status: Mapped[str] = mapped_column(String(20), default="present", nullable=False, index=True)
    notes:  Mapped[str | None] = mapped_column(Text)

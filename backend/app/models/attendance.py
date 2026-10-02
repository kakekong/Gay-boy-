from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
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
    # Time past the end of the working day at clock-out, and whether it is
    # How long past the end of the day the clock-out was. A hint for the
    # director only — overtime is paid from OvertimeEntry, which the director
    # records by hand, because a forgotten clock-out reads as hours of
    # overtime. `overtime_status` / `overtime_approved_minutes` are from the
    # short-lived clock-out filing and are no longer written.
    overtime_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    overtime_status: Mapped[str | None] = mapped_column(String(20))
    overtime_approved_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class OvertimeEntry(Base, UUIDPK, TimestampMixin):
    """Overtime the director recorded for someone, which payroll pays.

    Entered by hand rather than read off clock-outs: clock times carry too
    many human errors (a forgotten clock-out is hours of "overtime"). The
    director's entry is the approval. A mistaken or test entry is revoked —
    kept on record with the reason, no longer paid — or deleted outright.
    """

    __tablename__ = "overtime_entries"

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="approved", nullable=False, index=True)
    entered_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    revoked_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(Text)

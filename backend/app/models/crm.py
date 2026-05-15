from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import AuthorshipMixin, SoftDeleteMixin, TimestampMixin, UUIDPK


class Customer(Base, UUIDPK, TimestampMixin, AuthorshipMixin, SoftDeleteMixin):
    __tablename__ = "customers"

    company_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    industry: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    pic_name: Mapped[str | None] = mapped_column(String(255))
    pic_position: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(40))
    whatsapp: Mapped[str | None] = mapped_column(String(40), index=True)
    email: Mapped[str | None] = mapped_column(String(255))
    company_address: Mapped[str | None] = mapped_column(Text)
    delivery_address: Mapped[str | None] = mapped_column(Text)

    sales_pic_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    stage: Mapped[str] = mapped_column(String(30), nullable=False, default="lead", index=True)
    payment_terms: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    lifetime_value: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    lost_reason: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class Activity(Base, UUIDPK, TimestampMixin):
    __tablename__ = "activities"

    customer_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )
    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(10), nullable=False, default="internal")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class Reminder(Base, UUIDPK, TimestampMixin):
    __tablename__ = "reminders"

    customer_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), index=True)
    invoice_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), index=True)
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ai_optimal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="whatsapp")
    message: Mapped[str | None] = mapped_column(Text)
    # Recurrence: none | daily | weekly | biweekly | monthly
    recurs: Mapped[str] = mapped_column(String(20), default="none", nullable=False)
    recurs_until: Mapped[date | None] = mapped_column(Date)
    parent_reminder_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))

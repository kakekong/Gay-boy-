from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String, Text
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

    # Tax info (Indonesian context: NPWP / NPPKP / PKP status).
    tax_id: Mapped[str | None] = mapped_column(String(32))
    tax_name: Mapped[str | None] = mapped_column(String(255))
    tax_address: Mapped[str | None] = mapped_column(Text)
    is_pkp: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    nppkp_no: Mapped[str | None] = mapped_column(String(64))
    tax_notes: Mapped[str | None] = mapped_column(Text)
    payment_terms: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    lifetime_value: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    lost_reason: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    @property
    def external_code(self) -> str | None:
        """This customer's code in the old accounting system, if imported.

        Kept so the two systems can still be reconciled against each other
        while both are in use — and so a second import run recognises the row
        instead of creating it again.
        """
        return (self.meta or {}).get("external_code")


class CustomerContact(Base, UUIDPK, TimestampMixin):
    """Additional PICs at a customer company. The Customer row itself still
    carries the primary PIC; this table holds everyone else."""
    __tablename__ = "customer_contacts"

    customer_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(40))
    whatsapp: Mapped[str | None] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(255))
    is_primary: Mapped[bool] = mapped_column(default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)


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
    kind: Mapped[str] = mapped_column(String(80), nullable=False)
    # Nullable: stage-playbook tasks start with NO deadline — they only hit
    # the calendar + notifications once someone sets a date explicitly.
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ai_optimal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="whatsapp")
    message: Mapped[str | None] = mapped_column(Text)
    # Recurrence: none | daily | weekly | biweekly | monthly
    recurs: Mapped[str] = mapped_column(String(20), default="none", nullable=False)
    recurs_until: Mapped[date | None] = mapped_column(Date)
    parent_reminder_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))

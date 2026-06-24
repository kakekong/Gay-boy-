from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPK


class Invoice(Base, UUIDPK, TimestampMixin):
    __tablename__ = "invoices"

    number: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    project_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    customer_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customers.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    type: Mapped[str] = mapped_column(String(20), default="single", nullable=False)
    termin_index: Mapped[int | None] = mapped_column(Integer)
    issue_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date, index=True)
    amount: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    tax_amount: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    total: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False, index=True)
    pdf_url: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)


class Payment(Base, UUIDPK, TimestampMixin):
    __tablename__ = "payments"

    invoice_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    amount: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    method: Mapped[str | None] = mapped_column(String(40))
    reference: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)


class LedgerEntry(Base, UUIDPK, TimestampMixin):
    """A single line in the company transaction journal.

    Every financial movement — a posted quotation, a received payment, a
    posted payroll, a manual adjustment — writes one row per account it
    touches. This is the system of record for *time-bounded* reporting:
    Chart-of-Accounts balances tell you where things stand right now, but
    the journal is what lets us slice profit, cash flow, and activity by
    month / quarter / year and attribute revenue to a salesperson.

    Sign convention (single-entry, matching the posting service): `amount`
    is the signed delta applied to the account's running balance. For a
    Cash & Bank account, `cash_delta` mirrors that change so money-in /
    money-out is a plain SUM — positive is cash in, negative is cash out.
    `cash_delta` is 0 for every non-cash line.
    """

    __tablename__ = "ledger_entries"

    entry_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    account_no: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    # Denormalised from the account so report grouping needs no join.
    account_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    account_name: Mapped[str | None] = mapped_column(String(255))
    amount: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    cash_delta: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    # What produced this line: quotation | payment | salary | opening | manual
    source_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    source_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), index=True)
    source_ref: Mapped[str | None] = mapped_column(String(120))
    memo: Mapped[str | None] = mapped_column(Text)
    customer_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), index=True)
    # Salesperson this movement is attributable to (revenue / commission),
    # so each rep can have their own financial report.
    sales_pic_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), index=True)
    created_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))

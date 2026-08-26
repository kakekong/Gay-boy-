"""Kas & Bank — money in, money out, and money moved between our own accounts.

Everything here ends up as a journal entry, so why does it need a table of
its own? Because a journal entry is what the books need and this is what the
person doing it needs. Paying a supplier has a payee, a method, a cheque or
transfer reference, and often several things being paid at once out of one
bank account. Those belong on the document; the journal underneath records
its effect on the accounts and nothing else.

Three kinds, and the difference between them is only which way the money
went:

- **payment** — out of one of our accounts. The bank is credited; whatever
  the money was for is debited.
- **receipt** — into one. The mirror image.
- **transfer** — out of one of ours and into another of ours. Nothing is
  earned or spent, which is exactly why it needs to be its own kind rather
  than a payment that happens to name a bank account: booked as a payment it
  would read as expenditure.

A posted transaction is never edited. Voiding one reverses its journal and
leaves both on the record, the same rule the journal itself keeps.
"""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPK

KINDS = ("payment", "receipt", "transfer")


class CashTransaction(Base, UUIDPK, TimestampMixin):
    __tablename__ = "cash_transactions"

    number: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    tx_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # The account the money leaves (payment, transfer) or arrives in
    # (receipt). Always one of ours, always Cash & Bank.
    bank_account_no: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    # Only for a transfer: the account of ours it arrives in.
    to_account_no: Mapped[str | None] = mapped_column(String(40), index=True)
    # Who it was paid to or received from, in words. Deliberately free text:
    # a lot of what a company pays is not a supplier on file — a courier, a
    # notary, the tax office — and forcing every one of them into the
    # supplier directory is how the directory stops being useful.
    counterparty: Mapped[str | None] = mapped_column(String(255))
    method: Mapped[str | None] = mapped_column(String(40))     # transfer | cash | cheque
    reference: Mapped[str | None] = mapped_column(String(120))  # slip no., cheque no.
    memo: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)

    journal_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), index=True)
    is_void: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    void_reason: Mapped[str | None] = mapped_column(Text)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    voided_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    # Bank reconciliation: ticked off against the statement, by whom, when.
    cleared_on: Mapped[date | None] = mapped_column(Date, index=True)
    cleared_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    created_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))

    lines: Mapped[list["CashLine"]] = relationship(
        back_populates="tx", cascade="all, delete-orphan",
        order_by="CashLine.line_no", lazy="selectin",
    )


class CashLine(Base, UUIDPK):
    """What the money was for — one line per account it is split across.

    A single transfer out of the bank often pays three things at once, and
    the whole point of recording it here rather than as a lump is that the
    profit report can then say which three.
    """

    __tablename__ = "cash_lines"

    cash_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("cash_transactions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    line_no: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    account_no: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    amount: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    memo: Mapped[str | None] = mapped_column(Text)
    # Optional links, so a receipt can be tied to the invoice it settles and
    # a payment to the customer it concerns.
    customer_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), index=True)
    invoice_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), index=True)

    tx: Mapped[CashTransaction] = relationship(back_populates="lines")

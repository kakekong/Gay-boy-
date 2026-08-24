"""The general journal — double-entry, and the record everything else reads.

The ledger this app started with is single-entry: each movement writes one
signed line per account it touches, and the account balance is the running
sum. That is enough to answer "how much cash do we have" and "what did we
sell in March", which is what it was built for.

It is not enough for the rest of accounting. A balance sheet that balances,
an account history you can hand an auditor, a bank reconciliation, a
depreciation run, a manual correction with a reason on it — all of them
assume every transaction names *both* sides: what was debited and what was
credited, adding to the same number. That is what this is.

Two rules, and they are the whole thing:

**A journal balances or it does not exist.** Total debits equal total
credits, checked before anything is written. An unbalanced entry is not
saved as a draft to fix later — it is refused, because the moment one exists
the balance sheet stops balancing and nobody can tell which entry did it.

**Posted is permanent.** A posted journal is never edited and never deleted;
correcting one means posting its reverse, which leaves both on the record.
Drafts are the place for work in progress, and a draft touches no balance.
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

# Which side increases an account. Assets and costs are debit-normal; what
# funds them — liabilities, equity, income — is credit-normal. Accumulated
# depreciation is the odd one: it sits under assets but carries a credit
# balance, because it is the amount of an asset already used up.
DEBIT_NORMAL = {
    "Cash & Bank", "Receivable", "Inventory", "Other Current Asset",
    "Fixed Asset", "Cost Of Good Sold", "Expense", "Other Expense",
}
CREDIT_NORMAL = {
    "Accumulated Depreciation", "Payable", "Other Current Liability",
    "Long Term Liability", "Equity", "Revenue", "Other Income",
}


def signed_delta(account_type: str, debit: float, credit: float) -> float:
    """What this line does to the account's running balance.

    Positive means the balance goes up in the direction the account is
    normally read: cash up on a debit, revenue up on a credit.
    """
    if account_type in CREDIT_NORMAL:
        return float(credit or 0) - float(debit or 0)
    return float(debit or 0) - float(credit or 0)


class JournalEntry(Base, UUIDPK, TimestampMixin):
    __tablename__ = "journal_entries"

    number: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    memo: Mapped[str | None] = mapped_column(Text)
    # What produced it: manual (Jurnal Umum), or the document that did —
    # quotation | payment | salary | cash | transfer | depreciation | opening.
    source_type: Mapped[str] = mapped_column(String(30), default="manual",
                                             nullable=False, index=True)
    source_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), index=True)
    source_ref: Mapped[str | None] = mapped_column(String(120))

    is_posted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    posted_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    # A reversal points at what it reverses; the original is marked so the
    # list can show it struck through rather than pretending it never was.
    reverses_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), index=True)
    reversed_by_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), index=True)
    created_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))

    lines: Mapped[list["JournalLine"]] = relationship(
        back_populates="entry", cascade="all, delete-orphan",
        order_by="JournalLine.line_no", lazy="selectin",
    )


class JournalLine(Base, UUIDPK):
    __tablename__ = "journal_lines"

    journal_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("journal_entries.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    line_no: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    account_no: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    # Denormalised from the account, like the single-entry journal does, so a
    # report can group by type without a join — and so a line still reads
    # correctly if the account is later renamed.
    account_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    account_name: Mapped[str | None] = mapped_column(String(255))
    debit: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    credit: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    memo: Mapped[str | None] = mapped_column(Text)
    # Kept from the single-entry journal: revenue attribution per rep, and
    # which customer a receivable line belongs to.
    customer_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), index=True)
    sales_pic_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), index=True)

    entry: Mapped[JournalEntry] = relationship(back_populates="lines")

"""Anggaran — what we said we would spend, against what we did.

A budget is only worth having if it can be compared to something, so the
shape here is chosen to make the comparison possible rather than to make
data entry pleasant: one line per account per period, and the period is
either a month or a year, never a vague "this quarter".

**Why a line is (period, account) and nothing else.** A budget that is
kept by department, by project, and by account at once cannot be compared
to the ledger, because the ledger only knows the account. Keeping the
budget in the same shape as the thing it is measured against is what turns
Monitor Anggaran from a spreadsheet into an answer.

**Why transfers are recorded rather than being two edits.** Moving 50
million from travel to training is a decision somebody made, and the two
edits that implement it lose the fact that they were one act. The transfer
row is the audit trail: who moved what, from where, and why.
"""

from datetime import date
from uuid import UUID

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPK


class Budget(Base, UUIDPK, TimestampMixin):
    __tablename__ = "budgets"
    # One figure per account per period. A second one is an edit, not another
    # budget — enforced here rather than left to the endpoint, because two
    # rows for the same account is a monitor that silently double-counts.
    __table_args__ = (
        UniqueConstraint("period_year", "period_month", "account_no",
                         name="uq_budget_period_account"),
    )

    period_year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    # NULL means the whole year. A yearly figure and twelve monthly ones are
    # different intentions, and the monitor says which one it used.
    period_month: Mapped[int | None] = mapped_column(Integer, index=True)
    account_no: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    amount: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"))


class BudgetTransfer(Base, UUIDPK, TimestampMixin):
    """Transfer Anggaran — one decision, not two edits.

    No journal: nothing has been spent, only re-allocated. What it changes
    is the yardstick, which is exactly why it needs a record of its own —
    a variance that looks fine only because the budget was moved last week
    should be able to say so.
    """

    __tablename__ = "budget_transfers"

    period_year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    period_month: Mapped[int | None] = mapped_column(Integer)
    from_account_no: Mapped[str] = mapped_column(String(40), nullable=False)
    to_account_no: Mapped[str] = mapped_column(String(40), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    moved_on: Mapped[date | None] = mapped_column(Date)
    memo: Mapped[str | None] = mapped_column(Text)
    actor_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"))

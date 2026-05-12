from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPK


class Salary(Base, UUIDPK, TimestampMixin):
    """Monthly payroll record for an employee. Director-only."""

    __tablename__ = "salaries"

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    period: Mapped[str] = mapped_column(String(7), nullable=False, index=True)  # YYYY-MM

    base_salary:  Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    transport:    Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    meal:         Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    bonus:        Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    thr:          Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    other_allowance: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)

    pph21:        Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    bpjs:         Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    other_deduction: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)

    gross_salary: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    net_pay:      Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)

    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False, index=True)
    # draft -> posted -> paid

    # CoA linkage
    account_expense_no:   Mapped[str | None] = mapped_column(String(40))   # default "6000-04"
    account_liability_no: Mapped[str | None] = mapped_column(String(40))   # default "2102-02"
    account_tax_no:       Mapped[str | None] = mapped_column(String(40))   # default "2102-04"
    account_bank_no:      Mapped[str | None] = mapped_column(String(40))   # default "1101-01"

    is_posted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    posted_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    paid_at:   Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes:     Mapped[str | None] = mapped_column(Text)

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPK

# What a rep earns on a job unless somebody decides otherwise. Kept here
# rather than in a settings table because it is one number that has never
# varied; the director can still override it on the claim they approve, which
# is where a different figure would be argued for anyway.
DEFAULT_RATE_PCT = 2.0

# pending  — filed, waiting on the director
# approved — the director agreed the figure; it is owed
# rejected — with a reason
# paid     — it has actually gone out with payroll
CLAIM_STATUSES = ("pending", "approved", "rejected", "paid")
LIVE_STATUSES = ("pending", "approved", "paid")


class CommissionClaim(Base, UUIDPK, TimestampMixin):
    """A rep asking to be paid their share of a job the customer has settled.

    The rule the whole thing hangs on is *when*: a claim can only be filed
    once finance has the money. Commission on an invoice that is still
    outstanding is a payment against a promise, and the promise is the part
    that sometimes does not arrive — so the gate is the collected figure, not
    the order value, and it is checked on the server at the moment the claim
    is filed.

    The figures are stored rather than recomputed on read. What was collected
    at the moment of the claim, the rate agreed, and the amount that follows
    are three facts about a decision; re-deriving them later would quietly
    restate an approved payout when a payment is reversed or an order is
    re-priced months afterwards.
    """

    __tablename__ = "commission_claims"

    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # Whose commission it is. Captured at claim time on purpose: handing the
    # customer to another rep next quarter must not move money that was
    # already earned.
    beneficiary_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    claimed_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False, index=True
    )
    # The percentage agreed, and what it was applied to — the amount the
    # customer had actually paid when the claim was filed.
    rate_pct: Mapped[float] = mapped_column(
        Numeric(6, 3), default=DEFAULT_RATE_PCT, nullable=False
    )
    basis_amount: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    # What the invoices said, before PPN, when the claim was approved. The
    # commission is worked out on `basis_amount`, which is the same figure
    # unless finance set the real selling price lower — a customer asks for
    # 15.000 on paper while 10.000 is what the company actually keeps — and
    # then why, by whom and when are kept with it.
    invoiced_basis: Mapped[float | None] = mapped_column(Numeric(18, 2))
    basis_note: Mapped[str | None] = mapped_column(Text)
    basis_set_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    basis_set_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    decision_notes: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

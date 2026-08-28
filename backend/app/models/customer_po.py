"""Customer Purchase Orders.

The PO the *customer* sends *us* after they accept a quotation. This is
what triggers project creation: a customer PO is filed (often by sales),
the director approves it in /approvals, and on approval a Project is
spawned with the PO number, date and value flowing in.

Distinct from `SupplierPO` (purchasing module), which is the PO *we*
send to *our suppliers*. The two never get mixed up because they live
in separate tables and behind separate endpoints.
"""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import AuthorshipMixin, TimestampMixin, UUIDPK


class CustomerPO(Base, UUIDPK, TimestampMixin, AuthorshipMixin):
    """An incoming PO from the customer.

    Two lifecycles:

    Regular PO (`is_downpayment=False`):
      pending_approval → approved → (project spawns) → project_id set
                       → rejected
                       → cancelled

    Down-payment PO (`is_downpayment=True`):
      pending_finance → (finance approves + issues DP invoice)
        → pending_payment_confirm → (finance confirms the money landed)
        → approved → (project spawns) → project_id set

    Both DP steps are finance's, and deliberately so: whether a deposit
    arrived is a fact about the bank account, and finance is who can see
    it. Sales used to confirm receipt, which meant the person with the
    most reason to want the job started was the one attesting the money
    was in.

      Any step can also land at rejected / cancelled.
    """

    __tablename__ = "customer_pos"

    number: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    po_date: Mapped[date | None] = mapped_column(Date)
    customer_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    quotation_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("quotations.id", ondelete="SET NULL"),
        index=True,
    )

    # The Project this PO spawns once it's approved. Null until approval
    # lands. ON DELETE SET NULL keeps the PO history visible even if the
    # downstream project is later hard-deleted.
    project_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="SET NULL"),
        index=True,
    )

    total: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    items: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="pending_approval", nullable=False, index=True)

    decided_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_notes: Mapped[str | None] = mapped_column(Text)

    # Down-payment flag. When True the PO takes a different path: finance
    # signs off first (they're the ones who chase the deposit invoice),
    # then sales confirms once payment lands, and only then the project
    # spawns. False keeps the original director-approves flow.
    is_downpayment: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
    )
    dp_finance_approved_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    dp_finance_approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    # Who confirmed the deposit actually landed, and when. Finance's,
    # since it is a statement about the bank rather than about the deal.
    dp_payment_confirmed_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    dp_payment_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )

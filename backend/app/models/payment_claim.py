from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPK


class PaymentClaim(Base, UUIDPK, TimestampMixin):
    """One recorded receipt of money against an invoice.

    Named for what it used to be: a customer's claim from the portal that
    they had paid, waiting for finance to agree. That route is gone —
    finance records payments itself, in one step, and every such record still
    writes a row here already verified, so the history reads continuously
    either side of the change.

    `customer_user_id` is therefore whoever wrote the row: a member of
    finance on anything recent, the customer on the older ones. The column
    keeps its name rather than being renamed under live data.
    """

    __tablename__ = "payment_claims"

    invoice_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    customer_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    paid_at: Mapped[date | None] = mapped_column(Date)
    method:    Mapped[str | None] = mapped_column(String(60))   # bank_transfer / cash / cheque / etc.
    reference: Mapped[str | None] = mapped_column(String(120))  # bank transfer ID, cheque #
    notes:     Mapped[str | None] = mapped_column(Text)
    attachment_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("attachments.id", ondelete="SET NULL")
    )

    # pending | verified | rejected
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False, index=True)
    verified_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_notes: Mapped[str | None] = mapped_column(Text)

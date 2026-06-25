"""Pre-quotation pricing workflow.

The order pipeline now starts with a Price Request: before a quotation can
be drawn up, sales lists the goods a customer needs (description + qty, no
prices). Purchasing fills in the procurement cost per line. The director
reviews, may edit the costs, and sets the selling price per line. Once the
director approves, a quotation is built straight from this form — sales
never types a price.

Status flow:
    draft → pending_purchasing → pending_director → approved
                                                   ↘ rejected (back to sales)

`items` is a JSON list of line dicts:
    {line_no, description, qty, uom, spec, cost_price, sell_price}
`cost_price` is filled by purchasing; `sell_price` is set by the director.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import AuthorshipMixin, SoftDeleteMixin, TimestampMixin, UUIDPK


class PriceRequest(Base, UUIDPK, TimestampMixin, AuthorshipMixin, SoftDeleteMixin):
    __tablename__ = "price_requests"

    number: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    customer_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customers.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    sales_pic_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), index=True)
    status: Mapped[str] = mapped_column(
        String(30), default="draft", nullable=False, index=True
    )
    items: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    # Purchasing fills costs
    priced_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    priced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Director approves + sets selling prices
    approved_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_notes: Mapped[str | None] = mapped_column(Text)

    # Once a quotation is generated from this request.
    quotation_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), index=True)

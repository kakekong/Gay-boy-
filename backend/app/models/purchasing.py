from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPK


class Supplier(Base, UUIDPK, TimestampMixin):
    __tablename__ = "suppliers"

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    category: Mapped[str | None] = mapped_column(String(120))
    rating: Mapped[float] = mapped_column(Numeric(4, 2), default=0, nullable=False)
    lead_time_days_avg: Mapped[float] = mapped_column(Numeric(6, 2), default=0, nullable=False)
    qc_fail_rate: Mapped[float] = mapped_column(Numeric(6, 4), default=0, nullable=False)
    price_volatility: Mapped[float] = mapped_column(Numeric(6, 4), default=0, nullable=False)

    # Where they are, and how the *company* is reached — the switchboard and
    # the sales@ mailbox, which outlive whichever person currently answers
    # them. A named person's own number lives on their SupplierContact row.
    company_address: Mapped[str | None] = mapped_column(Text)
    warehouse_address: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(String(40))
    whatsapp: Mapped[str | None] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(255))

    # Legacy free-form contact blob, kept because rows created before the
    # columns above still carry {name, phone, email} in it and the supplier
    # page reads it as a fallback. New writes go to the columns.
    contact: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class SupplierContact(Base, UUIDPK, TimestampMixin):
    """The people at a supplier company — the same shape as CustomerContact.

    A supplier is not one phone number: the sales rep quotes, a different
    person confirms the delivery date, and a third chases the invoice. Which
    one you need depends on what you are asking, so they are rows rather than
    a single `contact` blob.
    """
    __tablename__ = "supplier_contacts"

    supplier_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(40))
    whatsapp: Mapped[str | None] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(255))
    is_primary: Mapped[bool] = mapped_column(default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)


class SupplierPriceRequest(Base, UUIDPK, TimestampMixin):
    """What we ask a supplier to charge us — the buy side of a price request.

    The existing PriceRequest is the *sell* side: sales lists what a customer
    wants, purchasing fills a cost, the director sets a margin. Where that cost
    came from was nowhere: purchasing asked two or three vendors on WhatsApp
    and typed the winning number in, so the quote that justified the price, the
    ones that lost, and the lead times all lived in a phone.

    This is that conversation, written down. One row per supplier asked — so
    three vendors on the same job are three rows to compare — optionally
    pointing at the customer price request it serves. When it points at one,
    the quoted prices can be applied to it as the cost, which is the whole
    reason the record exists.

    Status: draft → sent → quoted → closed  (or cancelled at any point)
    `items` is [{line_no, description, qty, uom, quoted_price, quoted_basis,
                 lead_days, note}]
    """
    __tablename__ = "supplier_price_requests"

    number: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    supplier_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    # The customer-side price request being costed, when there is one. Nullable
    # because purchasing also asks for prices with no deal behind it — keeping
    # a price list current, checking a rate before a tender.
    price_request_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("price_requests.id", ondelete="SET NULL"),
        index=True,
    )
    requested_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(
        String(20), default="draft", nullable=False, index=True
    )
    items: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    # Every customer price request this one draws lines from, as a flat list of
    # id strings. `price_request_id` above is the single-source case and goes
    # NULL on a joint request; this is what "which SPRs touch PR-2026-0007"
    # asks, and it stays queryable with a JSONB containment test instead of
    # scanning every row's items.
    source_pr_ids: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(String(8), default="IDR", nullable=False)
    # How long the supplier's quote holds, and how long they said delivery
    # takes — both are half of what makes one quote better than another.
    valid_until: Mapped[date | None] = mapped_column(Date)
    quoted_lead_days: Mapped[int | None] = mapped_column()
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set when this quote is the one that became the cost on the linked
    # customer price request. At most one per price request, enforced in the
    # endpoint rather than the schema so re-costing stays possible.
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class PurchaseRequest(Base, UUIDPK, TimestampMixin):
    __tablename__ = "purchase_requests"

    number: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    project_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    requested_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    items: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text)


class RFQ(Base, UUIDPK, TimestampMixin):
    __tablename__ = "rfqs"

    pr_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("purchase_requests.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    supplier_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    quoted_lines: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    quoted_lead_days: Mapped[int | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)


class SupplierPO(Base, UUIDPK, TimestampMixin):
    __tablename__ = "supplier_pos"

    number: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    rfq_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("rfqs.id", ondelete="SET NULL")
    )
    supplier_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    # The approved price request this PO sources against. Lets the PO pull in
    # the buying (cost) price purchasing already entered, instead of re-typing.
    price_request_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), index=True)
    po_date: Mapped[date | None] = mapped_column(Date)
    quoted_lead_days: Mapped[int | None] = mapped_column()
    # When this shipment is expected. Per PO rather than per project, because
    # a job split across three vendors arrives in three deliveries and the
    # project's own dates cannot hold three answers.
    eta: Mapped[date | None] = mapped_column(Date)
    # What the numbers on this order mean. Overseas vendors quote in USD or
    # CNY, and a purchase order that prints 1.800.000 without saying which
    # currency is an invoice dispute waiting to happen — read as rupiah it is
    # a hundred and twenty dollars, read as dollars it is a fortune.
    currency: Mapped[str] = mapped_column(String(8), default="IDR", nullable=False)
    total: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    # Lines carry `project_id` / `project_code` and their price-request origin,
    # so one order to one vendor can cover several jobs — the shipment is one
    # truck, the jobs are still separate.
    items: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    # Every project this PO feeds. `project_id` above is the single-job case
    # and stays set for it; this is what the project page queries so a
    # multi-job order shows up on all of them.
    project_ids: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False, index=True)


class GoodsReceipt(Base, UUIDPK, TimestampMixin):
    __tablename__ = "goods_receipts"

    po_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("supplier_pos.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    received_at: Mapped[date | None] = mapped_column(Date)
    items: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="received", nullable=False)


class QCReport(Base, UUIDPK, TimestampMixin):
    __tablename__ = "qc_reports"

    po_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("supplier_pos.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    pass_qty: Mapped[float] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    fail_qty: Mapped[float] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    findings: Mapped[str | None] = mapped_column(Text)
    decision: Mapped[str] = mapped_column(String(20), default="accepted", nullable=False)

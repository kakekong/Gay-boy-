from datetime import date
from uuid import UUID

from sqlalchemy import Date, ForeignKey, Numeric, String, Text
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
    contact: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
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
    total: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    items: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
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

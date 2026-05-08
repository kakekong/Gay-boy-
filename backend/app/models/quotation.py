from datetime import date
from uuid import UUID

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import AuthorshipMixin, SoftDeleteMixin, TimestampMixin, UUIDPK


class Product(Base, UUIDPK, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "products"

    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str | None] = mapped_column(String(120))
    uom: Mapped[str] = mapped_column(String(20), default="pcs", nullable=False)
    list_price: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    std_cost: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    spec: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class Quotation(Base, UUIDPK, TimestampMixin, AuthorshipMixin, SoftDeleteMixin):
    __tablename__ = "quotations"

    number: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    customer_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customers.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    project_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    parent_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("quotations.id", ondelete="SET NULL")
    )
    variant: Mapped[str] = mapped_column(String(20), default="detailed", nullable=False)
    sales_pic_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(8), default="IDR", nullable=False)
    subtotal: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    discount_pct: Mapped[float] = mapped_column(Numeric(6, 3), default=0, nullable=False)
    discount_amount: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    tax_pct: Mapped[float] = mapped_column(Numeric(6, 3), default=11, nullable=False)
    total: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    valid_until: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    pdf_url: Mapped[str | None] = mapped_column(String(500))

    items: Mapped[list["QuotationItem"]] = relationship(
        back_populates="quotation",
        cascade="all, delete-orphan",
        order_by="QuotationItem.line_no",
        lazy="selectin",
    )


class QuotationItem(Base, UUIDPK, TimestampMixin):
    __tablename__ = "quotation_items"

    quotation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("quotations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(10), default="product", nullable=False)
    product_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("products.id", ondelete="SET NULL")
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    spec: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    qty: Mapped[float] = mapped_column(Numeric(18, 4), default=1, nullable=False)
    uom: Mapped[str] = mapped_column(String(20), default="pcs", nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    cost_estimate: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    line_total: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)

    quotation: Mapped["Quotation"] = relationship(back_populates="items")

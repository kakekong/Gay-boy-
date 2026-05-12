from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPK


class InventoryItem(Base, UUIDPK, TimestampMixin):
    """Stockable item: spare parts, consumables, raw materials, etc."""

    __tablename__ = "inventory_items"

    sku: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str | None] = mapped_column(String(120), index=True)
    uom: Mapped[str] = mapped_column(String(20), default="pcs", nullable=False)
    unit_cost: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    current_stock: Mapped[float] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    reorder_point: Mapped[float] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    reorder_qty: Mapped[float] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    location: Mapped[str | None] = mapped_column(String(120))
    supplier_hint: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class InventoryMovement(Base, UUIDPK, TimestampMixin):
    """Audit trail for every stock change."""

    __tablename__ = "inventory_movements"

    item_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("inventory_items.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    delta: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    reason: Mapped[str] = mapped_column(String(40), nullable=False)
    # adjust | receive | issue | return | transfer
    reference: Mapped[str | None] = mapped_column(String(120))
    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    notes: Mapped[str | None] = mapped_column(Text)

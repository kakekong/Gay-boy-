from uuid import UUID

from sqlalchemy import ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPK


class SalesTarget(Base, UUIDPK, TimestampMixin):
    """Monthly revenue target for a salesperson."""

    __tablename__ = "sales_targets"
    __table_args__ = (UniqueConstraint("user_id", "period", name="uq_target_user_period"),)

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    period: Mapped[str] = mapped_column(String(7), nullable=False, index=True)  # YYYY-MM
    target_amount: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    set_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

"""Generic comment thread attachable to any entity.

Used for the discussion/chat thread on quotations and POs (customer +
supplier). owner_type namespaces the thread; owner_id ties it to the row.
"""

from uuid import UUID

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPK


class EntityComment(Base, UUIDPK, TimestampMixin):
    __tablename__ = "entity_comments"

    # e.g. "quotation" | "customer_po" | "supplier_po"
    owner_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    owner_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    author_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)

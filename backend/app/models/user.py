from uuid import UUID

from sqlalchemy import Boolean, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPK


class User(Base, UUIDPK, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # sales|admin|hr|manager|director|customer|supplier
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    whatsapp_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Portal scopes — only set for customer / supplier accounts
    linked_customer_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), index=True)
    linked_supplier_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), index=True)

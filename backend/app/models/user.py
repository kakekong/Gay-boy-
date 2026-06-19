from uuid import UUID

from sqlalchemy import Boolean, String
from sqlalchemy.dialects.postgresql import JSONB
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
    # Optional director-defined custom role (drives display name + sidebar
    # pages; the `role` column above is still the API security tier).
    custom_role_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), index=True)
    # Optional per-user sidebar page override. When set (non-empty), these
    # pages take precedence over the role / custom-role defaults — lets the
    # director tailor exactly which pages a single user sees.
    pages: Mapped[list | None] = mapped_column(JSONB, nullable=True)

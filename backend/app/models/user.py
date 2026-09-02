from datetime import date
from uuid import UUID

from sqlalchemy import Boolean, Date, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPK


class User(Base, UUIDPK, TimestampMixin):
    __tablename__ = "users"

    # The login. Unique, and the only thing `POST /auth/login` matches on.
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    # The address this person actually corresponds from — the one that goes
    # on a quotation the customer reads. Deliberately separate from the login
    # and deliberately NOT unique or indexed: it is a contact detail, not an
    # identity, two people can share a shared mailbox, and nothing may ever
    # authenticate against it.
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    # Storage path of this person's scanned signature, drawn into the
    # signature block of every document they sign. Same dispatch rule as
    # every other stored file: `s3://…` reads from the bucket, anything else
    # from disk (see services/storage.py).
    signature_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # sales|admin|hr|manager|director|customer|supplier
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    whatsapp_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # ── Employment record ────────────────────────────────────────────────
    # The day they started. HR's, not the login's: it drives length of
    # service, and payroll reads it for a first partial month.
    join_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Where their salary goes. Three fields because a transfer needs all
    # three — the bank, the number, and the name the account is held under,
    # which is often not spelled the way the employee's record spells it
    # ("atas nama"), and a mismatch is what bounces a payment.
    bank_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    bank_account_no: Mapped[str | None] = mapped_column(String(60), nullable=True)
    bank_account_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # The person this login belongs to. Required for every internal role and
    # refused for portal accounts — a customer's login is not an employee.
    # Unique: one person, one login. Nullable only so the column could be
    # added to a live table; `POST /users` will not create an internal
    # account without it.
    employee_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), unique=True, index=True)
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

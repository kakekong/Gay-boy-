from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPK


class Account(Base, UUIDPK, TimestampMixin):
    """Chart of Accounts entry."""

    __tablename__ = "accounts"

    account_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    name_en: Mapped[str | None] = mapped_column(String(255))
    account_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    balance: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    parent_account_no: Mapped[str | None] = mapped_column(String(40), index=True)
    is_parent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_suspended: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_tax: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class AccountArchive(Base, UUIDPK, TimestampMixin):
    """An account the director deleted, and where to get it back.

    Deleting writes the account and every line ever posted to it into a file
    in the document store (Cloudflare R2 in production), then takes both out
    of the database. For a week the same copy is also kept here, in `data`,
    so restoring is instant; after that only this row is left — a pointer to
    the file, which can still restore the account. `restored_at` marks one
    that came back."""

    __tablename__ = "account_archives"

    account_no: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    account_type: Mapped[str] = mapped_column(String(40), nullable=False)
    balance: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    entry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deleted_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    deleted_by_name: Mapped[str | None] = mapped_column(String(255))
    storage_path: Mapped[str | None] = mapped_column(Text)
    # The full copy, for the first week only.
    data: Mapped[dict | None] = mapped_column(JSONB)
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    restored_by_name: Mapped[str | None] = mapped_column(String(255))

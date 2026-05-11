from sqlalchemy import Boolean, Integer, Numeric, String, Text
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

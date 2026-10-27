from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin


class AppSetting(Base, TimestampMixin):
    """A company-wide setting, by name — e.g. `item_accounts`, the accounts a
    new item takes (Accurate's "Set sbg Default")."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

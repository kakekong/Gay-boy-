"""Custom roles — director-defined named roles with a page permission set.

A custom role pairs a human name (e.g. "Finance Manager") with:
  - base_role: one of the built-in Role values; drives all API-level
    security so existing access checks keep working unchanged.
  - pages: the list of sidebar page paths this role is allowed to see
    (e.g. ["/finance", "/finance/payment-verification", "/reports"]).

Users get pointed at a custom role via User.custom_role_id; their plain
`role` column is set to the custom role's base_role so nothing in the
permission layer has to learn about custom roles.
"""

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPK


class CustomRole(Base, UUIDPK, TimestampMixin):
    __tablename__ = "custom_roles"

    name: Mapped[str] = mapped_column(String(60), unique=True, nullable=False, index=True)
    # One of the built-in Role enum values; the API security tier.
    base_role: Mapped[str] = mapped_column(String(20), nullable=False, default="sales")
    # Allowed sidebar page paths.
    pages: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))

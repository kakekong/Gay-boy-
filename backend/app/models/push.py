"""Web Push — subscriptions + delivery ledger + VAPID keypair.

Real app-style notifications: the browser registers a service worker and a
push subscription; the backend signs pushes with a VAPID keypair and the
push service (FCM/Mozilla/Apple) wakes the device even when no tab is open.

- PushSubscription: one row per (user, device/browser) endpoint.
- PushDelivered:   which notification item-ids each user has already been
                   pushed, so the background sweeper never double-sends.
- VapidKeypair:    single-row keypair generated on first use and persisted
                   in the DB so it survives Space rebuilds with zero setup.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import UUIDPK


class PushSubscription(Base, UUIDPK):
    __tablename__ = "push_subscriptions"
    __table_args__ = (UniqueConstraint("endpoint", name="uq_push_endpoint"),)

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    p256dh: Mapped[str] = mapped_column(String(255), nullable=False)
    auth: Mapped[str] = mapped_column(String(255), nullable=False)
    user_agent: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PushDelivered(Base, UUIDPK):
    __tablename__ = "push_delivered"
    __table_args__ = (
        UniqueConstraint("user_id", "item_id", name="uq_push_delivered"),
    )

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # The stable id of the notification item (e.g. "dp-finance:<uuid>").
    item_id: Mapped[str] = mapped_column(String(120), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class NotificationDismissed(Base, UUIDPK):
    """Bell items a user swiped away. The bell is computed live, so a
    dismissal is a per-user filter on item ids — the item disappears from
    that user's bell (and future pushes) until it resolves on its own.
    Rows are pruned after 30 days by the sweeper."""
    __tablename__ = "notification_dismissed"
    __table_args__ = (
        UniqueConstraint("user_id", "item_id", name="uq_notif_dismissed"),
    )

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    item_id: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class VapidKeypair(Base, UUIDPK):
    __tablename__ = "vapid_keypair"

    private_pem: Mapped[str] = mapped_column(Text, nullable=False)
    public_key: Mapped[str] = mapped_column(Text, nullable=False)  # URL-safe b64
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

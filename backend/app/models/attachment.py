from uuid import UUID

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPK


class Attachment(Base, UUIDPK, TimestampMixin):
    """File attached to a customer / quotation / project."""

    __tablename__ = "attachments"

    owner_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    # owner_type: customer | quotation | project
    owner_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(120))
    size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    # When set, this "attachment" is an external LINK, not an uploaded file
    # (storage_path is empty). Lets people reference a Drive/Dropbox URL that
    # survives Space rebuilds, since uploaded files live on ephemeral storage.
    external_url: Mapped[str | None] = mapped_column(String(1000))
    description: Mapped[str | None] = mapped_column(Text)
    uploaded_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

"""A record of what an import created, so it can be taken back out.

Importing hundreds of rows into a live system is only a reasonable thing to do
if getting them out again is one action rather than several hundred. The
record-picker can delete anything, but nobody is going to tick 87 customers by
hand at nine at night because a column mapped wrong.

So every commit writes a run, and every row it creates is listed against that
run. Undo then means "delete exactly what this run made" — not "delete
everything that looks like it came from a spreadsheet", which would also take
the customer somebody typed in by hand ten minutes later.

The list is a separate table rather than a column on each record because the
four things that can be imported have nothing else in common: a chart-of-
accounts row and a quotation share no shape, no base class and no spare JSON
column between them.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import TimestampMixin, UUIDPK


class ImportRun(Base, UUIDPK, TimestampMixin):
    """One press of the Import button."""

    __tablename__ = "import_runs"

    # customers | accounts | items | quotations
    kind: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    filename: Mapped[str | None] = mapped_column(String(255))
    created_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    # Set when the run has been undone. The row itself stays, because "this
    # import was reversed on Thursday" is worth being able to answer later.
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    undone_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    records: Mapped[list["ImportedRecord"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", lazy="selectin",
    )


class ImportedRecord(Base, UUIDPK):
    """One row an import created.

    `record_id` is deliberately not a foreign key: it points at one of four
    different tables depending on `record_type`, and the row it names is
    expected to be deleted out from under it — by the undo itself, or by
    somebody using the record picker later. A dangling entry here means "this
    import made that, and it is gone now", which is the truth.
    """

    __tablename__ = "imported_records"

    run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("import_runs.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    record_type: Mapped[str] = mapped_column(String(30), nullable=False)
    record_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )

    run: Mapped["ImportRun"] = relationship(back_populates="records")

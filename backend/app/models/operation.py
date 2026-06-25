from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import AuthorshipMixin, SoftDeleteMixin, TimestampMixin, UUIDPK


class Project(Base, UUIDPK, TimestampMixin, AuthorshipMixin, SoftDeleteMixin):
    __tablename__ = "projects"

    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    customer_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("customers.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    quotation_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("quotations.id", ondelete="SET NULL")
    )
    # The approved price request this project fulfils, so purchasing knows
    # exactly what order it is working without seeing the deal economics.
    price_request_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), index=True)
    po_number: Mapped[str | None] = mapped_column(String(80))
    po_date: Mapped[date | None] = mapped_column(Date)
    po_value: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date)
    target_delivery: Mapped[date | None] = mapped_column(Date)
    actual_delivery: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(30), default="new", nullable=False, index=True)
    margin_estimate: Mapped[float] = mapped_column(Numeric(8, 4), default=0, nullable=False)
    margin_actual: Mapped[float] = mapped_column(Numeric(8, 4), default=0, nullable=False)
    # Shipping timeline — especially useful for imports
    est_ship_from_origin:     Mapped[date | None] = mapped_column(Date)
    act_ship_from_origin:     Mapped[date | None] = mapped_column(Date)
    est_arrive_our_warehouse: Mapped[date | None] = mapped_column(Date)
    act_arrive_our_warehouse: Mapped[date | None] = mapped_column(Date)
    est_arrive_customer:      Mapped[date | None] = mapped_column(Date)
    act_arrive_customer:      Mapped[date | None] = mapped_column(Date)
    origin_location:          Mapped[str | None]  = mapped_column(String(120))
    is_import:                Mapped[bool]        = mapped_column(Boolean, default=False, nullable=False)
    # ── Post-drawing logistics (set by purchasing) ─────────────────────────
    # How the goods arrive — drives which import documents are required.
    #   local | direct_import | agent
    delivery_mode:        Mapped[str]             = mapped_column(String(20), default="local", nullable=False)
    # Purchasing's estimated delivery date, set after the drawing is approved.
    est_delivery_date:    Mapped[date | None]     = mapped_column(Date)
    # Stamped when purchasing confirms the date (spawns the receiving WO).
    delivery_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Import-document checklist: {key: {collected: bool, attachment_id, note}}
    import_docs:          Mapped[dict]            = mapped_column(JSONB, default=dict, nullable=False)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


# Project lifecycle stages, in order. The project status is read-only in the
# UI — nobody sets it from a dropdown. It reflects where the project actually
# is, advanced forward by real events (e.g. the customer approving a drawing
# moves it to `drawing_approved`). It never moves backward on its own.
PROJECT_STATUS_ORDER: list[str] = [
    "new", "drawing", "drawing_approved", "purchasing",
    "production", "qc", "packaging", "delivered", "invoiced", "paid", "closed",
]


def advance_project_status(project: "Project", to_status: str) -> bool:
    """Move `project` forward to `to_status` only if that's later in the
    pipeline than where it already is. Returns True when the status changed.

    Never regresses (a project already in production won't drop back to
    drawing_approved), and a status outside PROJECT_STATUS_ORDER is left
    untouched — so this is always safe to call on a real event.
    """
    order = PROJECT_STATUS_ORDER
    try:
        cur = order.index(project.status)
        nxt = order.index(to_status)
    except ValueError:
        return False
    if nxt > cur:
        project.status = to_status
        return True
    return False


class WorkOrder(Base, UUIDPK, TimestampMixin):
    __tablename__ = "work_orders"

    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    stage: Mapped[str] = mapped_column(String(30), nullable=False, default="receiving")
    notes: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Drawing(Base, UUIDPK, TimestampMixin):
    __tablename__ = "drawings"

    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    file_url: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False)
    customer_decision_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)


class DeliveryOrder(Base, UUIDPK, TimestampMixin):
    __tablename__ = "delivery_orders"

    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    number: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    split_index: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    courier: Mapped[str | None] = mapped_column(String(120))
    tracking_no: Mapped[str | None] = mapped_column(String(120))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False, index=True)
    items: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

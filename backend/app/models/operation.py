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
    # ── Operations QC + customer handover ──────────────────────────────────
    # Operations runs a final check; passing QC hands the project to admin to
    # issue the delivery order + invoice. Failing parks it with findings.
    qc_decision:          Mapped[str | None]      = mapped_column(String(20))
    qc_passed_at:         Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Stamped by admin once the customer confirms they received the goods.
    customer_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


# Project lifecycle stages, in order. The project status is read-only in the
# UI — nobody sets it from a dropdown. It reflects where the project actually
# is, advanced forward by real events (e.g. the customer approving a drawing
# moves it to `drawing_approved`). It never moves backward on its own.
#
# Purchasing files the supplier PO first (that trigger sets 'purchasing').
# Then the supplier posts a drawing (→ drawing), the director approves it
# (→ drawing_approved), ops does the physical work (production → QC →
# packaging), finance invoices (→ invoiced) and admin confirms delivery
# (→ delivered), then verified payment closes it out (→ paid → closed).
PROJECT_STATUS_ORDER: list[str] = [
    "new", "purchasing", "drawing", "drawing_approved",
    "production", "qc", "packaging", "invoiced", "delivered", "paid", "closed",
]


def advance_project_status(project: "Project", to_status: str) -> bool:
    """Move `project` forward to the milestone `to_status` an event represents.

    Each caller passes the stage its event actually completes (supplier PO →
    'purchasing', drawing approved → 'drawing_approved', confirm-delivery →
    'production', …). We jump straight to that stage — the project reflects the
    FURTHEST milestone reached, regardless of the order events fire in. This
    keeps the pipeline order-independent: doing the drawing before the supplier
    PO (or vice-versa) both land the project correctly instead of lagging a
    stage behind and blocking downstream gates (e.g. the QC work order).

    Forward-only: a target at or behind the current stage is a no-op (never
    regresses). A status outside PROJECT_STATUS_ORDER is left untouched — safe
    on unknown / legacy values. The real "not too early" protection lives in the
    work-order stage gates, which check the project has reached the required
    stage independently of this walk.
    """
    order = PROJECT_STATUS_ORDER
    try:
        cur = order.index(project.status)
        nxt = order.index(to_status)
    except ValueError:
        return False
    if nxt <= cur:
        return False
    project.status = to_status
    return True


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
    # 'customer' | 'supplier'. Two different documents that used to share one
    # pile: the supplier's drawing is what the vendor sent us to make the part
    # from, and the customer's is what we show the customer for approval. They
    # have different authors, different readers, and the second is produced
    # *from* the first — so which one a row is decides who may see it at all.
    kind: Mapped[str] = mapped_column(String(20), default="customer",
                                      nullable=False, index=True)
    # Set on a customer drawing that was drawn up from a supplier's. Keeps the
    # lineage visible so nobody has to remember which vendor sheet it came off.
    source_drawing_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("drawings.id", ondelete="SET NULL")
    )
    file_url: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False)
    # Who posted the drawing — so they can re-upload a revised file after the
    # director requests a revision.
    uploaded_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    customer_decision_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Who signed off (director, internally) and when. Distinct from the legacy
    # customer_decision_at so both the internal and customer paths are tracked.
    decided_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
    # Director-side proof verification: admin uploads the proof, director
    # verifies it. Marking a DO delivered requires verification first.
    verified_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

"""Purchasing module — PR → RFQ → PO → GR → QC → Payment.

Stubs scaffolded; full implementation follows the same pattern as quotations.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approval import request_approval
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.permissions import Role, require
from app.models.approval import ApprovalRequest, ApprovalStatus
from app.models.purchasing import Supplier
from app.models.user import User

router = APIRouter()

_admin_or_director = require(Role.ADMIN, Role.DIRECTOR, Role.MANAGER)


# ─── Suppliers ───────────────────────────────────────────────────────────────

class SupplierIn(BaseModel):
    name: str
    category: str | None = None
    rating: float = 0
    contact: dict = {}


@router.get("/suppliers")
async def list_suppliers(
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(get_current_user),
):
    rows = (await db.scalars(
        select(Supplier).order_by(Supplier.name.asc())
    )).all()
    return [
        {
            "id": str(s.id),
            "name": s.name,
            "category": s.category,
            "rating": float(s.rating or 0),
            "lead_time_days_avg": float(s.lead_time_days_avg or 0),
            "qc_fail_rate": float(s.qc_fail_rate or 0),
        }
        for s in rows
    ]


@router.get("/suppliers/{supplier_id}")
async def get_supplier(
    supplier_id: UUID,
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(get_current_user),
):
    """Supplier detail with a recap of POs we've issued. Used by the
    new supplier detail screen behind a click on the Purchasing board."""
    from app.models.purchasing import Supplier, SupplierPO

    s = await db.get(Supplier, supplier_id)
    if not s:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Supplier not found")
    po_rows = (await db.scalars(
        select(SupplierPO)
        .where(SupplierPO.supplier_id == supplier_id)
        .order_by(SupplierPO.created_at.desc())
    )).all()
    open_pos = [p for p in po_rows if p.status in ("open", "pending_approval")]
    return {
        "id": str(s.id),
        "name": s.name,
        "category": s.category,
        "rating": float(s.rating or 0),
        "lead_time_days_avg": float(s.lead_time_days_avg or 0),
        "qc_fail_rate": float(s.qc_fail_rate or 0),
        "price_volatility": float(s.price_volatility or 0),
        "contact": s.contact or {},
        "po_count": len(po_rows),
        "open_po_count": len(open_pos),
        "lifetime_value": float(sum(float(p.total or 0) for p in po_rows)),
        "purchase_orders": [
            {
                "id": str(p.id),
                "number": p.number,
                "status": p.status,
                "po_date": p.po_date,
                "total": float(p.total or 0),
                "project_id": str(p.project_id) if p.project_id else None,
            }
            for p in po_rows
        ],
    }


@router.post("/suppliers", status_code=201)
async def create_supplier(
    payload: SupplierIn,
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_admin_or_director),
):
    if not payload.name.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Name required")
    existing = await db.scalar(select(Supplier).where(Supplier.name == payload.name.strip()))
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Supplier with this name already exists")
    s = Supplier(
        name=payload.name.strip(),
        category=payload.category,
        rating=payload.rating,
        contact=payload.contact or {},
    )
    db.add(s)
    await db.flush()
    return {"id": str(s.id), "name": s.name}


# ─── Supplier POs ────────────────────────────────────────────────────────────

class PoCreate(BaseModel):
    supplier_id: UUID
    project_id: UUID
    po_date: str | None = None  # ISO date
    quoted_lead_days: int | None = None
    items: list[dict] = []
    total: float = 0
    number: str | None = None  # auto-generated if missing


_purchasing_or_director = require(Role.PURCHASING, Role.MANAGER, Role.DIRECTOR, Role.ADMIN)
_director_only = require(Role.DIRECTOR)


@router.get("/po")
async def list_pos(
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_purchasing_or_director),
    supplier_id: UUID | None = None,
    project_id: UUID | None = None,
    customer_id: UUID | None = None,
):
    """All supplier POs.

    Rows are enriched with supplier / project / customer / sales-rep
    context so the list view, the PO recap and the per-customer PO
    section can render in one round-trip. Use ?customer_id=… to scope
    to a single customer's POs (joined via project.customer_id).
    """
    from app.models.crm import Customer
    from app.models.operation import Project
    from app.models.purchasing import Supplier, SupplierPO

    stmt = select(SupplierPO).order_by(SupplierPO.created_at.desc())
    if supplier_id:
        stmt = stmt.where(SupplierPO.supplier_id == supplier_id)
    if project_id:
        stmt = stmt.where(SupplierPO.project_id == project_id)
    if customer_id:
        # Join via project to filter by customer.
        stmt = (
            stmt.join(Project, Project.id == SupplierPO.project_id)
            .where(Project.customer_id == customer_id)
        )
    rows = (await db.scalars(stmt)).all()

    # Batch-load related rows so we don't N+1 supplier / project / customer
    # / sales-rep lookups inside the list comprehension.
    supplier_ids = {r.supplier_id for r in rows if r.supplier_id}
    project_ids  = {r.project_id  for r in rows if r.project_id}
    suppliers: dict[UUID, Supplier] = {}
    projects:  dict[UUID, Project]  = {}
    if supplier_ids:
        for s in (await db.scalars(
            select(Supplier).where(Supplier.id.in_(supplier_ids))
        )).all():
            suppliers[s.id] = s
    if project_ids:
        for p in (await db.scalars(
            select(Project).where(Project.id.in_(project_ids))
        )).all():
            projects[p.id] = p

    customer_ids = {p.customer_id for p in projects.values() if p.customer_id}
    customers: dict[UUID, Customer] = {}
    if customer_ids:
        for c in (await db.scalars(
            select(Customer).where(Customer.id.in_(customer_ids))
        )).all():
            customers[c.id] = c

    sales_ids = {c.sales_pic_id for c in customers.values() if c.sales_pic_id}
    sales_users: dict[UUID, User] = {}
    if sales_ids:
        for u in (await db.scalars(
            select(User).where(User.id.in_(sales_ids))
        )).all():
            sales_users[u.id] = u

    out = []
    for r in rows:
        proj = projects.get(r.project_id) if r.project_id else None
        cust = customers.get(proj.customer_id) if proj else None
        sales = sales_users.get(cust.sales_pic_id) if cust and cust.sales_pic_id else None
        sup = suppliers.get(r.supplier_id)
        out.append({
            "id": str(r.id), "number": r.number, "status": r.status,
            "supplier_id": str(r.supplier_id),
            "supplier_name": sup.name if sup else None,
            "project_id": str(r.project_id) if r.project_id else None,
            "project_code": proj.code if proj else None,
            "customer_id": str(cust.id) if cust else None,
            "customer_name": cust.company_name if cust else None,
            "sales_pic_id": str(sales.id) if sales else None,
            "sales_pic_name": sales.full_name if sales else None,
            "po_date": r.po_date, "total": float(r.total or 0),
            "quoted_lead_days": r.quoted_lead_days,
            "items": r.items, "created_at": r.created_at,
        })
    return out


@router.post("/po", status_code=201)
async def create_po(
    payload: PoCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_purchasing_or_director),
):
    """Create a supplier PO. Every step in the PO lifecycle is gated on
    director approval: when a non-director submits this, the PO is
    created with status='pending_approval' and an ApprovalRequest is
    filed for the director. The director sees it in /approvals and can
    flip it to 'open' (or 'cancelled') from there. Director themselves
    short-circuit and the PO comes up 'open' immediately.
    """
    from datetime import date as date_t

    from app.models.operation import Project
    from app.models.purchasing import Supplier, SupplierPO

    supplier = await db.get(Supplier, payload.supplier_id)
    if not supplier:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown supplier")
    project = await db.get(Project, payload.project_id)
    if not project:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown project")

    number = payload.number
    if not number:
        prefix = "PO"
        ts = date_t.today().strftime("%y%m%d")
        # Count today's POs for a short suffix
        existing = await db.scalar(
            select(func.count(SupplierPO.id)).where(SupplierPO.number.like(f"{prefix}-{ts}-%"))
        ) or 0
        number = f"{prefix}-{ts}-{existing + 1:03d}"

    po_date_parsed = None
    if payload.po_date:
        try:
            po_date_parsed = date_t.fromisoformat(payload.po_date)
        except ValueError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "po_date must be YYYY-MM-DD")

    is_director = Role(user.role) == Role.DIRECTOR
    po = SupplierPO(
        number=number,
        supplier_id=payload.supplier_id,
        project_id=payload.project_id,
        po_date=po_date_parsed,
        quoted_lead_days=payload.quoted_lead_days,
        total=payload.total,
        items=payload.items,
        status="open" if is_director else "pending_approval",
    )
    db.add(po)
    await db.flush()

    if not is_director:
        await request_approval(
            db,
            target_type="supplier_po",
            target_id=po.id,
            requested_by=user.id,
            required_role=Role.DIRECTOR,
            reason=f"Create PO {po.number} ({supplier.name}, project {project.code})",
            payload={"action": "create"},
        )

    return {
        "id": str(po.id), "number": po.number,
        "supplier_id": str(po.supplier_id),
        "project_id": str(po.project_id),
        "status": po.status,
        "pending_approval": not is_director,
    }


@router.get("/po/{po_id}")
async def get_po(
    po_id: UUID,
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_purchasing_or_director),
):
    """Full PO detail with supplier and project context for the detail page."""
    from app.models.operation import Project
    from app.models.purchasing import Supplier, SupplierPO

    po = await db.get(SupplierPO, po_id)
    if not po:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "PO not found")
    supplier = await db.get(Supplier, po.supplier_id) if po.supplier_id else None
    project = await db.get(Project, po.project_id) if po.project_id else None
    return {
        "id": str(po.id),
        "number": po.number,
        "status": po.status,
        "supplier_id": str(po.supplier_id),
        "supplier_name": supplier.name if supplier else None,
        "supplier_category": supplier.category if supplier else None,
        "project_id": str(po.project_id) if po.project_id else None,
        "project_code": project.code if project else None,
        "project_status": project.status if project else None,
        "project_target_delivery": project.target_delivery if project else None,
        "project_actual_delivery": project.actual_delivery if project else None,
        "po_date": po.po_date,
        "quoted_lead_days": po.quoted_lead_days,
        "total": float(po.total or 0),
        "items": po.items,
        "created_at": po.created_at,
    }


class POPatch(BaseModel):
    number: str | None = None
    po_date: str | None = None        # ISO YYYY-MM-DD
    quoted_lead_days: int | None = None
    total: float | None = None
    status: str | None = None         # open | received | closed | cancelled
    items: list | None = None


@router.patch("/po/{po_id}")
async def update_po(
    po_id: UUID,
    payload: POPatch,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_purchasing_or_director),
):
    """Update an existing supplier PO. Every change is gated on director
    approval: when a non-director submits this, the PO is left untouched
    and an ApprovalRequest is filed with the proposed changes in its
    payload. The director sees it in /approvals and the changes are
    applied when they approve. Director themselves apply immediately.

    Renaming the PO number is allowed but the new value must be unique —
    a conflict returns 409 so the UI can show "that number's already
    used" instead of letting the DB raise an opaque IntegrityError.
    """
    from datetime import date as date_t
    from app.models.purchasing import SupplierPO

    po = await db.get(SupplierPO, po_id)
    if not po:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "PO not found")

    data = payload.model_dump(exclude_unset=True)

    # Validate without mutating — same checks regardless of approval path,
    # so we never queue a doomed approval the director can't apply later.
    if "number" in data:
        new_num = (data["number"] or "").strip()
        if not new_num:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "PO number cannot be empty")
        if new_num != po.number:
            clash = await db.scalar(
                select(SupplierPO).where(
                    SupplierPO.number == new_num, SupplierPO.id != po_id
                )
            )
            if clash:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"PO number '{new_num}' is already used by another PO",
                )
        data["number"] = new_num
    if "po_date" in data and data["po_date"] not in (None, ""):
        try:
            date_t.fromisoformat(data["po_date"])
        except ValueError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "po_date must be YYYY-MM-DD")

    is_director = Role(user.role) == Role.DIRECTOR
    if not is_director:
        # Drop the field outright if it would clear an existing date — the
        # rule everywhere else in the app is "null doesn't wipe protected
        # dates". The director can still set a date explicitly.
        if data.get("po_date") in (None, ""):
            data.pop("po_date", None)
        await request_approval(
            db,
            target_type="supplier_po",
            target_id=po.id,
            requested_by=user.id,
            required_role=Role.DIRECTOR,
            reason=f"Update PO {po.number}: {', '.join(sorted(data.keys())) or 'no fields'}",
            payload={"action": "update", "changes": data},
        )
        raise HTTPException(
            status.HTTP_202_ACCEPTED,
            "Submitted for director approval; changes will apply once approved.",
        )

    # Director path: apply immediately.
    if "number" in data:
        po.number = data["number"]
    if "po_date" in data:
        raw = data["po_date"]
        po.po_date = None if raw in (None, "") else date_t.fromisoformat(raw)
    if "quoted_lead_days" in data:
        po.quoted_lead_days = data["quoted_lead_days"]
    if "total" in data and data["total"] is not None:
        po.total = data["total"]
    if "status" in data and data["status"]:
        po.status = data["status"]
    if "items" in data and data["items"] is not None:
        po.items = data["items"]

    await db.flush()
    return {
        "id": str(po.id), "number": po.number, "status": po.status,
        "supplier_id": str(po.supplier_id),
        "project_id": str(po.project_id) if po.project_id else None,
        "po_date": po.po_date, "total": float(po.total or 0),
        "quoted_lead_days": po.quoted_lead_days,
        "items": po.items,
    }


# ─── PR / RFQ / PO stubs (kept) ──────────────────────────────────────────────

# PR/RFQ/GR/QC are intentionally not implemented in this build — the
# director-owned PO flow (POST /purchasing/po) covers the procurement
# loop. These stubs return 501 so a caller never thinks a TODO succeeded.

@router.get("/pr")
async def list_pr(_user: User = Depends(get_current_user)):
    return []


def _not_implemented():
    raise HTTPException(
        status.HTTP_501_NOT_IMPLEMENTED,
        "Not in this release — use the director PO flow at POST /purchasing/po",
    )


@router.post("/pr")
async def create_pr(_user: User = Depends(_director_only)):
    _not_implemented()


@router.post("/pr/{pr_id}/rfq")
async def spawn_rfq(pr_id: str, _user: User = Depends(_director_only)):
    _not_implemented()


@router.post("/rfq/{rfq_id}/po")
async def rfq_to_po(rfq_id: str, _user: User = Depends(_director_only)):
    _not_implemented()


@router.post("/po/{po_id}/gr")
async def goods_receipt(po_id: str, _user: User = Depends(_director_only)):
    _not_implemented()


@router.post("/po/{po_id}/qc")
async def qc(po_id: str, _user: User = Depends(_director_only)):
    _not_implemented()

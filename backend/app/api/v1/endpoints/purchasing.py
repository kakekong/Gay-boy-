"""Purchasing module — PR → RFQ → PO → GR → QC → Payment.

Stubs scaffolded; full implementation follows the same pattern as quotations.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.permissions import Role, require
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
    _u: User = Depends(_director_only),
    supplier_id: UUID | None = None,
    project_id: UUID | None = None,
):
    from app.models.purchasing import SupplierPO
    stmt = select(SupplierPO).order_by(SupplierPO.created_at.desc())
    if supplier_id:
        stmt = stmt.where(SupplierPO.supplier_id == supplier_id)
    if project_id:
        stmt = stmt.where(SupplierPO.project_id == project_id)
    rows = (await db.scalars(stmt)).all()
    return [
        {
            "id": str(r.id), "number": r.number, "status": r.status,
            "supplier_id": str(r.supplier_id),
            "project_id": str(r.project_id) if r.project_id else None,
            "po_date": r.po_date, "total": float(r.total or 0),
            "quoted_lead_days": r.quoted_lead_days,
            "items": r.items, "created_at": r.created_at,
        }
        for r in rows
    ]


@router.post("/po", status_code=201)
async def create_po(
    payload: PoCreate,
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_director_only),
):
    """Issue a supplier PO — **director only** to limit exposure of the
    supplier⇄customer mapping. The PO must reference a supplier and a
    project so the supplier portal can show it and updates flow to the
    customer.
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

    po = SupplierPO(
        number=number,
        supplier_id=payload.supplier_id,
        project_id=payload.project_id,
        po_date=po_date_parsed,
        quoted_lead_days=payload.quoted_lead_days,
        total=payload.total,
        items=payload.items,
        status="open",
    )
    db.add(po)
    await db.flush()
    return {
        "id": str(po.id), "number": po.number,
        "supplier_id": str(po.supplier_id),
        "project_id": str(po.project_id),
    }


# ─── PR / RFQ / PO stubs (kept) ──────────────────────────────────────────────

@router.get("/pr")
async def list_pr(_user: User = Depends(get_current_user)):
    return []


@router.post("/pr")
async def create_pr(_user: User = Depends(get_current_user)):
    return {"status": "todo"}


@router.post("/pr/{pr_id}/rfq")
async def spawn_rfq(pr_id: str, _user: User = Depends(get_current_user)):
    return {"pr_id": pr_id, "rfqs": []}


@router.post("/rfq/{rfq_id}/po")
async def rfq_to_po(rfq_id: str, _user: User = Depends(get_current_user)):
    return {"rfq_id": rfq_id, "po_id": "todo"}


@router.post("/po/{po_id}/gr")
async def goods_receipt(po_id: str, _user: User = Depends(get_current_user)):
    return {"po_id": po_id, "gr_id": "todo"}


@router.post("/po/{po_id}/qc")
async def qc(po_id: str, _user: User = Depends(get_current_user)):
    return {"po_id": po_id, "qc_id": "todo"}

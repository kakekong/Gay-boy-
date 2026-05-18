"""Purchasing module — PR → RFQ → PO → GR → QC → Payment.

Stubs scaffolded; full implementation follows the same pattern as quotations.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
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

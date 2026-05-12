"""Inventory endpoints.

Everyone can VIEW stock (so sales can answer 'do we have this in stock?').
Only admin/director can CREATE / EDIT items or ADJUST stock.
Any logged-in user can REQUEST AN ORDER — this creates a PurchaseRequest
that purchasing handles via the existing flow.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.permissions import Role, require
from app.models.inventory import InventoryItem, InventoryMovement
from app.models.purchasing import PurchaseRequest
from app.models.user import User

router = APIRouter()
_editor = require(Role.ADMIN, Role.DIRECTOR)


# ─── Schemas ─────────────────────────────────────────────────────────────────

class ItemIn(BaseModel):
    sku: str
    name: str
    category: str | None = None
    uom: str = "pcs"
    unit_cost: float = 0
    current_stock: float = 0
    reorder_point: float = 0
    reorder_qty: float = 0
    location: str | None = None
    supplier_hint: str | None = None
    notes: str | None = None
    is_active: bool = True


class ItemPatch(BaseModel):
    name: str | None = None
    category: str | None = None
    uom: str | None = None
    unit_cost: float | None = None
    reorder_point: float | None = None
    reorder_qty: float | None = None
    location: str | None = None
    supplier_hint: str | None = None
    notes: str | None = None
    is_active: bool | None = None


class AdjustIn(BaseModel):
    delta: float
    reason: str = "adjust"   # adjust | receive | issue | return | transfer
    reference: str | None = None
    notes: str | None = None


class OrderIn(BaseModel):
    qty: float | None = None    # default = reorder_qty
    notes: str | None = None


class ItemOut(ItemIn):
    id: UUID
    stock_status: str   # ok | low | out
    model_config = {"from_attributes": True}


def _status(item: InventoryItem) -> str:
    stock = float(item.current_stock or 0)
    rp = float(item.reorder_point or 0)
    if stock <= 0:
        return "out"
    if stock < rp:
        return "low"
    return "ok"


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.get("")
async def list_items(
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(get_current_user),
    q: str | None = None,
    category: str | None = None,
    only_low: bool = False,
    only_active: bool = True,
):
    stmt = select(InventoryItem).order_by(InventoryItem.name.asc())
    if only_active:
        stmt = stmt.where(InventoryItem.is_active.is_(True))
    if q:
        like = f"%{q}%"
        stmt = stmt.where((InventoryItem.name.ilike(like)) | (InventoryItem.sku.ilike(like)))
    if category:
        stmt = stmt.where(InventoryItem.category == category)
    rows = (await db.scalars(stmt)).all()
    out = []
    for r in rows:
        st = _status(r)
        if only_low and st == "ok":
            continue
        out.append({
            "id": str(r.id),
            "sku": r.sku, "name": r.name, "category": r.category,
            "uom": r.uom, "unit_cost": float(r.unit_cost or 0),
            "current_stock": float(r.current_stock or 0),
            "reorder_point": float(r.reorder_point or 0),
            "reorder_qty": float(r.reorder_qty or 0),
            "location": r.location, "supplier_hint": r.supplier_hint,
            "notes": r.notes, "is_active": r.is_active,
            "stock_status": st,
        })
    return out


@router.get("/categories")
async def categories(db: AsyncSession = Depends(get_db),
                     _u: User = Depends(get_current_user)):
    rows = await db.scalars(
        select(InventoryItem.category)
        .where(InventoryItem.category.is_not(None))
        .distinct()
    )
    return sorted({c for c in rows if c})


@router.get("/{item_id}")
async def get_item(item_id: UUID,
                   db: AsyncSession = Depends(get_db),
                   _u: User = Depends(get_current_user)):
    r = await db.get(InventoryItem, item_id)
    if not r:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return {
        "id": str(r.id), "sku": r.sku, "name": r.name, "category": r.category,
        "uom": r.uom, "unit_cost": float(r.unit_cost or 0),
        "current_stock": float(r.current_stock or 0),
        "reorder_point": float(r.reorder_point or 0),
        "reorder_qty": float(r.reorder_qty or 0),
        "location": r.location, "supplier_hint": r.supplier_hint,
        "notes": r.notes, "is_active": r.is_active,
        "stock_status": _status(r),
    }


@router.get("/{item_id}/movements")
async def list_movements(item_id: UUID,
                         db: AsyncSession = Depends(get_db),
                         _u: User = Depends(get_current_user),
                         limit: int = Query(50, ge=1, le=500)):
    rows = (await db.scalars(
        select(InventoryMovement)
        .where(InventoryMovement.item_id == item_id)
        .order_by(InventoryMovement.created_at.desc())
        .limit(limit)
    )).all()
    return [
        {
            "id": str(m.id), "delta": float(m.delta),
            "reason": m.reason, "reference": m.reference,
            "notes": m.notes, "user_id": str(m.user_id) if m.user_id else None,
            "at": m.created_at,
        }
        for m in rows
    ]


@router.post("", status_code=201)
async def create_item(payload: ItemIn,
                      db: AsyncSession = Depends(get_db),
                      _u: User = Depends(_editor)):
    existing = await db.scalar(select(InventoryItem).where(InventoryItem.sku == payload.sku))
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "SKU already exists.")
    r = InventoryItem(**payload.model_dump())
    db.add(r)
    await db.flush()
    return {"id": str(r.id), "ok": True}


@router.patch("/{item_id}")
async def update_item(item_id: UUID,
                      payload: ItemPatch,
                      db: AsyncSession = Depends(get_db),
                      _u: User = Depends(_editor)):
    r = await db.get(InventoryItem, item_id)
    if not r:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(r, k, v)
    return {"id": str(r.id), "ok": True}


@router.delete("/{item_id}", status_code=204)
async def delete_item(item_id: UUID,
                      db: AsyncSession = Depends(get_db),
                      _u: User = Depends(_editor)):
    r = await db.get(InventoryItem, item_id)
    if not r:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    has_moves = await db.scalar(
        select(func.count(InventoryMovement.id)).where(InventoryMovement.item_id == item_id)
    )
    if has_moves:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Cannot delete: this item has movement history.")
    await db.delete(r)
    return None


@router.post("/{item_id}/adjust")
async def adjust_stock(item_id: UUID,
                       payload: AdjustIn,
                       db: AsyncSession = Depends(get_db),
                       user: User = Depends(_editor)):
    r = await db.get(InventoryItem, item_id)
    if not r:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    new_stock = float(r.current_stock or 0) + float(payload.delta)
    if new_stock < 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Resulting stock would be negative.")
    r.current_stock = new_stock
    db.add(InventoryMovement(
        item_id=item_id, delta=payload.delta, reason=payload.reason,
        reference=payload.reference, notes=payload.notes, user_id=user.id,
    ))
    await db.flush()
    return {"id": str(r.id), "current_stock": new_stock, "status": _status(r)}


@router.post("/{item_id}/request-order")
async def request_order(item_id: UUID,
                        payload: OrderIn,
                        db: AsyncSession = Depends(get_db),
                        user: User = Depends(get_current_user)):
    """Any logged-in employee can request an order. Creates a PurchaseRequest."""
    r = await db.get(InventoryItem, item_id)
    if not r:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    qty = payload.qty or float(r.reorder_qty or 0)
    if qty <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Quantity required (set reorder_qty or pass qty).")
    # PR number: PR-YYYY-NNNN
    year = datetime.now(UTC).year
    prefix = f"PR-{year}-"
    seq = await db.scalar(
        select(func.count(PurchaseRequest.id))
        .where(PurchaseRequest.number.like(f"{prefix}%"))
    ) or 0
    pr = PurchaseRequest(
        number=f"{prefix}{seq + 1:04d}",
        requested_by=user.id,
        items=[{
            "sku": r.sku, "name": r.name, "qty": qty, "uom": r.uom,
            "supplier_hint": r.supplier_hint,
            "unit_cost": float(r.unit_cost or 0),
            "from_inventory_id": str(item_id),
        }],
        status="open",
        notes=payload.notes,
    )
    db.add(pr)
    await db.flush()
    return {"purchase_request_id": str(pr.id), "number": pr.number, "qty": qty}

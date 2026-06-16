"""Director-managed custom roles.

A custom role = a name + a base access tier (one of the built-in roles)
+ the set of sidebar pages it's allowed to see. Lets the director spin
up roles like "Finance Manager" or "Junior Sales" without code changes,
Discord-style: pick a name, pick what they can access.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.permissions import Role, require
from app.models.custom_role import CustomRole
from app.models.user import User

router = APIRouter()
_director = require(Role.DIRECTOR)

# The catalogue of pages a custom role can be granted. Keep `path` in
# sync with the frontend routes / sidebar `to` values.
PAGE_CATALOG = [
    {"path": "/", "label": "Dashboard"},
    {"path": "/customers", "label": "CRM / Customers"},
    {"path": "/quotations", "label": "Quotations"},
    {"path": "/customer-pos", "label": "Customer PO"},
    {"path": "/purchase-orders", "label": "Purchasing PO"},
    {"path": "/po-recap", "label": "PO Recap"},
    {"path": "/calendar", "label": "Calendar"},
    {"path": "/chat", "label": "Chat"},
    {"path": "/approvals", "label": "Approvals"},
    {"path": "/projects", "label": "Projects"},
    {"path": "/purchasing", "label": "Purchasing / Suppliers"},
    {"path": "/operation", "label": "Operation board"},
    {"path": "/finance", "label": "Finance"},
    {"path": "/finance/payment-verification", "label": "Payment verification"},
    {"path": "/inventory", "label": "Inventory"},
    {"path": "/accounts", "label": "Chart of Accounts"},
    {"path": "/employees", "label": "Employees"},
    {"path": "/salary", "label": "Salary"},
    {"path": "/attendance", "label": "Attendance"},
    {"path": "/sales-targets", "label": "Sales Targets"},
    {"path": "/admin/users", "label": "Users / Admin"},
    {"path": "/kpi", "label": "KPI"},
    {"path": "/reports", "label": "Reports"},
    {"path": "/executive", "label": "Executive"},
    {"path": "/ai", "label": "AI Command"},
    {"path": "/audit", "label": "Audit log"},
    {"path": "/attachments", "label": "All files"},
    {"path": "/role-guide", "label": "Role guide"},
    {"path": "/help", "label": "Help"},
]
_VALID_PAGES = {p["path"] for p in PAGE_CATALOG}
_BASE_ROLES = {"sales", "admin", "hr", "finance", "purchasing", "manager", "director"}


class CustomRoleIn(BaseModel):
    name: str
    base_role: str = "sales"
    pages: list[str] = Field(default_factory=list)
    description: str | None = None


def _out(r: CustomRole) -> dict:
    return {
        "id": str(r.id),
        "name": r.name,
        "base_role": r.base_role,
        "pages": r.pages or [],
        "description": r.description,
        "created_at": r.created_at,
    }


@router.get("/catalog")
async def page_catalog(_u: User = Depends(_director)):
    """The list of pages a custom role can be granted access to."""
    return {"pages": PAGE_CATALOG, "base_roles": sorted(_BASE_ROLES)}


@router.get("")
async def list_custom_roles(
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_director),
):
    rows = (await db.scalars(select(CustomRole).order_by(CustomRole.name.asc()))).all()
    return [_out(r) for r in rows]


def _validate(payload: CustomRoleIn) -> None:
    if not payload.name.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Role name required")
    if payload.base_role not in _BASE_ROLES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"base_role must be one of: {', '.join(sorted(_BASE_ROLES))}",
        )
    bad = [p for p in payload.pages if p not in _VALID_PAGES]
    if bad:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown pages: {bad}")


@router.post("", status_code=201)
async def create_custom_role(
    payload: CustomRoleIn,
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_director),
):
    _validate(payload)
    if await db.scalar(select(CustomRole).where(CustomRole.name == payload.name.strip())):
        raise HTTPException(status.HTTP_409_CONFLICT, "A role with that name already exists")
    r = CustomRole(
        name=payload.name.strip(),
        base_role=payload.base_role,
        pages=payload.pages,
        description=payload.description,
    )
    db.add(r)
    await db.flush()
    return _out(r)


@router.patch("/{role_id}")
async def update_custom_role(
    role_id: UUID,
    payload: CustomRoleIn,
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_director),
):
    _validate(payload)
    r = await db.get(CustomRole, role_id)
    if not r:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Custom role not found")
    clash = await db.scalar(
        select(CustomRole).where(
            CustomRole.name == payload.name.strip(), CustomRole.id != role_id
        )
    )
    if clash:
        raise HTTPException(status.HTTP_409_CONFLICT, "A role with that name already exists")
    r.name = payload.name.strip()
    r.base_role = payload.base_role
    r.pages = payload.pages
    r.description = payload.description
    # Keep base_role of every user on this custom role in sync.
    users = (await db.scalars(select(User).where(User.custom_role_id == role_id))).all()
    for u in users:
        u.role = payload.base_role
    await db.flush()
    return _out(r)


@router.delete("/{role_id}", status_code=204)
async def delete_custom_role(
    role_id: UUID,
    db: AsyncSession = Depends(get_db),
    _u: User = Depends(_director),
):
    r = await db.get(CustomRole, role_id)
    if not r:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Custom role not found")
    # Detach any users on it (they keep their base role).
    users = (await db.scalars(select(User).where(User.custom_role_id == role_id))).all()
    for u in users:
        u.custom_role_id = None
    await db.delete(r)
    return None

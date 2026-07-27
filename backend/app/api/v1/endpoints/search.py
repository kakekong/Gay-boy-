"""Global search — used by the ⌘K command palette."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.permissions import Role, require_min
from app.models.account import Account
from app.models.crm import Customer
from app.models.inventory import InventoryItem
from app.models.operation import Project
from app.models.quotation import Quotation
from app.models.user import User

router = APIRouter(
    # Internal-only surface. External portal accounts (customer /
    # supplier, hierarchy tier 0) must never reach the CRM, pricing,
    # calendar or notification data — they have /portal/* instead.
    dependencies=[Depends(require_min(Role.SALES))]
)


@router.get("")
async def search(
    q: str = Query("", min_length=0, max_length=120),
    limit: int = 8,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    """Return grouped results across the system, scoped to the caller's role."""
    if not q or not q.strip():
        return {"query": q, "groups": []}
    like = f"%{q.strip()}%"
    groups: list[dict] = []

    # Customers (scoped: sales sees own)
    c_stmt = (
        select(Customer)
        .where(Customer.is_deleted.is_(False))
        .where(or_(Customer.company_name.ilike(like), Customer.pic_name.ilike(like)))
        .order_by(Customer.company_name.asc())
        .limit(limit)
    )
    if Role(me.role) == Role.SALES:
        c_stmt = c_stmt.where(Customer.sales_pic_id == me.id)
    customers = (await db.scalars(c_stmt)).all()
    if customers:
        groups.append({
            "label": "Customers",
            "items": [
                {
                    "id": str(c.id),
                    "label": c.company_name,
                    "sublabel": f"{c.industry} · {c.stage}",
                    "link": f"/customers/{c.id}",
                }
                for c in customers
            ],
        })

    # Quotations
    q_stmt = (
        select(Quotation)
        .where(or_(Quotation.number.ilike(like), Quotation.notes.ilike(like)))
        .order_by(Quotation.created_at.desc())
        .limit(limit)
    )
    if Role(me.role) == Role.SALES:
        q_stmt = q_stmt.where(Quotation.sales_pic_id == me.id)
    quotations = (await db.scalars(q_stmt)).all()
    if quotations:
        groups.append({
            "label": "Quotations",
            "items": [
                {
                    "id": str(qt.id),
                    "label": qt.number,
                    "sublabel": f"{qt.status} · {qt.variant}",
                    "link": f"/quotations/{qt.id}",
                }
                for qt in quotations
            ],
        })

    # Projects
    p_stmt = (
        select(Project)
        .where(or_(Project.code.ilike(like), Project.po_number.ilike(like)))
        .order_by(Project.created_at.desc())
        .limit(limit)
    )
    projects = (await db.scalars(p_stmt)).all()
    if projects:
        groups.append({
            "label": "Projects",
            "items": [
                {
                    "id": str(p.id),
                    "label": p.code,
                    "sublabel": f"{p.status}" + (f" · {p.po_number}" if p.po_number else ""),
                    "link": f"/projects",
                }
                for p in projects
            ],
        })

    # Inventory
    i_stmt = (
        select(InventoryItem)
        .where(or_(InventoryItem.sku.ilike(like), InventoryItem.name.ilike(like)))
        .order_by(InventoryItem.name.asc())
        .limit(limit)
    )
    items = (await db.scalars(i_stmt)).all()
    if items:
        groups.append({
            "label": "Inventory",
            "items": [
                {
                    "id": str(it.id),
                    "label": f"{it.sku} · {it.name}",
                    "sublabel": f"{it.current_stock} {it.uom}",
                    "link": "/inventory",
                }
                for it in items
            ],
        })

    # Employees (visible to HR + Director only)
    if Role(me.role) in (Role.HR, Role.DIRECTOR):
        u_stmt = (
            select(User)
            .where(or_(User.full_name.ilike(like), User.email.ilike(like)))
            .where(User.is_active.is_(True))
            .order_by(User.full_name.asc())
            .limit(limit)
        )
        users = (await db.scalars(u_stmt)).all()
        if users:
            groups.append({
                "label": "Employees",
                "items": [
                    {
                        "id": str(u.id),
                        "label": u.full_name,
                        "sublabel": f"{u.role} · {u.email}",
                        "link": f"/employees/{u.id}",
                    }
                    for u in users
                ],
            })

    # Chart of Accounts (visible to admin + director only)
    if Role(me.role) in (Role.ADMIN, Role.DIRECTOR):
        a_stmt = (
            select(Account)
            .where(or_(Account.account_no.ilike(like), Account.name.ilike(like)))
            .order_by(Account.account_no.asc())
            .limit(limit)
        )
        accs = (await db.scalars(a_stmt)).all()
        if accs:
            groups.append({
                "label": "Chart of Accounts",
                "items": [
                    {
                        "id": str(a.id),
                        "label": f"{a.account_no} · {a.name}",
                        "sublabel": a.account_type,
                        "link": "/accounts",
                    }
                    for a in accs
                ],
            })

    return {"query": q, "groups": groups}

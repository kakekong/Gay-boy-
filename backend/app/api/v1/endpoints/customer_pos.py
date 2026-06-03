"""Customer Purchase Orders — the PO the customer sends us.

This is the gate to project creation. A non-director files a customer PO
(usually after a quotation is marked Won), the director approves it from
/approvals, and on approval a Project is spawned with the PO number,
date and value flowing in. Direct director submissions short-circuit and
create the project immediately.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approval import request_approval
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.permissions import Role, require
from app.models.approval import ApprovalRequest, ApprovalStatus
from app.models.crm import Customer
from app.models.customer_po import CustomerPO
from app.models.operation import Project
from app.models.quotation import Quotation
from app.models.user import User
from app.schemas.customer_po import (
    CustomerPOCreate,
    CustomerPOOut,
    CustomerPOPatch,
)

router = APIRouter()

_any_internal = require(
    Role.SALES, Role.PURCHASING, Role.MANAGER, Role.ADMIN, Role.HR, Role.DIRECTOR,
)
_director_only = require(Role.DIRECTOR)


def _items_total(items: list[dict]) -> float:
    return sum(
        float(it.get("qty", 0) or 0) * float(it.get("unit_price", 0) or 0)
        for it in items
    )


async def _enrich(db: AsyncSession, po: CustomerPO) -> dict:
    cust = await db.get(Customer, po.customer_id) if po.customer_id else None
    quote = await db.get(Quotation, po.quotation_id) if po.quotation_id else None
    project = await db.get(Project, po.project_id) if po.project_id else None
    return {
        "id": po.id,
        "customer_id": po.customer_id,
        "customer_name": cust.company_name if cust else None,
        "quotation_id": po.quotation_id,
        "quotation_number": quote.number if quote else None,
        "number": po.number,
        "po_date": po.po_date,
        "items": po.items or [],
        "total": float(po.total or 0),
        "notes": po.notes,
        "status": po.status,
        "project_id": po.project_id,
        "project_code": project.code if project else None,
        "decided_by": po.decided_by,
        "decided_at": po.decided_at,
        "decision_notes": po.decision_notes,
        "created_at": po.created_at,
    }


@router.get("", response_model=list[CustomerPOOut])
async def list_customer_pos(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_any_internal),
    customer_id: UUID | None = None,
    status_eq: str | None = None,
):
    stmt = select(CustomerPO).order_by(CustomerPO.created_at.desc())
    if customer_id:
        stmt = stmt.where(CustomerPO.customer_id == customer_id)
    if status_eq:
        stmt = stmt.where(CustomerPO.status == status_eq)
    # Sales sees only their own customers' POs (matches the rest of the
    # CRM scope rules).
    if Role(user.role) == Role.SALES:
        stmt = stmt.join(
            Customer, Customer.id == CustomerPO.customer_id
        ).where(Customer.sales_pic_id == user.id)
    rows = (await db.scalars(stmt)).all()
    return [await _enrich(db, r) for r in rows]


@router.get("/{po_id}", response_model=CustomerPOOut)
async def get_customer_po(
    po_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_any_internal),
):
    po = await db.get(CustomerPO, po_id)
    if not po:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer PO not found")
    if Role(user.role) == Role.SALES:
        cust = await db.get(Customer, po.customer_id)
        if not cust or cust.sales_pic_id != user.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your customer")
    return await _enrich(db, po)


@router.post("", response_model=CustomerPOOut, status_code=201)
async def create_customer_po(
    payload: CustomerPOCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_any_internal),
):
    """File a customer PO. Director-only is the goal here long-term, but
    sales / manager / purchasing / admin can submit because they're the
    ones who handle incoming customer paperwork. Either way the PO must
    be approved by the director before it spawns a project."""
    customer = await db.get(Customer, payload.customer_id)
    if not customer:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown customer")
    # Sales is scoped to their own customers.
    if Role(user.role) == Role.SALES and customer.sales_pic_id != user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Sales can only file POs for their own customers",
        )
    quotation = await db.get(Quotation, payload.quotation_id)
    if not quotation or quotation.customer_id != payload.customer_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Quotation does not belong to this customer",
        )
    if quotation.status != "won":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Quotation status is '{quotation.status}', "
            "but only Won quotations can have a customer PO submitted.",
        )
    if not payload.number.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "PO number required")

    # Uniqueness scoped to the customer — two different customers using
    # the same PO number "001" is fine, but the same customer can't have
    # two POs sharing a number.
    clash = await db.scalar(
        select(CustomerPO).where(
            CustomerPO.customer_id == payload.customer_id,
            CustomerPO.number == payload.number.strip(),
        )
    )
    if clash:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Customer PO '{payload.number}' already exists for this customer",
        )

    items = [it.model_dump() for it in payload.items]
    total = _items_total(items)
    is_director = Role(user.role) == Role.DIRECTOR

    po = CustomerPO(
        number=payload.number.strip(),
        po_date=payload.po_date,
        customer_id=payload.customer_id,
        quotation_id=payload.quotation_id,
        items=items,
        total=total,
        notes=payload.notes,
        status="approved" if is_director else "pending_approval",
        created_by=user.id, updated_by=user.id,
    )
    db.add(po)
    await db.flush()

    if is_director:
        # Director submission applies immediately — create the project now.
        po.decided_by = user.id
        from datetime import UTC, datetime as _dt
        po.decided_at = _dt.now(UTC)
        project = await _spawn_project(db, po, user)
        po.project_id = project.id
        await db.flush()
    else:
        await request_approval(
            db,
            target_type="customer_po",
            target_id=po.id,
            requested_by=user.id,
            required_role=Role.DIRECTOR,
            reason=f"Customer PO {po.number} from {customer.company_name}",
            payload={"action": "create"},
        )

    return await _enrich(db, po)


@router.patch("/{po_id}", response_model=CustomerPOOut)
async def update_customer_po(
    po_id: UUID,
    payload: CustomerPOPatch,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_any_internal),
):
    """Edit a customer PO that's still pending approval. Once it's
    approved (and a project spawned) the PO is frozen — edit the project
    instead."""
    po = await db.get(CustomerPO, po_id)
    if not po:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer PO not found")
    if Role(user.role) == Role.SALES:
        cust = await db.get(Customer, po.customer_id)
        if not cust or cust.sales_pic_id != user.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your customer")
    if po.status != "pending_approval" and Role(user.role) != Role.DIRECTOR:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Customer PO is no longer pending — edit the project it spawned instead.",
        )

    data = payload.model_dump(exclude_unset=True)
    if "number" in data:
        new_num = (data["number"] or "").strip()
        if not new_num:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "PO number required")
        if new_num != po.number:
            clash = await db.scalar(
                select(CustomerPO).where(
                    CustomerPO.customer_id == po.customer_id,
                    CustomerPO.number == new_num,
                    CustomerPO.id != po_id,
                )
            )
            if clash:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"Customer PO '{new_num}' already exists for this customer",
                )
            po.number = new_num
    if "po_date" in data:
        po.po_date = data["po_date"]
    if "items" in data and data["items"] is not None:
        po.items = data["items"]
        po.total = _items_total(po.items)
    if "notes" in data:
        po.notes = data["notes"]
    po.updated_by = user.id
    await db.flush()
    return await _enrich(db, po)


async def _spawn_project(
    db: AsyncSession, po: CustomerPO, user: User
) -> Project:
    """Create a Project from an approved customer PO. Mirrors the old
    project_factory.create_project_from_quotation but reads the PO number
    / date / value off the customer PO instead of generating placeholders
    from the quotation. Quotation linkage is preserved when present."""
    from datetime import datetime
    from sqlalchemy import func
    from app.ai.orchestrator import emit
    from app.models.operation import WorkOrder

    year = datetime.utcnow().year
    prefix = f"PRJ-{year}-"
    seq = await db.scalar(
        select(func.count(Project.id)).where(Project.code.like(f"{prefix}%"))
    ) or 0
    project = Project(
        code=f"{prefix}{seq + 1:04d}",
        customer_id=po.customer_id,
        quotation_id=po.quotation_id,
        po_number=po.number,
        po_date=po.po_date,
        po_value=po.total,
        status="new",
        created_by=user.id, updated_by=user.id,
    )
    db.add(project)
    await db.flush()
    db.add(WorkOrder(
        project_id=project.id,
        code=f"WO-{project.code}-01",
        stage="receiving",
    ))
    await emit(db, "customer_po.approved", {
        "customer_po_id": str(po.id),
        "project_id": str(project.id),
    })
    return project

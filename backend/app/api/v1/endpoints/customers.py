from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approval import evaluate_data_change, request_approval
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.permissions import Role, can_view_customer, filter_to_role_scope
from app.models.crm import Customer
from app.models.user import User
from app.schemas.common import Page
from app.schemas.customer import CustomerCreate, CustomerOut, CustomerUpdate

router = APIRouter()


@router.get("", response_model=Page[CustomerOut])
async def list_customers(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    q: str | None = None,
    stage: str | None = None,
    industry: str | None = None,
):
    base = select(Customer).where(Customer.is_deleted.is_(False))
    base = filter_to_role_scope(user, base, Customer.sales_pic_id)
    if q:
        base = base.where(Customer.company_name.ilike(f"%{q}%"))
    if stage:
        base = base.where(Customer.stage == stage)
    if industry:
        base = base.where(Customer.industry == industry)

    total = await db.scalar(
        select(func.count()).select_from(base.subquery())
    ) or 0
    rows = (await db.scalars(
        base.order_by(Customer.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )).all()
    return Page(data=[CustomerOut.model_validate(r) for r in rows],
                page=page, page_size=page_size, total=total)


@router.post("", response_model=CustomerOut, status_code=201)
async def create_customer(
    payload: CustomerCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if Role(user.role) == Role.SALES:
        sales_pic = user.id
    else:
        sales_pic = payload.sales_pic_id
    obj = Customer(
        **payload.model_dump(exclude={"sales_pic_id"}),
        sales_pic_id=sales_pic,
        created_by=user.id, updated_by=user.id,
    )
    db.add(obj)
    await db.flush()
    return obj


@router.get("/{customer_id}", response_model=CustomerOut)
async def get_customer(customer_id: UUID,
                       db: AsyncSession = Depends(get_db),
                       user: User = Depends(get_current_user)):
    obj = await db.get(Customer, customer_id)
    if not obj or obj.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if not can_view_customer(user, obj.sales_pic_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Out of scope")
    return obj


@router.patch("/{customer_id}", response_model=CustomerOut)
async def update_customer(
    customer_id: UUID,
    payload: CustomerUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    obj = await db.get(Customer, customer_id)
    if not obj or obj.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if Role(user.role) == Role.SALES and obj.sales_pic_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sales can only edit own customers")

    rule = evaluate_data_change(Role(user.role))
    changes = payload.model_dump(exclude_unset=True)

    if rule.required_role is None:
        for k, v in changes.items():
            setattr(obj, k, v)
        obj.updated_by = user.id
        return obj

    # admin role -> needs manager approval; record request, do not mutate
    await request_approval(
        db,
        target_type="customer",
        target_id=obj.id,
        requested_by=user.id,
        required_role=rule.required_role,
        reason=rule.reason,
        payload={"changes": changes},
    )
    raise HTTPException(status.HTTP_202_ACCEPTED, "Change requested; awaiting approval")

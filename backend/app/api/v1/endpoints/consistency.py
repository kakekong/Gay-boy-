"""Do the documents of one deal agree? — see `services/order_consistency.py`.

`GET` from whichever document the caller is on (price request, quotation,
customer PO or project); `POST /fix` applies one check's fix in one direction,
under that document's own edit rules.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.permissions import Role
from app.models.crm import Customer
from app.models.user import User
from app.services import order_consistency as oc

router = APIRouter()

_ROLES = (Role.SALES, Role.PURCHASING, Role.ADMIN, Role.FINANCE, Role.MANAGER, Role.DIRECTOR)


class Where(BaseModel):
    price_request_id: UUID | None = None
    quotation_id: UUID | None = None
    customer_po_id: UUID | None = None
    project_id: UUID | None = None


async def _chain(db: AsyncSession, user: User, where: Where) -> dict:
    if Role(user.role) not in _ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not available for your role")
    if not any(where.model_dump().values()):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Say which document")
    chain = await oc.resolve_chain(db, **where.model_dump())
    # Sales see a deal when the customer is theirs or the paperwork names them
    # — the same rule as opening any one of its documents.
    if Role(user.role) == Role.SALES:
        docs = [chain["price_request"], chain["quotation"], *chain["customer_pos"]]
        docs = [x for x in docs if x is not None]
        cust_id = next((x.customer_id for x in docs if getattr(x, "customer_id", None)), None)
        cust = await db.get(Customer, cust_id) if cust_id else None
        named = any(getattr(x, "sales_pic_id", None) == user.id for x in docs)
        if not (named or (cust and cust.sales_pic_id == user.id)):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Out of scope")
    return chain


@router.get("")
async def check(
    price_request_id: UUID | None = None, quotation_id: UUID | None = None,
    customer_po_id: UUID | None = None, project_id: UUID | None = None,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    where = Where(price_request_id=price_request_id, quotation_id=quotation_id,
                  customer_po_id=customer_po_id, project_id=project_id)
    return await oc.report(db, await _chain(db, user, where), user)


class FixIn(Where):
    check: str
    action: str


@router.post("/fix")
async def fix(payload: FixIn, db: AsyncSession = Depends(get_db),
              user: User = Depends(get_current_user)):
    where = Where(**payload.model_dump(include=set(Where.model_fields)))
    chain = await _chain(db, user, where)
    try:
        res = await oc.fix(db, chain, user, payload.check, payload.action)
    except oc.FixRefused as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    await db.flush()
    # Re-read: the fix may have moved more than the one pair it was asked about.
    # The quotation's new lines are added to the session, not appended to the
    # loaded collection, so it has to be read again explicitly.
    if chain["price_request"] is not None:
        await db.refresh(chain["price_request"])
    if chain["quotation"] is not None:
        await db.refresh(chain["quotation"], ["items"])
        await db.refresh(chain["quotation"])
    for c in chain["customer_pos"]:
        await db.refresh(c)
    after = await oc.report(db, await oc.resolve_chain(db, **where.model_dump()), user)
    return {**res, "report": after}

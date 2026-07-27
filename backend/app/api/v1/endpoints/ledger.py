"""Recent ledger activity.

The app keeps a single-entry ledger: posting a won quotation bumps the
linked Chart-of-Accounts balances and records the movements as a snapshot
on the quotation (see app/services/ledger.py). This endpoint flattens those
snapshots from the most recently posted quotations into a readable feed of
ledger entries. Finance + director only.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.permissions import Role, require, require_min
from app.models.crm import Customer
from app.models.quotation import Quotation
from app.models.user import User

router = APIRouter(
    # Internal-only surface. External portal accounts (customer /
    # supplier, hierarchy tier 0) must never reach the CRM, pricing,
    # calendar or notification data — they have /portal/* instead.
    dependencies=[Depends(require_min(Role.SALES))]
)


@router.get("/recent")
async def recent_ledger(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require(Role.FINANCE, Role.DIRECTOR)),
):
    """Flatten the latest posted-quotation snapshots into ledger entries,
    newest first. Each entry is one account movement."""
    limit = max(1, min(limit, 200))
    quotes = (await db.scalars(
        select(Quotation)
        .where(Quotation.is_posted.is_(True))
        .order_by(Quotation.posted_at.desc())
        .limit(limit)
    )).all()

    cust_ids = {q.customer_id for q in quotes if q.customer_id}
    customers: dict = {}
    if cust_ids:
        crows = (await db.scalars(
            select(Customer).where(Customer.id.in_(cust_ids))
        )).all()
        customers = {c.id: c for c in crows}

    entries = []
    for q in quotes:
        snap = q.posted_snapshot or {}
        cust = customers.get(q.customer_id) if q.customer_id else None
        for m in snap.get("movements", []):
            entries.append({
                "posted_at": q.posted_at,
                "quotation_id": str(q.id),
                "quotation_number": q.number,
                "customer_name": cust.company_name if cust else None,
                "account_no": m.get("account_no"),
                "account_name": m.get("name"),
                "role": m.get("role"),
                "amount": float(m.get("delta") or 0),
                "balance_after": (
                    float(m["new_balance"])
                    if m.get("new_balance") is not None else None
                ),
            })

    return {"entries": entries, "count": len(entries)}

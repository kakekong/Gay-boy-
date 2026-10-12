"""Every sidebar badge in one request.

The app shell used to keep eight queries polling on every page — unread chat
every 15 seconds, and mentions, pending invoices, payment claims, approvals,
waiting documents, claimable commission and the DP queue every 30 — for every
person with the app on screen. On a serverless database that bills for each
hour it is awake and only sleeps after five quiet minutes, that is a database
that never sleeps while anyone has a tab open.

This answers all of them at once, from the same handlers the full pages use
(so a badge can never disagree with the list it opens), behind one sign-in
check and one transaction. The shell asks once a minute, and not at all once
the person has stepped away (`frontend/src/lib/activity.ts`).
"""
import logging

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.permissions import Role, require_min
from app.models.user import User

# Staff only — portal (customer/supplier) logins never reach this.
router = APIRouter(dependencies=[Depends(require_min(Role.SALES))])
log = logging.getLogger(__name__)

_MONEY_QUEUES = (Role.FINANCE, Role.MANAGER, Role.DIRECTOR)
_APPROVERS = (Role.MANAGER, Role.DIRECTOR, Role.FINANCE)
_COMMISSION = (Role.SALES, Role.MANAGER, Role.DIRECTOR)
_DP_QUEUE = (Role.FINANCE, Role.DIRECTOR)


@router.get("/badges")
async def badges(db: AsyncSession = Depends(get_db), me: User = Depends(get_current_user)):
    role = Role(me.role)
    out: dict[str, int | None] = {}

    async def one(key: str, fn):
        # Each in its own savepoint: one queue failing must not blank the rest
        # of the sidebar, nor leave the transaction unusable for them.
        try:
            async with db.begin_nested():
                out[key] = int(await fn() or 0)
        except Exception as e:                       # pragma: no cover
            log.warning("nav badge %s failed: %s", key, e)
            out[key] = None

    from app.api.v1.endpoints.chat import unread_total
    from app.api.v1.endpoints.comments import my_mentions

    async def chat():
        r = await unread_total(db=db, me=me)
        return (r or {}).get("unread", 0)

    async def mentions():
        return len(await my_mentions(unread_only=True, db=db, me=me) or [])

    await one("chat_unread", chat)
    await one("mentions_unread", mentions)

    if role in _MONEY_QUEUES:
        from app.api.v1.endpoints.finance import list_pending_invoices
        from app.models.payment_claim import PaymentClaim

        async def invoices():
            return len(await list_pending_invoices(db=db, _user=me) or [])

        async def claims():
            return await db.scalar(select(func.count()).select_from(PaymentClaim)
                                   .where(PaymentClaim.status == "pending"))
        await one("pending_invoices", invoices)
        await one("pending_claims", claims)

    if role in _APPROVERS:
        from app.api.v1.endpoints.approvals import inbox, pending_documents

        async def approvals():
            return len(await inbox(db=db, user=me) or [])

        async def documents():
            return len(await pending_documents(db=db, user=me) or [])
        await one("pending_approvals", approvals)
        await one("pending_documents", documents)

    if role in _COMMISSION:
        from app.api.v1.endpoints.commissions import commission_summary

        async def commission():
            r = await commission_summary(db=db, me=me, user_id=None, year=None)
            return ((r or {}).get("totals") or {}).get("claimable_jobs", 0)
        await one("commission_claimable", commission)

    if role in _DP_QUEUE:
        from app.models.customer_po import CustomerPO

        async def dp():
            return await db.scalar(select(func.count()).select_from(CustomerPO)
                                   .where(CustomerPO.status == "pending_finance"))
        await one("pending_dp", dp)

    return out

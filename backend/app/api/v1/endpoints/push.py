"""Web Push subscription management.

The browser registers a service worker, subscribes with our VAPID public
key, and POSTs the subscription here. From then on the background sweeper
(app/services/webpush.py) delivers the user's role-routed notifications to
the device even when no tab is open.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.push import PushSubscription
from app.models.user import User
from app.services.webpush import get_or_create_vapid, push_to_user_detailed

router = APIRouter()


class SubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class SubscribeIn(BaseModel):
    endpoint: str
    keys: SubscriptionKeys


class UnsubscribeIn(BaseModel):
    endpoint: str


@router.get("/vapid-public-key")
async def vapid_public_key(
    db: AsyncSession = Depends(get_db),
    _me: User = Depends(get_current_user),
):
    kp = await get_or_create_vapid(db)
    return {"key": kp.public_key}


@router.post("/subscribe", status_code=201)
async def subscribe(
    payload: SubscribeIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    if not payload.endpoint.startswith("https://"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid endpoint")
    existing = await db.scalar(
        select(PushSubscription).where(PushSubscription.endpoint == payload.endpoint)
    )
    if existing:
        # Same browser re-subscribing (possibly after a re-login as someone
        # else on a shared machine) — reassign to the current user.
        existing.user_id = me.id
        existing.p256dh = payload.keys.p256dh
        existing.auth = payload.keys.auth
    else:
        db.add(PushSubscription(
            user_id=me.id,
            endpoint=payload.endpoint,
            p256dh=payload.keys.p256dh,
            auth=payload.keys.auth,
            user_agent=(request.headers.get("user-agent") or "")[:255],
        ))
    await db.flush()
    return {"ok": True}


@router.post("/unsubscribe")
async def unsubscribe(
    payload: UnsubscribeIn,
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    await db.execute(delete(PushSubscription).where(
        PushSubscription.endpoint == payload.endpoint,
        PushSubscription.user_id == me.id,
    ))
    return {"ok": True}


@router.post("/test")
async def send_test(
    db: AsyncSession = Depends(get_db),
    me: User = Depends(get_current_user),
):
    """Fire a test push to the caller's own devices so they can confirm
    the whole chain works with the tab closed."""
    results = await push_to_user_detailed(
        db, me.id,
        title="Transmisi Eng",
        body="Push notifications are working on this device. 🎉",
        url="/",
    )
    if not results:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "No push subscription for this account yet — enable notifications first.",
        )
    sent = sum(1 for r in results if r["ok"])
    if not sent:
        # Every device rejected the push — tell the user why instead of
        # pretending it worked.
        first_error = next((r["detail"] for r in results if r["detail"]), "unknown error")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Push service rejected the notification: {first_error}",
        )
    return {"sent": sent, "devices": len(results), "results": results}

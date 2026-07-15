"""Web Push sending + the background notification sweeper.

The bell (`GET /notifications`) already computes role-routed items per
user at request time. To reach devices with NO tab open, a background
task re-runs that aggregation for every internal user on an interval and
web-pushes any item not yet delivered to that user (dedup via
PushDelivered). One notification item → at most one push per user, ever.

VAPID keys are generated once and persisted in the DB, so there is zero
manual key setup and pushes keep verifying across restarts/rebuilds.
"""

import asyncio
import base64
import json
import logging

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.push import PushDelivered, PushSubscription, VapidKeypair
from app.models.user import User

log = logging.getLogger(__name__)

VAPID_SUBJECT = "mailto:admin@transmisisuplindo.com"

# Only nag devices about things worth waking a phone for.
_PUSH_SEVERITIES = {"high", "medium"}
# Advisory lock key so only ONE worker/process runs the sweeper.
_SWEEP_LOCK_KEY = 774_421_001


async def get_or_create_vapid(db: AsyncSession) -> VapidKeypair:
    kp = await db.scalar(select(VapidKeypair).limit(1))
    if kp:
        return kp
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    private = ec.generate_private_key(ec.SECP256R1())
    private_pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    pub_raw = private.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    public_b64 = base64.urlsafe_b64encode(pub_raw).decode().rstrip("=")
    kp = VapidKeypair(private_pem=private_pem, public_key=public_b64)
    db.add(kp)
    await db.flush()
    return kp


def _send_one(sub: PushSubscription, payload: dict, private_pem: str) -> dict:
    """Send one push (sync — called via to_thread).

    Returns {"ok": bool, "dead": bool, "detail": str|None} so callers can
    tell a real delivery from a swallowed failure — the test endpoint
    surfaces `detail` to the user instead of silently claiming success.
    """
    try:
        from py_vapid import Vapid
        from pywebpush import webpush

        # pywebpush treats a plain string as base64 raw/DER — handing it
        # our PEM makes it fail with "Could not deserialize key data".
        # Parse the PEM ourselves and pass a Vapid instance.
        vapid = Vapid.from_pem(private_pem.encode())
        webpush(
            subscription_info={
                "endpoint": sub.endpoint,
                "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
            },
            data=json.dumps(payload),
            vapid_private_key=vapid,
            vapid_claims={"sub": VAPID_SUBJECT},
            ttl=3600,
        )
        return {"ok": True, "dead": False, "detail": None}
    except Exception as e:
        code = getattr(getattr(e, "response", None), "status_code", None)
        body = getattr(getattr(e, "response", None), "text", "") or str(e)
        log.warning("webpush failed (%s): %s", code, body[:300])
        return {
            "ok": False,
            "dead": code in (404, 410),  # endpoint gone — unsubscribe it
            "detail": f"HTTP {code}: {body[:200]}" if code else str(e)[:200],
        }


async def push_to_user(db: AsyncSession, user_id, title: str, body: str,
                       url: str = "/") -> int:
    """Push to every device of one user. Returns how many sends SUCCEEDED."""
    results = await push_to_user_detailed(db, user_id, title, body, url)
    return sum(1 for r in results if r["ok"])


async def push_to_user_detailed(db: AsyncSession, user_id, title: str,
                                body: str, url: str = "/") -> list[dict]:
    """Push to every device of one user; return per-device delivery results.

    Dead subscriptions (push service says 404/410) are removed. Each result
    is {"ok": bool, "detail": str|None} — `detail` carries the push
    service's rejection so /push/test can show the user WHY nothing arrived.
    """
    subs = (await db.scalars(
        select(PushSubscription).where(PushSubscription.user_id == user_id)
    )).all()
    if not subs:
        return []
    kp = await get_or_create_vapid(db)
    payload = {"title": title, "body": body, "url": url}
    results: list[dict] = []
    for sub in subs:
        res = await asyncio.to_thread(_send_one, sub, payload, kp.private_pem)
        if res["dead"]:
            await db.delete(sub)
        results.append({"ok": res["ok"], "detail": res["detail"]})
    await db.flush()
    return results


async def sweep_once(db: AsyncSession) -> int:
    """Compute fresh notifications per subscribed user and push the new ones.

    Reuses the bell's aggregator so role routing / scoping / severity are
    identical to what the user sees in-app. Pushes only high/medium items
    that haven't been delivered to that user before.
    """
    from app.api.v1.endpoints.notifications import list_notifications

    user_ids = [row[0] for row in (await db.execute(
        select(PushSubscription.user_id).distinct()
    )).all()]
    if not user_ids:
        return 0

    total = 0
    for uid in user_ids:
        user = await db.get(User, uid)
        if not user or not user.is_active:
            continue
        try:
            data = await list_notifications(db=db, me=user)
        except Exception as e:
            log.warning("sweep: aggregator failed for %s: %s", uid, e)
            continue
        items = [i for i in data.get("items", [])
                 if i.get("severity") in _PUSH_SEVERITIES]
        if not items:
            continue
        seen = {row[0] for row in (await db.execute(
            select(PushDelivered.item_id).where(PushDelivered.user_id == uid)
        )).all()}
        fresh = [i for i in items if i["id"] not in seen][:5]  # cap per sweep
        for item in fresh:
            db.add(PushDelivered(user_id=uid, item_id=item["id"]))
            await db.flush()
            total += await push_to_user(
                db, uid, title=item["title"], body=item.get("body") or "",
                url=item.get("link") or "/",
            )
    return total


async def sweeper_loop(interval: int = 90) -> None:
    """Background task: run sweep_once forever, one runner per deployment.

    A Postgres advisory lock makes this safe under multiple workers — only
    the first process to grab the lock sweeps; the rest idle.
    """
    from app.core.db import SessionLocal

    await asyncio.sleep(15)  # let boot finish first
    while True:
        try:
            async with SessionLocal() as db:
                got = (await db.execute(
                    text("SELECT pg_try_advisory_lock(:k)"), {"k": _SWEEP_LOCK_KEY}
                )).scalar()
                if got:
                    try:
                        n = await sweep_once(db)
                        await db.commit()
                        if n:
                            log.info("webpush sweep: %s push(es) sent", n)
                        # prune delivery + dismissal ledgers so they don't
                        # grow forever
                        from app.models.push import NotificationDismissed
                        await db.execute(delete(PushDelivered).where(
                            text("sent_at < now() - interval '30 days'")
                        ))
                        await db.execute(delete(NotificationDismissed).where(
                            text("created_at < now() - interval '30 days'")
                        ))
                        await db.commit()
                    finally:
                        await db.execute(
                            text("SELECT pg_advisory_unlock(:k)"),
                            {"k": _SWEEP_LOCK_KEY},
                        )
        except Exception as e:
            log.warning("webpush sweeper iteration failed: %s", e)
        await asyncio.sleep(interval)

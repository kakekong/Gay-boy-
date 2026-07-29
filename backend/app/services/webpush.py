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


# Hold strong references to in-flight fire-and-forget pushes. asyncio keeps
# only a weak reference to tasks, so without this a push suspended at an await
# can be GC'd mid-flight ("Task was destroyed but it is pending").
_bg_tasks: set = set()


def fire_and_forget(coro) -> None:
    """Schedule a background coroutine that outlives the request, keeping a
    reference until it finishes so the event loop can't drop it."""
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


async def get_or_create_vapid(db: AsyncSession) -> VapidKeypair:
    # Always read the OLDEST row deterministically: even if a race ever left
    # two keypairs, every caller (public-key endpoint + signing sweeper) then
    # agrees on the same one, so the served public key can't mismatch the
    # private key we sign with.
    kp = await db.scalar(
        select(VapidKeypair).order_by(VapidKeypair.created_at.asc()).limit(1)
    )
    if kp:
        return kp
    # Serialize first-time creation across concurrent callers/workers so two
    # of them can't each insert a keypair. A transaction-scoped advisory lock
    # is released automatically on commit/rollback.
    await db.execute(text("SELECT pg_advisory_xact_lock(429173001)"))
    kp = await db.scalar(
        select(VapidKeypair).order_by(VapidKeypair.created_at.asc()).limit(1)
    )
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


async def notify_chat_message(channel_id, sender_id, sender_name: str,
                              channel_name: str | None, text: str) -> None:
    """Instant chat push — fire-and-forget from the send-message endpoint.

    Unlike the 90s sweeper, messages push immediately to every OTHER
    member of the channel who has device notifications on. One tag per
    channel so a burst of messages collapses into one notification per
    conversation instead of stacking.
    """
    from app.core.db import SessionLocal
    from app.models.chat import ChatChannelMember

    try:
        async with SessionLocal() as db:
            member_ids = [row[0] for row in (await db.execute(
                select(ChatChannelMember.user_id).where(
                    ChatChannelMember.channel_id == channel_id,
                    ChatChannelMember.user_id != sender_id,
                )
            )).all()]
            if not member_ids:
                return
            title = (f"{sender_name} · {channel_name}"
                     if channel_name else sender_name)
            body = text if len(text) <= 140 else text[:137] + "…"
            payload = {"title": title, "body": body, "url": "/chat",
                       "tag": f"chat:{channel_id}"}
            kp = await get_or_create_vapid(db)
            for uid in member_ids:
                subs = (await db.scalars(
                    select(PushSubscription).where(PushSubscription.user_id == uid)
                )).all()
                for sub in subs:
                    res = await asyncio.to_thread(
                        _send_one, sub, payload, kp.private_pem)
                    if res["dead"]:
                        await db.delete(sub)
            await db.commit()
    except Exception as e:
        log.warning("chat push failed for channel %s: %s", channel_id, e)


_DISCUSSION_LINKS = {
    "price_request": "/price-requests?open={id}",
    "quotation": "/quotations/{id}",
    "customer_po": "/customer-pos/{id}",
    "supplier_po": "/purchase-orders",
    "project": "/projects/{id}",
    "invoice": "/finance",
}


async def notify_discussion_comment(owner_type: str, owner_id, sender_id,
                                    sender_name: str, text: str,
                                    mentioned_ids: list | None = None) -> None:
    """Instant push for entity discussion threads. Fire-and-forget from the
    comment endpoint.

    Recipients = everyone who commented on the thread before + the entity's
    natural stakeholders (requester / coster / approver) + anyone @-mentioned,
    minus the sender — so the FIRST comment already reaches the right people,
    not just repliers.

    Mentions are included whether or not the person can open the document:
    reaching someone outside the page is the entire point of mentioning them,
    and their access to the thread was granted at the same moment. They get a
    distinct title so being named reads differently from thread noise.
    """
    from app.core.db import SessionLocal
    from app.models.comment import EntityComment

    try:
        async with SessionLocal() as db:
            recipients: set = set()
            for row in (await db.execute(
                select(EntityComment.author_id).distinct().where(
                    EntityComment.owner_type == owner_type,
                    EntityComment.owner_id == owner_id,
                    EntityComment.author_id.is_not(None),
                )
            )).all():
                recipients.add(row[0])

            number = None
            if owner_type == "price_request":
                from app.models.price_request import PriceRequest
                pr = await db.get(PriceRequest, owner_id)
                if pr:
                    number = pr.number
                    for uid in (pr.created_by, pr.sales_pic_id,
                                pr.priced_by, pr.approved_by):
                        if uid:
                            recipients.add(uid)
            elif owner_type == "quotation":
                from app.models.quotation import Quotation
                q = await db.get(Quotation, owner_id)
                if q:
                    number = q.number
                    for uid in (q.created_by, q.sales_pic_id):
                        if uid:
                            recipients.add(uid)
            elif owner_type == "customer_po":
                from app.models.customer_po import CustomerPO
                po = await db.get(CustomerPO, owner_id)
                if po:
                    number = po.number
                    if po.created_by:
                        recipients.add(po.created_by)

            if owner_type == "project":
                from app.models.operation import Project
                proj = await db.get(Project, owner_id)
                if proj:
                    number = proj.code
            elif owner_type == "invoice":
                from app.models.finance import Invoice
                inv = await db.get(Invoice, owner_id)
                if inv:
                    number = inv.number

            named = {uid for uid in (mentioned_ids or [])}
            recipients |= named
            recipients.discard(sender_id)
            named.discard(sender_id)
            if not recipients:
                return

            link = _DISCUSSION_LINKS.get(owner_type, "/")
            doc = number or owner_type.replace("_", " ")
            body = text if len(text) <= 140 else text[:137] + "…"
            kp = await get_or_create_vapid(db)
            for uid in recipients:
                was_named = uid in named
                payload = {
                    # Being named is the one that should pull someone out of
                    # whatever they were doing, so say so in the title.
                    "title": (f"{sender_name} mentioned you · {doc}" if was_named
                              else f"{sender_name} · {doc}"),
                    "body": body,
                    # Someone mentioned into a document they cannot open must
                    # not be deep-linked to a page that will 403 at them.
                    "url": (link.format(id=owner_id) if not was_named
                            else "/mentions"),
                    "tag": f"disc:{owner_type}:{owner_id}",
                }
                subs = (await db.scalars(
                    select(PushSubscription).where(PushSubscription.user_id == uid)
                )).all()
                for sub in subs:
                    res = await asyncio.to_thread(
                        _send_one, sub, payload, kp.private_pem)
                    if res["dead"]:
                        await db.delete(sub)
            await db.commit()
    except Exception as e:
        log.warning("discussion push failed (%s %s): %s", owner_type, owner_id, e)


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

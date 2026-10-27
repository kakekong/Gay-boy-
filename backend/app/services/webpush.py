"""Web Push sending + the background notification sweeper.

The bell (`GET /notifications`) already computes role-routed items per
user at request time. To reach devices with NO tab open, a background
task re-runs that aggregation for every internal user on an interval and
web-pushes any item not yet delivered to that user (dedup via
PushDelivered). One notification item → at most one push per user, ever —
and only while it is recent (PUSH_MAX_AGE_DAYS).

VAPID keys are generated once and persisted in the DB, so there is zero
manual key setup and pushes keep verifying across restarts/rebuilds.
"""

import asyncio
import base64
import json
import logging
import time

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.push import PushDelivered, PushSubscription, VapidKeypair
from app.models.user import User

log = logging.getLogger(__name__)

VAPID_SUBJECT = "mailto:admin@transmisisuplindo.com"

# Only nag devices about things worth waking a phone for.
_PUSH_SEVERITIES = {"high", "medium"}

# A phone hears about what has just happened. Something that has been open
# for longer — an approval from months ago — is recorded as delivered without
# a push: the bell still lists it, but a device subscribing today, or a
# ledger reset, doesn't wake it with the whole backlog five at a time.
PUSH_MAX_AGE_DAYS = 3

# The delivery and dismissal ledgers keep one row per notification per user,
# for as long as the notification can still appear. Only notifications that
# are new each day by design — the unread-chat count, attendance, the daily
# roll-up — are cleared once old. Clearing the rest after 30 days is what
# brought months-old approvals back into the director's bell and onto their
# phone every month.
_EPHEMERAL_PREFIXES = ("chat-unread:", "attendance-missing:", "attendance-late:", "team-rollup:")
# Advisory lock key so only ONE worker/process runs the sweeper.
_SWEEP_LOCK_KEY = 774_421_001
# How often the 30-day ledgers get swept, in seconds.
_PRUNE_EVERY = 86_400


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
        new = [i for i in items if i["id"] not in seen]
        old = [i for i in new if _older_than(i.get("at"), PUSH_MAX_AGE_DAYS)]
        for item in old:
            db.add(PushDelivered(user_id=uid, item_id=item["id"]))
        if old:
            await db.flush()
        fresh = [i for i in new if i not in old][:5]  # cap per sweep
        for item in fresh:
            db.add(PushDelivered(user_id=uid, item_id=item["id"]))
            await db.flush()
            total += await push_to_user(
                db, uid, title=item["title"], body=item.get("body") or "",
                url=item.get("link") or "/",
            )
    return total


def _older_than(at, days: int) -> bool:
    """Whether a notification's time is more than `days` ago. No time: not."""
    from datetime import UTC, date, datetime, timedelta
    if at is None:
        return False
    if isinstance(at, str):
        try:
            at = datetime.fromisoformat(at)
        except ValueError:
            return False
    if isinstance(at, datetime):
        if at.tzinfo is None:
            at = at.replace(tzinfo=UTC)
        return at < datetime.now(UTC) - timedelta(days=days)
    if isinstance(at, date):
        return at < date.today() - timedelta(days=days)
    return False


async def prune_ledgers(db: AsyncSession) -> None:
    """Clear old rows of the new-each-day notifications only; everything
    else stays delivered and dismissed for as long as it can still show."""
    from app.models.push import NotificationDismissed
    await db.execute(delete(PushDelivered).where(
        text("sent_at < now() - interval '30 days'"),
        ephemeral_clause(PushDelivered.item_id),
    ))
    await db.execute(delete(NotificationDismissed).where(
        text("created_at < now() - interval '30 days'"),
        ephemeral_clause(NotificationDismissed.item_id),
    ))


def ephemeral_clause(column):
    """SQL: the item id is one of the new-each-day notifications."""
    from sqlalchemy import or_
    return or_(*[column.like(p + "%") for p in _EPHEMERAL_PREFIXES])


def seconds_until_active(now=None) -> float:
    """0 inside the sweeper's working window, else how long until it opens.

    Read from WEBPUSH_ACTIVE_HOURS / WEBPUSH_ACTIVE_DAYS in the office's time
    zone. Computed without any database access — the whole point is that the
    database is left alone outside the window.
    """
    from datetime import datetime, time as dtime, timedelta
    from zoneinfo import ZoneInfo
    from app.core.config import settings

    spec = (settings.WEBPUSH_ACTIVE_HOURS or "").strip()
    days_spec = (settings.WEBPUSH_ACTIVE_DAYS or "").strip()
    if not spec and not days_spec:
        return 0.0
    tz = ZoneInfo(settings.TIMEZONE or "Asia/Jakarta")
    now = (now or datetime.now(tz)).astimezone(tz)
    try:
        a, b = (spec or "00:00-24:00").split("-")
        start = dtime.fromisoformat(a.strip())
        end_s = b.strip()
        end = dtime.max if end_s in ("24:00", "24:00:00") else dtime.fromisoformat(end_s)
        days = ({int(x) for x in days_spec.split(",") if x.strip()}
                if days_spec else set(range(7)))
    except (ValueError, TypeError):
        log.warning("WEBPUSH_ACTIVE_HOURS/DAYS unreadable (%r / %r) — sweeping always",
                    spec, days_spec)
        return 0.0
    if not days:
        return 0.0
    if now.weekday() in days and start <= now.time() < end:
        return 0.0
    # Next opening: today if we're before it on a working day, else the next
    # working day's start.
    for add in range(0, 8):
        d = (now + timedelta(days=add)).date()
        if d.weekday() not in days:
            continue
        opening = datetime.combine(d, start, tzinfo=tz)
        if opening > now:
            return (opening - now).total_seconds()
    return 3600.0


async def sweeper_loop(interval: int | None = None,
                       idle_interval: int | None = None) -> None:
    """Background task: run sweep_once forever, one runner per deployment.

    A Postgres advisory lock makes this safe under multiple workers — only
    the first process to grab the lock sweeps; the rest idle.

    The cadence is a database bill, not just a latency knob. Every tick opens
    a session and queries, and a serverless Postgres keeps its compute awake
    for some minutes after each one — so the old 90-second timer meant the
    database never suspended and was charged around the clock, on an app used
    during office hours by a handful of people. It emptied a month's compute
    allowance by itself and locked everyone out of the login screen.

    So: a slow default cadence, a much slower one when nobody is subscribed
    (nothing to deliver — don't even run the aggregator), pruning once a day
    rather than every tick, and an off switch. Pushes raised inline by an
    event are untouched by any of this.
    """
    from app.core.config import settings
    from app.core.db import SessionLocal

    interval = settings.WEBPUSH_SWEEP_SECONDS if interval is None else interval
    idle_interval = (settings.WEBPUSH_IDLE_SECONDS
                     if idle_interval is None else idle_interval)
    if interval <= 0:
        log.info("web-push sweeper disabled (WEBPUSH_SWEEP_SECONDS=0)")
        return
    # Backing off to something *shorter* than the working cadence would be a
    # misconfiguration that costs money silently.
    idle_interval = max(idle_interval, interval)

    await asyncio.sleep(15)  # let boot finish first
    # None = "not pruned in this process yet". Counting from zero instead
    # would tie the first prune to how long the machine had been up, so on a
    # container that restarts daily the ledgers would never be swept at all.
    last_prune: float | None = None
    while True:
        nap = interval
        closed = seconds_until_active()
        if closed > 0:
            # Outside the working window: sleep without touching the
            # database. Capped at an hour so a changed setting or clock is
            # picked up without a restart.
            await asyncio.sleep(min(closed, 3600))
            continue
        try:
            async with SessionLocal() as db:
                got = (await db.execute(
                    text("SELECT pg_try_advisory_lock(:k)"), {"k": _SWEEP_LOCK_KEY}
                )).scalar()
                if got:
                    try:
                        subscribed = await db.scalar(
                            select(func.count()).select_from(PushSubscription)
                        ) or 0
                        if not subscribed:
                            # No device is listening. The aggregator would run
                            # every role's notification query to deliver to
                            # nobody, so skip it and come back much later.
                            nap = idle_interval
                        else:
                            n = await sweep_once(db)
                            await db.commit()
                            if n:
                                log.info("webpush sweep: %s push(es) sent", n)
                        # Prune the delivery + dismissal ledgers so they don't
                        # grow forever. Daily is plenty for rows that expire
                        # after 30 days, and it kept three writes on every
                        # single tick.
                        now = time.monotonic()
                        if last_prune is None or now - last_prune >= _PRUNE_EVERY:
                            await prune_ledgers(db)
                            await db.commit()
                            last_prune = now
                    finally:
                        await db.execute(
                            text("SELECT pg_advisory_unlock(:k)"),
                            {"k": _SWEEP_LOCK_KEY},
                        )
        except Exception as e:
            log.warning("webpush sweeper iteration failed: %s", e)
        await asyncio.sleep(nap)

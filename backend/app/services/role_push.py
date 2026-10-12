"""Push a phone notification to everyone in a role, the moment it happens.

The background sweeper turns bell items into phone notifications, but only
every 15 minutes and only in working hours, so a new price request could sit
unannounced for a quarter of an hour, or overnight. For the hand-offs that
start somebody's work, that is too slow. This sends the push as the event
happens, and records it under the bell item's own id so the sweeper does not
send the same thing again later.
"""
import asyncio
import logging

from sqlalchemy import select

log = logging.getLogger(__name__)


def after_commit(db, make_coro) -> None:
    """Run `make_coro()` (a push) once this session's transaction commits.

    A push sent before the commit could announce something that then rolls
    back — a project that never existed. Sent after, it can't.
    """
    from sqlalchemy import event

    from app.services.webpush import fire_and_forget

    def _fire(_session):
        try:
            fire_and_forget(make_coro())
        except Exception as e:                    # no running loop, etc.
            log.warning("after-commit push not scheduled: %s", e)

    event.listen(db.sync_session, "after_commit", _fire, once=True)


async def push_to_role(role: str, *, title: str, body: str, url: str,
                       item_id: str, tag: str | None = None,
                       exclude_user_id=None) -> None:
    """Fire-and-forget: every active `role` user with notifications on —
    except `exclude_user_id`, the person who caused it (they know)."""
    from app.core.db import SessionLocal
    from app.models.push import PushDelivered, PushSubscription
    from app.models.user import User
    from app.services.webpush import _send_one, get_or_create_vapid

    try:
        async with SessionLocal() as db:
            uids = [r[0] for r in (await db.execute(
                select(User.id).where(User.role == role, User.is_active.is_(True))
            )).all() if r[0] != exclude_user_id]
            if not uids:
                return
            subs = (await db.scalars(
                select(PushSubscription).where(PushSubscription.user_id.in_(uids))
            )).all()
            if not subs:
                return
            kp = await get_or_create_vapid(db)
            payload = {"title": title, "body": body, "url": url, "tag": tag or item_id}
            for sub in subs:
                res = await asyncio.to_thread(_send_one, sub, payload, kp.private_pem)
                if res["dead"]:
                    await db.delete(sub)
            already = {r[0] for r in (await db.execute(
                select(PushDelivered.user_id).where(PushDelivered.item_id == item_id)
            )).all()}
            for uid in {s.user_id for s in subs} - already:
                db.add(PushDelivered(user_id=uid, item_id=item_id))
            await db.commit()
    except Exception as e:                                    # never break the caller
        log.warning("role push to %s failed (%s): %s", role, item_id, e)

"""System log — the director's view of who has been in the system.

Three reads, director only:

* ``/people``   — every account with its last sign-in, last seen, and a
  30-day count of sign-ins, failed attempts and changes made.
* ``/sign-ins`` — the sign-in history across everyone (see
  `models/login_event.py`), filterable, paged with a total.
* ``/timeline`` — one person's history: their sign-ins, every change request
  they made (the action log) with the audit log's before/after attached where
  there is one, newest first.

Read-only. Nothing here can be edited or deleted from the app — a log that
the people in it can tidy up is not a log.
"""
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.permissions import Role, require
from app.models.audit import AuditLog
from app.models.login_event import ActionLog, LoginEvent
from app.models.user import User
from app.services.attendance_pay import tz

router = APIRouter(dependencies=[Depends(require(Role.DIRECTOR))])

EVENTS = ("login", "failed", "blocked", "logout", "view_as")


def _day_start(d: date) -> datetime:
    """Midnight in the office's time zone — the day the director means."""
    return datetime.combine(d, time.min, tzinfo=tz()).astimezone(UTC)


def _event_row(e: LoginEvent, users: dict) -> dict:
    u = users.get(e.user_id)
    a = users.get(e.actor_id)
    return {
        "id": str(e.id),
        "event": e.event,
        "reason": e.reason,
        "user_id": str(e.user_id) if e.user_id else None,
        "user_name": u.full_name if u else None,
        "user_role": u.role if u else None,
        "email": e.email,
        "actor_id": str(e.actor_id) if e.actor_id else None,
        "actor_name": a.full_name if a else None,
        "ip": e.ip,
        "device": e.device,
        "user_agent": e.user_agent,
        "occurred_at": e.occurred_at,
    }


async def _users_by_id(db: AsyncSession, ids) -> dict:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return {u.id: u for u in (await db.scalars(select(User).where(User.id.in_(ids)))).all()}


@router.get("/people")
async def people(db: AsyncSession = Depends(get_db)):
    since = datetime.now(UTC) - timedelta(days=30)
    users = (await db.scalars(select(User).order_by(User.full_name))).all()

    counts: dict = {}
    for uid, ev, n in (await db.execute(
        select(LoginEvent.user_id, LoginEvent.event, func.count())
        .where(LoginEvent.occurred_at >= since, LoginEvent.user_id.is_not(None))
        .group_by(LoginEvent.user_id, LoginEvent.event)
    )).all():
        counts.setdefault(uid, {})[ev] = n

    # The latest sign-in and the latest failure per person, one row each.
    def latest(event: str):
        ranked = (select(LoginEvent, func.row_number().over(
            partition_by=LoginEvent.user_id,
            order_by=LoginEvent.occurred_at.desc()).label("rn"))
            .where(LoginEvent.event == event, LoginEvent.user_id.is_not(None))
            .subquery())
        return select(LoginEvent).join(ranked, and_(LoginEvent.id == ranked.c.id,
                                                    ranked.c.rn == 1))
    last_login = {e.user_id: e for e in (await db.scalars(latest("login"))).all()}
    last_fail = {e.user_id: e for e in (await db.scalars(latest("failed"))).all()}

    # Changes they made themselves — not the director's, in a "View as".
    actions = dict((await db.execute(
        select(ActionLog.user_id, func.count())
        .where(ActionLog.occurred_at >= since, ActionLog.user_id.is_not(None),
               ActionLog.via_id.is_(None), ActionLog.status_code < 400)
        .group_by(ActionLog.user_id)
    )).all())

    out = []
    for u in users:
        ll, lf, c = last_login.get(u.id), last_fail.get(u.id), counts.get(u.id, {})
        out.append({
            "id": str(u.id), "full_name": u.full_name, "email": u.email,
            "role": u.role, "is_active": u.is_active,
            "last_login_at": ll.occurred_at if ll else None,
            "last_login_ip": ll.ip if ll else None,
            "last_login_device": ll.device if ll else None,
            # A session lives for days on its refresh token, so the last
            # sign-in can be a week old for someone who used it an hour ago.
            "last_seen_at": u.last_seen_at,
            "last_failed_at": lf.occurred_at if lf else None,
            "logins_30d": c.get("login", 0),
            "failed_30d": c.get("failed", 0) + c.get("blocked", 0),
            "actions_30d": actions.get(u.id, 0),
        })
    # Most recently active first; never-seen accounts at the bottom.
    def key(r):
        t = max([x for x in (r["last_seen_at"], r["last_login_at"]) if x] or [None],
                key=lambda x: x or datetime.min.replace(tzinfo=UTC))
        return (t is None, -(t.timestamp() if t else 0))
    out.sort(key=key)
    return out


@router.get("/sign-ins")
async def sign_ins(
    db: AsyncSession = Depends(get_db),
    user_id: UUID | None = None,
    event: str | None = None,
    q: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=10000),
):
    conds = []
    if user_id:
        conds.append(LoginEvent.user_id == user_id)
    if event:
        conds.append(LoginEvent.event == event)
    if date_from:
        conds.append(LoginEvent.occurred_at >= _day_start(date_from))
    if date_to:
        conds.append(LoginEvent.occurred_at < _day_start(date_to + timedelta(days=1)))
    if q and q.strip():
        like = f"%{q.strip().lower()}%"
        matching = select(User.id).where(or_(func.lower(User.full_name).like(like),
                                             func.lower(User.email).like(like)))
        conds.append(or_(LoginEvent.email.like(like), LoginEvent.ip.like(like),
                         func.lower(LoginEvent.device).like(like),
                         LoginEvent.user_id.in_(matching)))
    total = await db.scalar(select(func.count()).select_from(LoginEvent).where(*conds))
    rows = (await db.scalars(
        select(LoginEvent).where(*conds)
        .order_by(LoginEvent.occurred_at.desc(), LoginEvent.id)
        .offset(offset).limit(limit)
    )).all()
    users = await _users_by_id(db, [r.user_id for r in rows] + [r.actor_id for r in rows])
    return {"total": total or 0, "items": [_event_row(r, users) for r in rows]}


@router.get("/timeline")
async def timeline(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=2000),
):
    """One person, everything, newest first: their sign-ins, every change
    request they made, and — attached to the request that caused it — the
    audit log's before/after where an endpoint writes one.

    Audit rows from before the action log existed have no request to sit
    under and are listed on their own.
    """
    take = offset + limit
    ev_where = or_(LoginEvent.user_id == user_id, LoginEvent.actor_id == user_id)
    act_where = or_(ActionLog.user_id == user_id, ActionLog.via_id == user_id)
    ev = (await db.scalars(select(LoginEvent).where(ev_where)
                           .order_by(LoginEvent.occurred_at.desc()).limit(take))).all()
    acts = (await db.scalars(select(ActionLog).where(act_where)
                             .order_by(ActionLog.occurred_at.desc()).limit(take))).all()
    first_action = await db.scalar(select(func.min(ActionLog.occurred_at)).where(
        ActionLog.user_id == user_id))
    legacy_where = [AuditLog.actor_id == user_id]
    if first_action is not None:
        legacy_where.append(AuditLog.occurred_at < first_action)
    legacy = (await db.scalars(select(AuditLog).where(*legacy_where)
                               .order_by(AuditLog.occurred_at.desc()).limit(take))).all()

    # The audit rows written inside the requests on this page. An audit row is
    # stamped at the start of its transaction and the action when the response
    # is sent, so each attaches to the first action at or after it.
    attached: dict = {}
    if acts:
        lo = min(a.occurred_at for a in acts) - timedelta(seconds=60)
        hi = max(a.occurred_at for a in acts)
        inner = (await db.scalars(select(AuditLog).where(
            AuditLog.actor_id == user_id, AuditLog.occurred_at >= lo,
            AuditLog.occurred_at <= hi,
        ).order_by(AuditLog.occurred_at))).all()
        ordered = sorted(acts, key=lambda a: a.occurred_at)
        for au in inner:
            host = next((a for a in ordered if a.occurred_at >= au.occurred_at
                         and (a.occurred_at - au.occurred_at).total_seconds() <= 60), None)
            if host is not None:
                attached.setdefault(host.id, []).append(au)

    total = sum([
        await db.scalar(select(func.count()).select_from(LoginEvent).where(ev_where)) or 0,
        await db.scalar(select(func.count()).select_from(ActionLog).where(act_where)) or 0,
        await db.scalar(select(func.count()).select_from(AuditLog).where(*legacy_where)) or 0,
    ])
    users = await _users_by_id(db, [user_id] + [e.user_id for e in ev] + [e.actor_id for e in ev]
                               + [a.user_id for a in acts] + [a.via_id for a in acts])

    def change(a: AuditLog) -> dict:
        return {"id": str(a.id), "action": a.action, "entity": a.entity,
                "entity_id": str(a.entity_id) if a.entity_id else None,
                "before": a.before, "after": a.after, "occurred_at": a.occurred_at}

    merged = [{"kind": "sign_in", **_event_row(e, users)} for e in ev]
    for a in acts:
        u, v = users.get(a.user_id), users.get(a.via_id)
        merged.append({
            "kind": "action", "id": str(a.id), "method": a.method, "path": a.path,
            "status_code": a.status_code, "ip": a.ip, "occurred_at": a.occurred_at,
            "user_id": str(a.user_id) if a.user_id else None,
            "user_name": u.full_name if u else None,
            "via_id": str(a.via_id) if a.via_id else None,
            "via_name": v.full_name if v else None,
            "changes": [change(x) for x in attached.get(a.id, [])],
        })
    merged += [{"kind": "change", **change(a)} for a in legacy]
    merged.sort(key=lambda r: r["occurred_at"], reverse=True)
    return {"total": total, "items": merged[offset:offset + limit]}


@router.get("/actions")
async def actions(
    db: AsyncSession = Depends(get_db),
    user_id: UUID | None = None,
    q: str | None = None,
    failed: bool = False,
    date_from: date | None = None,
    date_to: date | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=10000),
):
    """Everyone's change requests, newest first. `q` matches the person or
    the path ("customers", "quotations/…"); `failed` keeps only the refused."""
    conds = []
    if user_id:
        conds.append(or_(ActionLog.user_id == user_id, ActionLog.via_id == user_id))
    if failed:
        conds.append(ActionLog.status_code >= 400)
    if date_from:
        conds.append(ActionLog.occurred_at >= _day_start(date_from))
    if date_to:
        conds.append(ActionLog.occurred_at < _day_start(date_to + timedelta(days=1)))
    if q and q.strip():
        like = f"%{q.strip().lower()}%"
        matching = select(User.id).where(or_(func.lower(User.full_name).like(like),
                                             func.lower(User.email).like(like)))
        conds.append(or_(func.lower(ActionLog.path).like(like),
                         ActionLog.user_id.in_(matching)))
    total = await db.scalar(select(func.count()).select_from(ActionLog).where(*conds))
    rows = (await db.scalars(
        select(ActionLog).where(*conds)
        .order_by(ActionLog.occurred_at.desc(), ActionLog.id)
        .offset(offset).limit(limit))).all()
    users = await _users_by_id(db, [r.user_id for r in rows] + [r.via_id for r in rows])
    out = []
    for a in rows:
        u, v = users.get(a.user_id), users.get(a.via_id)
        out.append({
            "id": str(a.id), "method": a.method, "path": a.path,
            "status_code": a.status_code, "ip": a.ip, "occurred_at": a.occurred_at,
            "user_id": str(a.user_id) if a.user_id else None,
            "user_name": u.full_name if u else None, "user_role": u.role if u else None,
            "via_id": str(a.via_id) if a.via_id else None,
            "via_name": v.full_name if v else None,
        })
    return {"total": total or 0, "items": out}

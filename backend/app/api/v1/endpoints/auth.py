import time
from collections import defaultdict, deque
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record as audit_record
from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.permissions import Role, require
from app.core.security import (
    decode_token,
    make_access_token,
    make_refresh_token,
    verify_password,
)
from app.models.user import User
from app.schemas.auth import LoginRequest, TokenPair, UserOut
from app.services.login_log import record_login_event

router = APIRouter()


# Per-IP rolling-window rate limit for failed logins (in-memory; one-process
# deployments only — for multi-worker setups put this behind nginx/Caddy).
_LOGIN_FAILS: dict[str, deque] = defaultdict(deque)
_LOGIN_WINDOW_SEC = 60
_LOGIN_MAX_FAILS = 5


def _check_login_rate(ip: str) -> None:
    now = time.time()
    q = _LOGIN_FAILS[ip]
    while q and now - q[0] > _LOGIN_WINDOW_SEC:
        q.popleft()
    if len(q) >= _LOGIN_MAX_FAILS:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Too many failed logins. Try again in {_LOGIN_WINDOW_SEC} seconds.",
        )


def _record_login_fail(ip: str) -> None:
    _LOGIN_FAILS[ip].append(time.time())


def _clear_login_fails(ip: str) -> None:
    _LOGIN_FAILS.pop(ip, None)


@router.post("/login", response_model=TokenPair)
async def login(
    payload: LoginRequest, request: Request, db: AsyncSession = Depends(get_db),
):
    # Prefer the leftmost X-Forwarded-For entry when behind a proxy (Caddy etc.)
    xff = request.headers.get("x-forwarded-for") or ""
    ip = xff.split(",")[0].strip() or (request.client.host if request.client else "anon")
    email = payload.email.lower()
    try:
        _check_login_rate(ip)
    except HTTPException:
        known = await db.scalar(select(User.id).where(User.email == email))
        await record_login_event(request, event="blocked", user_id=known,
                                 email=email, reason="too_many_attempts")
        raise
    user = await db.scalar(select(User).where(User.email == email))
    password_ok = bool(user) and verify_password(payload.password, user.password_hash)
    if not user or not user.is_active or not password_ok:
        _record_login_fail(ip)
        # Which of the three it was goes in the director's log only; the
        # caller gets the same "Invalid credentials" either way, so the
        # endpoint still doesn't say which addresses exist.
        reason = ("unknown_email" if not user
                  else "wrong_password" if not password_ok
                  else "deactivated")
        await record_login_event(request, event="failed", user_id=user.id if user else None,
                                 email=email, reason=reason)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    _clear_login_fails(ip)
    await record_login_event(request, event="login", user_id=user.id, email=email)
    return TokenPair(
        access_token=make_access_token(user.id, user.role),
        refresh_token=make_refresh_token(user.id),
    )


class RefreshIn(BaseModel):
    token: str | None = None


@router.post("/refresh", response_model=TokenPair)
async def refresh(
    body: RefreshIn | None = Body(None),
    token: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Trade a refresh token for a fresh pair.

    The token is taken from the body, or from the query string, which is where
    it used to live and where it must keep working: the frontend and this
    service deploy separately, so an endpoint that accepted only the new shape
    would sign everybody out for the length of one deployment gap. The query
    string is the worse home for a credential — it ends up in every proxy and
    CDN access log on the way here — so the body wins when both arrive, and
    the query copy is what gets dropped later.
    """
    raw = (body.token if body else None) or token
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "No refresh token supplied")
    try:
        payload = decode_token(raw)
    except Exception as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from exc
    if payload.get("type") != "refresh":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong token type")
    user = await db.scalar(select(User).where(User.id == payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User unavailable")
    via = payload.get("via")      # a "View as" session stays one when renewed
    return TokenPair(
        access_token=make_access_token(user.id, user.role, via=via),
        refresh_token=make_refresh_token(user.id, via=via),
    )


@router.post("/logout", status_code=204)
async def logout(request: Request, user: User = Depends(get_current_user)):
    """Record a deliberate sign-out. Tokens are stateless, so the client
    dropping them is what actually ends the session; this only puts the exit
    on the history."""
    await record_login_event(request, event="logout", user_id=user.id, email=user.email)
    return None


@router.get("/me", response_model=UserOut)
async def me(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    out = UserOut.model_validate(user)
    if user.custom_role_id:
        from app.models.custom_role import CustomRole
        cr = await db.get(CustomRole, user.custom_role_id)
        if cr:
            out.custom_role_name = cr.name
            out.custom_role_pages = cr.pages or []
    # A per-user page override (when set) wins over the custom-role pages —
    # the sidebar gates on custom_role_pages, so funnel the effective set here.
    if user.pages:
        out.custom_role_pages = user.pages
    return out


@router.post("/impersonate/{user_id}", response_model=TokenPair)
async def impersonate(
    user_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    director: User = Depends(require(Role.DIRECTOR)),
):
    """Director-only "View as": mint a token pair for another user so the
    director can see the app exactly as that user does (data scope + sidebar).
    The frontend stashes the director's own session and restores it on exit —
    there's no time gate, it's manual enter/exit. Audit-logged."""
    if user_id == director.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Already signed in as yourself")
    target = await db.scalar(
        select(User).where(User.id == user_id, User.is_active.is_(True))
    )
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found or inactive")
    await audit_record(
        db, actor=director, action="impersonate", entity="user",
        entity_id=target.id,
        after={"as_email": target.email, "as_role": target.role},
    )
    await record_login_event(request, event="view_as", user_id=target.id,
                             email=target.email, actor_id=director.id)
    return TokenPair(
        access_token=make_access_token(target.id, target.role, via=director.id),
        refresh_token=make_refresh_token(target.id, via=director.id),
    )

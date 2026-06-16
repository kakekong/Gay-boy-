import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.security import (
    decode_token,
    make_access_token,
    make_refresh_token,
    verify_password,
)
from app.models.user import User
from app.schemas.auth import LoginRequest, TokenPair, UserOut

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
    _check_login_rate(ip)
    user = await db.scalar(select(User).where(User.email == payload.email.lower()))
    if not user or not user.is_active or not verify_password(payload.password, user.password_hash):
        _record_login_fail(ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    _clear_login_fails(ip)
    return TokenPair(
        access_token=make_access_token(user.id, user.role),
        refresh_token=make_refresh_token(user.id),
    )


@router.post("/refresh", response_model=TokenPair)
async def refresh(token: str, db: AsyncSession = Depends(get_db)):
    try:
        payload = decode_token(token)
    except Exception as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from exc
    if payload.get("type") != "refresh":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong token type")
    user = await db.scalar(select(User).where(User.id == payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User unavailable")
    return TokenPair(
        access_token=make_access_token(user.id, user.role),
        refresh_token=make_refresh_token(user.id),
    )


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
    return out

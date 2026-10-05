"""Writing the sign-in history and the "last seen" stamp.

Both are written in a session of their own. A failed sign-in ends in a 401,
and the request's own session rolls back on that — which is exactly the event
that must not be lost. And neither may ever break the request it rides on:
every write here swallows its own errors.
"""
import time
from uuid import UUID

from fastapi import Request
from loguru import logger
from sqlalchemy import text

from app.core.db import SessionLocal
from app.models.login_event import LoginEvent


def client_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    xff = request.headers.get("x-forwarded-for") or ""
    return (xff.split(",")[0].strip()
            or (request.client.host if request.client else None))


def device_of(ua: str | None) -> str | None:
    """'Mozilla/5.0 (iPhone; …) … Safari/604.1' → 'Safari · iPhone'.

    Rough on purpose: enough to tell "her phone" from "the office PC" at a
    glance. The full string is kept beside it for anything finer.
    """
    if not ua:
        return None
    u = ua.lower()
    if "iphone" in u:
        os_ = "iPhone"
    elif "ipad" in u:
        os_ = "iPad"
    elif "android" in u:
        os_ = "Android"
    elif "windows" in u:
        os_ = "Windows"
    elif "mac os x" in u or "macintosh" in u:
        os_ = "Mac"
    elif "linux" in u:
        os_ = "Linux"
    else:
        os_ = None
    if "edg/" in u:
        br = "Edge"
    elif "opr/" in u or "opera" in u:
        br = "Opera"
    elif "firefox/" in u or "fxios/" in u:
        br = "Firefox"
    elif "chrome/" in u or "crios/" in u:
        br = "Chrome"
    elif "safari/" in u:
        br = "Safari"
    elif "python" in u or "httpx" in u or "curl" in u:
        br = "Script"
    else:
        br = None
    return " · ".join(x for x in (br, os_) if x) or None


async def record_login_event(
    request: Request | None, *, event: str, user_id: UUID | None = None,
    email: str | None = None, reason: str | None = None,
    actor_id: UUID | None = None,
) -> None:
    ua = request.headers.get("user-agent") if request is not None else None
    try:
        async with SessionLocal() as s:
            s.add(LoginEvent(
                user_id=user_id, email=(email or "").strip().lower()[:255] or None,
                event=event, reason=reason, actor_id=actor_id,
                ip=(client_ip(request) or "")[:64] or None,
                user_agent=(ua or "")[:400] or None, device=device_of(ua),
            ))
            await s.commit()
    except Exception as exc:     # the log must never cost anyone their sign-in
        logger.warning(f"login event not recorded: {exc}")


# ── last seen ────────────────────────────────────────────────────────────────
# In-process throttle: one write per account per few minutes, not one per
# request. Per worker, which is fine — the worst case is a write a little
# more often than the interval.
_SEEN_EVERY_SEC = 300
_last_write: dict[UUID, float] = {}


async def touch_last_seen(user_id: UUID) -> None:
    now = time.monotonic()
    if now - _last_write.get(user_id, -1e9) < _SEEN_EVERY_SEC:
        return
    _last_write[user_id] = now
    try:
        async with SessionLocal() as s:
            await s.execute(text("UPDATE users SET last_seen_at = now() WHERE id = :id"),
                            {"id": user_id})
            await s.commit()
    except Exception as exc:
        logger.warning(f"last_seen not recorded: {exc}")


# ── every change request ─────────────────────────────────────────────────────
# Pure ASGI rather than BaseHTTPMiddleware: it must not buffer responses
# (file downloads stream) and must see the final status code.

_LOGGED_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
# Already on the sign-in history, or not an action anybody took: renewing a
# token happens on its own every few minutes.
_SKIP_PATHS = ("/api/v1/auth/login", "/api/v1/auth/refresh", "/api/v1/auth/logout",
               "/api/v1/auth/impersonate")


class ActionLogMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (scope.get("type") != "http" or scope.get("method") not in _LOGGED_METHODS
                or not scope.get("path", "").startswith("/api/v1/")
                or scope["path"].startswith(_SKIP_PATHS)):
            return await self.app(scope, receive, send)

        status_code = {"v": 500}

        async def send_wrapper(message):
            if message.get("type") == "http.response.start":
                status_code["v"] = message.get("status", 500)
            await send(message)

        started = time.monotonic()
        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            await _write_action(scope, status_code["v"],
                                int((time.monotonic() - started) * 1000))


async def _write_action(scope, status_code: int, duration_ms: int) -> None:
    from app.core.security import decode_token
    from app.models.login_event import ActionLog
    try:
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers") or []}
        auth = headers.get("authorization") or ""
        if not auth.lower().startswith("bearer "):
            return                       # nobody signed in — nothing to attribute
        try:
            claims = decode_token(auth.split(None, 1)[1])
        except Exception:
            return
        if claims.get("type") != "access":
            return
        xff = headers.get("x-forwarded-for") or ""
        client = scope.get("client")
        ip = xff.split(",")[0].strip() or (client[0] if client else None)
        async with SessionLocal() as s:
            s.add(ActionLog(
                user_id=UUID(claims["sub"]),
                via_id=UUID(claims["via"]) if claims.get("via") else None,
                method=scope["method"], path=scope["path"][:300],
                status_code=status_code, duration_ms=duration_ms,
                ip=(ip or "")[:64] or None,
            ))
            await s.commit()
    except Exception as exc:
        logger.warning(f"action not recorded: {exc}")

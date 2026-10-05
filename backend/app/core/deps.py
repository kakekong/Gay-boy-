from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.security import decode_token
from app.models.user import User


async def get_current_user(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    token = authorization.split(None, 1)[1]
    try:
        payload = decode_token(token)
    except Exception as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from exc
    if payload.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong token type")
    user_id = UUID(payload["sub"])
    user = await db.scalar(select(User).where(User.id == user_id, User.is_active.is_(True)))
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    # "Last seen" for the director's system log — throttled, and in its own
    # session so it never touches this request's transaction.
    # Not while the director is viewing as them — that isn't them.
    if not payload.get("via"):
        from app.services.login_log import touch_last_seen
        await touch_last_seen(user.id)
    return user

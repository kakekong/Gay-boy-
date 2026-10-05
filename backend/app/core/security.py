from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.core.config import settings

_hasher = PasswordHasher()


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, plain)
    except VerifyMismatchError:
        return False


def _encode(payload: dict, ttl: timedelta) -> str:
    now = datetime.now(UTC)
    to_encode = {**payload, "iat": now, "exp": now + ttl}
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def make_access_token(user_id: UUID, role: str, via: UUID | str | None = None) -> str:
    """`via` marks a "View as" session: the director's id, carried so the
    system log can say the director did it rather than the person viewed."""
    payload = {"sub": str(user_id), "role": role, "type": "access"}
    if via:
        payload["via"] = str(via)
    return _encode(payload, timedelta(minutes=settings.JWT_ACCESS_TTL_MIN))


def make_refresh_token(user_id: UUID, via: UUID | str | None = None) -> str:
    payload = {"sub": str(user_id), "type": "refresh"}
    if via:
        payload["via"] = str(via)
    return _encode(payload, timedelta(days=settings.JWT_REFRESH_TTL_DAYS))


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])

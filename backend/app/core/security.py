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


def make_access_token(user_id: UUID, role: str) -> str:
    return _encode({"sub": str(user_id), "role": role, "type": "access"},
                   timedelta(minutes=settings.JWT_ACCESS_TTL_MIN))


def make_refresh_token(user_id: UUID) -> str:
    return _encode({"sub": str(user_id), "type": "refresh"},
                   timedelta(days=settings.JWT_REFRESH_TTL_DAYS))


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])

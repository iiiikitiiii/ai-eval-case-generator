"""Password hashing and JWT issuance/verification.

Kept deliberately small: one hashing scheme (bcrypt), one token type (a
short-lived bearer JWT carrying user id + role). No refresh tokens yet —
add them if 12h sessions prove too short in practice, not preemptively.
"""
from datetime import datetime, timedelta, timezone
from uuid import UUID

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

settings = get_settings()
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


def create_access_token(user_id: UUID, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


class TokenPayload:
    def __init__(self, user_id: UUID, role: str):
        self.user_id = user_id
        self.role = role


def decode_access_token(token: str) -> TokenPayload | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
    sub = payload.get("sub")
    role = payload.get("role")
    if not sub or not role:
        return None
    return TokenPayload(user_id=UUID(sub), role=role)

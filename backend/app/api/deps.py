"""Shared FastAPI dependencies: DB session, current user, role gate, arq pool."""
from collections.abc import Callable

from arq.connections import ArqRedis
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.models.user import User
from app.db.session import get_db

_bearer = HTTPBearer(auto_error=False)


def get_arq_pool(request: Request) -> ArqRedis:
    """The pool created once at app startup (see app.main.lifespan) —
    reused across requests, never opened per-call."""
    return request.app.state.arq_pool


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未登录")
    payload = decode_access_token(creds.credentials)
    if payload is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "登录已失效，请重新登录")
    user = db.get(User, payload.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "账号不存在或已停用")
    return user


def require_role(*roles: str) -> Callable[[User], User]:
    """Usage: `Depends(require_role("engineer", "admin"))`."""

    def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles and user.role != "admin":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "没有权限执行此操作")
        return user

    return _check

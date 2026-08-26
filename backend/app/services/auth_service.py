from sqlalchemy.orm import Session

from app.core.security import create_access_token, verify_password
from app.db.models.user import User


def authenticate(db: Session, email: str, password: str) -> User | None:
    user = db.query(User).filter(User.email == email, User.is_active.is_(True)).first()
    if user is None or not verify_password(password, user.password_hash):
        return None
    return user


def issue_token(user: User) -> str:
    return create_access_token(user_id=user.id, role=user.role)

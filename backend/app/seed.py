"""One-off bootstrap: create the first admin account so someone can log in.

Run after migrations are applied:
    python -m app.seed --email you@hospital.example --name "你的名字" --password "change-me"
"""
import argparse

from app.core.security import hash_password
from app.db.models.user import User, UserRole
from app.db.session import SessionLocal


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--role", default=UserRole.admin.value, choices=[r.value for r in UserRole])
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if db.query(User).filter(User.email == args.email).first():
            print(f"用户 {args.email} 已存在，跳过。")
            return
        user = User(
            name=args.name,
            email=args.email,
            password_hash=hash_password(args.password),
            role=args.role,
        )
        db.add(user)
        db.commit()
        print(f"已创建 {args.role} 账号：{args.email}")
    finally:
        db.close()


if __name__ == "__main__":
    main()

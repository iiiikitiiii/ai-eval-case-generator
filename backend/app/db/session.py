"""Sync SQLAlchemy engine/session.

Sync, not async: at ~100s of cases and a handful of concurrent reviewers,
an async DB layer buys nothing but doubles the surface area (async
Alembic env, async session plumbing everywhere). FastAPI endpoints stay
`async def` where useful; blocking DB calls run in FastAPI's threadpool.
Revisit only if profiling actually shows the DB as the bottleneck.
"""
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

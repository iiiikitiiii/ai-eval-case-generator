"""Shared fixtures for the DB-backed test suite.

`db_session` wraps each test in an outer transaction against the real
(dev) Postgres from .env and rolls it back afterward — the standard
SQLAlchemy "join a session into an external transaction" pattern. Tests
call service functions that do their own `db.commit()`; because those
commits land on a SAVEPOINT (not the outer transaction), the final
rollback still discards everything the test wrote. Needs a live Postgres
reachable via DATABASE_URL — same requirement as running the app itself.

Uses `join_transaction_mode="create_savepoint"` (SQLAlchemy 2.0.30+),
not the older manual "begin_nested() + after_transaction_end listener"
recipe — verified empirically that the manual recipe's SAVEPOINT bookkeeping
gets corrupted by an explicit `session.rollback()` from application code
(objects created earlier in the test become unrefreshable/"deleted" even
though they were already committed to an enclosing SAVEPOINT). This matters
here specifically because `pipeline.common.finish_failed()` calls
`db.rollback()` on every agent failure — exactly the code path the
阶段 0 regression tests exist to exercise.
"""
import uuid

import pytest

from app.db.models.user import User
from app.db.session import SessionLocal, engine


@pytest.fixture()
def db_session():
    connection = engine.connect()
    outer_tx = connection.begin()
    session = SessionLocal(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        outer_tx.rollback()
        connection.close()


@pytest.fixture()
def anyio_backend():
    """Lets `@pytest.mark.anyio` async tests run on asyncio — needed for the
    agent-runner regression tests (阶段 0 of Agent统一架构改造方案.md),
    which call `async def run_agent_x()`. No extra pytest-asyncio dependency:
    `anyio`'s own pytest plugin auto-registers and just needs this fixture."""
    return "asyncio"


@pytest.fixture()
def actor(db_session):
    """一个用完即弃的测试用户，用作各种 write_audit(actor=...) 的调用方。"""
    user = User(
        id=uuid.uuid4(),
        name="测试执行人",
        email=f"audit-test-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x",
        role="engineer",
    )
    db_session.add(user)
    db_session.flush()
    return user

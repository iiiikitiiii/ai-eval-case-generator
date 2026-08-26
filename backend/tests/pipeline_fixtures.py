"""Shared helpers for agent regression tests (阶段 0 of
doc/Agent统一架构改造方案.md — "先补测试护栏"). Not a test module itself
(no test_ prefix, pytest won't collect it).

Every agent runner needs: a Case with whatever upstream state it depends
on, a published AgentVersion for its own code (the real Agent rows already
exist as seed data — S0/A/B/C/D/F — so this only ever adds a version under
the existing agent, never a duplicate Agent row), and a queued PipelineRun
to pass in. `fake_run_structured` is how every test controls what the
"model" returns without a real LLM call — each agent module imports
`run_structured` into its own namespace, so callers must monkeypatch the
name on the *agent* module, not on `app.services.llm_client`.
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.db.models.agent import Agent, AgentVersion
from app.db.models.case import Case, CaseStatus, Document, PipelineRun


def make_published_version(db_session: Session, agent_code: str) -> AgentVersion:
    """Adds a fresh published version under the real, already-seeded Agent
    row for this code — picked up by get_published_version() because it
    orders by published_at desc, so it shadows whatever's really published
    within this test's transaction without touching that row at all."""
    agent = db_session.query(Agent).filter(Agent.code == agent_code).first()
    assert agent is not None, f"seed data missing: no Agent row for code={agent_code}"
    version = AgentVersion(
        id=uuid.uuid4(), agent_id=agent.id, version_label=f"test-{uuid.uuid4().hex[:6]}",
        prompt_text="测试用 prompt", out_schema={}, checks=[], status="published",
        published_at=datetime.now(timezone.utc),
    )
    db_session.add(version)
    db_session.commit()
    return version


def make_case(db_session: Session, *, current_step: str = "up", n_documents: int = 0) -> Case:
    """Commits, not just flushes — in production the case (and any
    documents/stage_map/etc. an agent depends on) was written by an earlier,
    already-finished request, long before the worker picks up this run.
    `finish_failed()` calls `db.rollback()` on failure; if this fixture data
    lived in the same uncommitted transaction as the agent's own work, that
    rollback would wipe the case out from under it — not what happens for
    real, and not what a regression test should be exercising either."""
    case = Case(
        id=uuid.uuid4(), case_no=f"CASE-TEST-{uuid.uuid4().hex[:6]}",
        patient_meta={}, status=CaseStatus.queued.value, current_step=current_step,
    )
    db_session.add(case)
    db_session.flush()
    for i in range(1, n_documents + 1):
        db_session.add(Document(id=uuid.uuid4(), case_id=case.id, seq=i, source_file=f"fake/{i}.jpg", content_type="image/jpeg"))
    db_session.commit()
    db_session.refresh(case)
    return case


def make_run(db_session: Session, case: Case, agent_code: str) -> PipelineRun:
    """Also a commit, not a flush — mirrors case_service.create_queued_run(),
    which is called (and committed) from the API request handler, in a
    separate transaction from the worker that later runs the agent."""
    run = PipelineRun(id=uuid.uuid4(), case_id=case.id, agent_code=agent_code, status="queued")
    db_session.add(run)
    db_session.commit()
    return run


def fake_run_structured(result: dict[str, Any]) -> Callable:
    """A `run_structured` stand-in that returns a canned dict — the "model
    behaved" case. Accepts and ignores every real kwarg (system_prompt,
    schema, images, provider, on_progress, on_usage, ...) so it drops into
    any agent's call site unchanged."""

    async def _fake(**kwargs) -> dict:
        return result

    return _fake


def sequenced_run_structured(*outcomes: Any) -> Callable:
    """Each call pops the next outcome off the queue — a dict for a
    successful (possibly still domain-invalid) return, or an Exception
    instance to have that call raise instead. For testing the unified
    framework's repair/retry loop, where the model behaves differently
    call to call (fails validation, then a "repaired" call succeeds;
    a transient network error, then a retry succeeds; etc.). Exhausting
    the queue means the code under test called run_structured more times
    than the test expected — fails loud rather than looping forever."""
    queue = list(outcomes)

    async def _fake(**kwargs) -> dict:
        assert queue, "run_structured 被调用的次数超过了测试准备的 outcomes 数量——重试/修复次数上限没有生效？"
        outcome = queue.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return _fake


def raising_run_structured(exc: Exception) -> Callable:
    """A `run_structured` stand-in that raises — the "LLM call itself
    failed" case (timeout, 5xx, truncated response, whatever
    llm_client.LLMStructuredError or a bare network exception looks like
    to a caller). Every agent's `except Exception: finish_failed(...); raise`
    has to handle this the same way it handles a validation PipelineError."""

    async def _fake(**kwargs) -> dict:
        raise exc

    return _fake

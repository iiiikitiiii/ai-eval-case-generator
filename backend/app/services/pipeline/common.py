"""Shared plumbing every agent runner uses: looking up the published prompt
version and recording the PipelineRun audit trail the same way every time.
Pulled out once B/C/D/F started repeating agent_a.py's pattern verbatim.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models.agent import Agent, AgentVersion
from app.db.models.case import Case, CaseStatus, PipelineRun


class PipelineError(RuntimeError):
    """Raised for expected, user-facing failures (missing input, no
    published prompt version, malformed model output) — the API layer
    turns these into 400s instead of 500s."""


def get_published_version(db: Session, agent_code: str) -> AgentVersion | None:
    agent = db.query(Agent).filter(Agent.code == agent_code).first()
    if agent is None:
        return None
    return (
        db.query(AgentVersion)
        .filter(AgentVersion.agent_id == agent.id, AgentVersion.status == "published")
        .order_by(AgentVersion.published_at.desc())
        .first()
    )


def create_queued_run(db: Session, case: Case, agent_code: str, input_ref: dict | None = None) -> PipelineRun:
    """Called from the request handler, before the job ever reaches a
    worker — the row exists (status=queued) the instant the API responds,
    so the frontend has something to poll immediately instead of a gap
    where "did my click even register?" has no answer.

    input_ref carries per-run parameters the caller chose at trigger time
    (currently just F's persona_codes selection) through to the worker,
    which reads it back off the same row — the queue only passes run_id/
    agent_code as job args, so this is the row's own memory of "what was
    asked for", not a separate side channel."""
    run = PipelineRun(case_id=case.id, agent_code=agent_code, status="queued", input_ref=input_ref)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def mark_running(db: Session, run: PipelineRun, agent_version_id: uuid.UUID) -> None:
    """Called from inside the worker once it actually picks the job up."""
    run.status = "running"
    run.agent_version_id = agent_version_id
    run.started_at = datetime.now(timezone.utc)
    db.commit()


def make_progress_writer(db: Session, run: PipelineRun):
    """Returns the on_progress callback every runner hands to
    run_structured() — llm_client streams the model's reasoning_content and
    calls this with the accumulated text so far (already throttled on that
    side, this doesn't need its own rate limiting). Overwrites, not
    appends: progress_note is a rolling snapshot of "what's it thinking
    right now", not a transcript."""

    def _write(text: str) -> None:
        run.progress_note = text
        db.commit()

    return _write


def make_usage_writer(db: Session, run: PipelineRun):
    """Returns the on_usage callback every runner hands to run_structured()
    — llm_client calls this once with the real token counts the provider
    reported, regardless of whether the call ultimately produced a usable
    structured result (a truncated/failed call still spent tokens, and the
    board's usage totals should reflect that, not just the successes)."""

    def _write(usage: dict) -> None:
        run.token_usage = usage
        db.commit()

    return _write


def finish_succeeded(db: Session, run: PipelineRun, output_ref: dict) -> None:
    run.status = "succeeded"
    run.output_ref = output_ref
    run.finished_at = datetime.now(timezone.utc)
    db.commit()


def int_array(value: object) -> list[int]:
    """Sanitizes a value bound for an ARRAY(Integer) column. Observed in the
    wild: MiniMax returning `[""]` instead of `[]` for "no documents" —
    schema said `items: integer`, but nothing enforces that on this
    provider. Postgres has zero tolerance for a stray `""` in an
    `INTEGER[]` insert (an `InvalidTextRepresentation` crash three frames
    into a bulk INSERT, useless to debug from), so every runner passes
    int-array fields through this before they reach an ORM object —
    silently drop anything that isn't actually an int rather than let one
    bad element take down the whole write."""
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, int) and not isinstance(v, bool)]


def require_fields(item: dict, keys: list[str], label: str) -> None:
    """MiniMax's tool-calling has no `tool_choice` to force schema
    compliance (see llm_client's module docstring) — the model occasionally
    drops a field the schema marks required. Every runner validates before
    persisting so a bad item fails loud as a 400 with the field name, not a
    bare `KeyError` 500 three lines into a DB write."""
    missing = [k for k in keys if item.get(k) in (None, "")]
    if missing:
        raise PipelineError(f"{label} 缺少必填字段 {missing}：{item}")


def finish_failed(db: Session, case: Case, run: PipelineRun, exc: Exception) -> None:
    """Any agent failure parks the whole case as `blocked` — never leave a
    run sitting in `running` or a case silently stuck with half-written
    data from a rolled-back attempt."""
    db.rollback()
    run.status = "failed"
    run.error = str(exc)
    run.finished_at = datetime.now(timezone.utc)
    case.status = CaseStatus.blocked.value
    db.add(run)
    db.add(case)
    db.commit()

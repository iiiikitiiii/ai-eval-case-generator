"""Agent D: backfills `real_gap` stages only — confirmed-but-unrecorded past
events. Deliberately does NOT touch `uncovered` stages (the future); see
doc/需求细节澄清.md and the prompt in seed_agents.py for why.

Runs through `pipeline.framework.UnifiedAgentRunner` (阶段 4 of
doc/Agent统一架构改造方案.md). Two things worth knowing about D's shape:

- When there's nothing to backfill, `_build_request` returns an
  `AgentRequest` with `precomputed_result={"mock_entries": []}` — the
  framework skips the LLM call entirely and feeds that straight to
  `_validate`/`_persist` rather than spending a request to get back an
  empty array the structural answer (from `stage_map`) already implies.
- The core red line — D must never persist content for a non-real_gap
  stage — lives in `_validate`: giving the model one bounded repair
  attempt when it violates this doesn't weaken the line, since
  `_persist()` never runs until `_validate()` reports zero issues.

The old hand-rolled `run_agent_d()` was deleted once this path was
validated against a real LLM call end-to-end (see README history);
阶段 0's tests/test_agent_d_regression.py went with it, superseded by
tests/test_agent_d_unified_regression.py.
"""
import json

from sqlalchemy.orm import Session

from app.db.models.case import Case, MockEntry, PipelineRun, StageMap
from app.services.pipeline.common import PipelineError
from app.services.pipeline.framework import AgentRequest, AgentSpec, RetryPolicy, ValidationIssue, ValidationResult, run_with_framework

__all__ = ["PipelineError", "D_SPEC", "run_agent_d", "real_gap_stages"]


def real_gap_stages(case: Case) -> list[StageMap]:
    return [s for s in case.stage_map if s.status == "real_gap"]


def _build_request(db: Session, case: Case, run: PipelineRun) -> AgentRequest:
    if not case.stage_map:
        raise PipelineError("病例还没有做阶段映射，无法判断哪些阶段需要补丁（先运行 Agent B）")

    gaps = real_gap_stages(case)
    if not gaps:
        return AgentRequest(user_text="", precomputed_result={"mock_entries": []})

    user_text = (
        "以下是需要补丁的 real_gap 阶段（JSON 数组，只含这些，不含 uncovered 阶段——"
        "不要为列表之外的任何阶段编造内容）：\n\n"
        + json.dumps([{"stage_code": s.stage_code, "reason": s.reason} for s in gaps], ensure_ascii=False, indent=2)
    )
    return AgentRequest(user_text=user_text)


def _validate(db: Session, case: Case, result: dict, context: dict) -> ValidationResult:
    gap_codes = {s.stage_code for s in real_gap_stages(case)}
    entries = result.get("mock_entries") or []

    issues: list[ValidationIssue] = []
    for i, e in enumerate(entries):
        missing = [k for k in ("journey_stage", "title", "clinical_basis", "strength") if e.get(k) in (None, "")]
        if missing:
            issues.append(ValidationIssue(code="missing_field", path=f"mock_entries[{i}]", message=f"mock_entries 第 {i + 1} 项缺少必填字段 {missing}"))
    if issues:
        return ValidationResult(issues=issues)

    bad = [e["journey_stage"] for e in entries if e["journey_stage"] not in gap_codes]
    if bad:
        # 核心红线——D 绝不能为非 real_gap 阶段编造内容。给一次修复机会
        # 不代表放宽这条线：只要这条 issue 还在，validate() 就不会通过，
        # persist() 就永远不会跑；修复耗尽后是"整条运行失败、一条都不落库"。
        issues.append(ValidationIssue(code="fabricated_non_real_gap_stage", message=f"模型为非 real_gap 阶段编造了内容：{bad}"))
    return ValidationResult(issues=issues)


def _persist(db: Session, case: Case, result: dict, run: PipelineRun, context: dict) -> dict:
    entries = result.get("mock_entries") or []
    for row in list(case.mock_entries):
        db.delete(row)
    db.flush()

    if not entries:
        return {"mock_count": 0, "skipped": "没有 real_gap 阶段，无需补丁"} if not real_gap_stages(case) else {"mock_count": 0}

    for e in entries:
        db.add(
            MockEntry(
                case_id=case.id,
                stage_code=e["journey_stage"],
                date_label=e.get("date"),
                title=e["title"],
                desc=e.get("desc"),
                clinical_basis=e["clinical_basis"],
                strength=e["strength"],
                disclaimer=e.get("disclaimer"),
                agent_version_id=run.agent_version_id,
            )
        )
    return {"mock_count": len(entries)}


D_SPEC = AgentSpec(
    code="D",
    build_request=_build_request,
    validate=_validate,
    persist=_persist,
    retry_policy=RetryPolicy(max_network_retries=2, max_repairs=1),
)


async def run_agent_d(db: Session, case: Case, run: PipelineRun) -> None:
    await run_with_framework(db, D_SPEC, case, run)

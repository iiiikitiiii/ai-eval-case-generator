"""Agent B: structured document timeline → J01–J06 stage map + boundary
decisions (business's real six-stage journey — see STAGE_CODES below).
Runs after flags are resolved (see case_service.advance_step's gate for
target_step="b"); reruns are idempotent — it fully replaces the case's
stage_map and boundary_decisions rather than merging (product decision,
see CaseWizardPage's B retry confirmation dialog — not something the
阶段 3 migration to `pipeline.framework.UnifiedAgentRunner` revisited).

This module only supplies `_build_request`, `_validate`, `_persist`. The
old hand-rolled `run_agent_b()` was deleted once this path was validated
against a real LLM call end-to-end (see README history); 阶段 0's
tests/test_agent_b_regression.py went with it, superseded by
tests/test_agent_b_unified_regression.py.
"""
import json

from sqlalchemy.orm import Session

from app.db.models.case import BoundaryDecision, Case, PipelineRun, StageMap
from app.services.pipeline.common import PipelineError, int_array
from app.services.pipeline.framework import AgentRequest, AgentSpec, RetryPolicy, ValidationIssue, ValidationResult, run_with_framework

__all__ = ["PipelineError", "STAGE_CODES", "B_SPEC", "run_agent_b", "build_doc_summary"]

STAGE_CODES = [f"J0{i}" for i in range(1, 7)]  # 业务方真实六阶段旅程，见 import_scenario_standards.SIX_STAGE_CODES


def build_doc_summary(case: Case) -> list[dict]:
    return [
        {
            "seq": d.seq,
            "document_type": d.document_type,
            "exam_time": d.exam_time,
            "report_time": d.report_time,
            "structured_info": d.structured_info,
            "core_abnormality": d.core_abnormality,
        }
        for d in sorted(case.documents, key=lambda x: x.seq)
    ]


def _build_request(db: Session, case: Case, run: PipelineRun) -> AgentRequest:
    if not case.documents:
        raise PipelineError("病例还没有抽取出任何单据，无法做阶段映射")
    user_text = (
        "以下是这位患者按 seq 排列的结构化病历时间线（JSON 数组），"
        "请输出每份病历所属的 J01–J06 阶段：\n\n" + json.dumps(build_doc_summary(case), ensure_ascii=False, indent=2)
    )
    return AgentRequest(user_text=user_text)


def _validate(db: Session, case: Case, result: dict, context: dict) -> ValidationResult:
    stage_map = result.get("stage_map") or {}
    missing = [c for c in STAGE_CODES if c not in stage_map]
    if missing:
        # 阶段都没凑齐时，先只报这一条——后面每个阶段的字段校验意义不大
        # （很可能是同一次输出被截断/不完整），凑一堆噪音不如让修复调用
        # 先把六个阶段配齐。
        return ValidationResult(issues=[ValidationIssue(code="missing_stage_coverage", message=f"模型没有覆盖全部 6 个阶段，缺：{missing}")])

    issues: list[ValidationIssue] = []
    for code in STAGE_CODES:
        if stage_map[code].get("status") in (None, ""):
            issues.append(ValidationIssue(code="missing_field", path=f"stage_map.{code}", message=f"stage_map.{code} 缺少必填字段 status"))
    if issues:
        return ValidationResult(issues=issues)

    doc_seqs = {d.seq for d in case.documents}
    for i, bd in enumerate(result.get("boundary_decisions") or []):
        missing_bd = [k for k in ("doc", "assigned", "alternative") if bd.get(k) in (None, "")]
        if missing_bd:
            issues.append(ValidationIssue(code="missing_field", path=f"boundary_decisions[{i}]", message=f"boundary_decisions 第 {i + 1} 项缺少必填字段 {missing_bd}"))
            continue
        if bd["doc"] not in doc_seqs:
            issues.append(ValidationIssue(code="invalid_doc_ref", path=f"boundary_decisions[{i}].doc", message=f"boundary_decisions 第 {i + 1} 项引用了不存在的病历 seq：{bd['doc']}"))
        if bd["assigned"] not in STAGE_CODES or bd["alternative"] not in STAGE_CODES:
            issues.append(ValidationIssue(code="invalid_stage_code", path=f"boundary_decisions[{i}]", message=f"boundary_decisions 第 {i + 1} 项的阶段代码不合法：{bd['assigned']} / {bd['alternative']}"))
    return ValidationResult(issues=issues)


def _persist(db: Session, case: Case, result: dict, run: PipelineRun, context: dict) -> dict:
    stage_map = result["stage_map"]
    boundary_decisions = result.get("boundary_decisions") or []

    # 幂等重跑：先清空这个病例旧的阶段映射与边界判断——产品决策已经定了
    # （见前端重试 B 的确认弹窗），这里原样保留，不是这次迁移要改的行为。
    for row in list(case.stage_map):
        db.delete(row)
    for row in list(case.boundary_decisions):
        db.delete(row)
    db.flush()

    for code in STAGE_CODES:
        info = stage_map[code]
        db.add(StageMap(case_id=case.id, stage_code=code, status=info["status"], docs=int_array(info.get("docs")), reason=info.get("reason")))

    for bd in boundary_decisions:
        db.add(
            BoundaryDecision(
                case_id=case.id,
                doc_seq=bd["doc"],
                assigned_stage=bd["assigned"],
                alternative_stage=bd["alternative"],
                rule_applied=bd.get("rule_applied"),
                rationale=bd.get("rationale"),
                needs_human=bd.get("needs_human", True),
            )
        )

    return {"stages_covered": len(stage_map), "boundary_decisions": len(boundary_decisions)}


B_SPEC = AgentSpec(
    code="B",
    build_request=_build_request,
    validate=_validate,
    persist=_persist,
    retry_policy=RetryPolicy(max_network_retries=2, max_repairs=1),
)


async def run_agent_b(db: Session, case: Case, run: PipelineRun) -> None:
    await run_with_framework(db, B_SPEC, case, run)

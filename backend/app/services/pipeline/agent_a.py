"""Agent A: raw document images → structured document records + cross-doc
review flags. The first agent wired to a real LLM call.

Runs through `pipeline.framework.UnifiedAgentRunner` (阶段 2 of
doc/Agent统一架构改造方案.md — migrating the image-input agent and its
"文档数量一一对应" check). This module only supplies `_build_request`,
`_validate`, `_persist`. Two things worth knowing about A's shape
specifically:

- Image bytes are read exactly once per run, in `_build_request`, never
  re-read across a repair attempt — the framework's retry loop reuses the
  same `AgentRequest` object for every attempt (only `user_text` changes),
  so this holds by construction, not by a separate guard. This was the
  plan's explicit verification target for this migration.
- "文档数量一一对应" used to be an immediate failure; it's now a
  repairable ValidationIssue (a count mismatch is usually the model
  under/over-processing, the same class of self-correctable error as C's
  out-of-range doc references) — `persist()` still only ever runs after
  `validate()` reports zero issues, so this doesn't weaken the check.

The old hand-rolled `run_agent_a()` was deleted once this path was
validated against a real LLM call end-to-end (see README history);
阶段 0's tests/test_agent_a_regression.py went with it, superseded by
tests/test_agent_a_unified_regression.py.
"""
from sqlalchemy.orm import Session

from app.core.storage import get_object_bytes
from app.db.models.case import Case, CaseStatus, PipelineRun, ReviewFlag
from app.services.pipeline.common import PipelineError, int_array
from app.services.pipeline.framework import AgentRequest, AgentSpec, RetryPolicy, ValidationIssue, ValidationResult, run_with_framework

__all__ = ["PipelineError", "A_SPEC", "run_agent_a"]


def _build_request(db: Session, case: Case, run: PipelineRun) -> AgentRequest:
    if not case.documents:
        raise PipelineError("病例还没有上传任何单据，无法抽取")
    docs = sorted(case.documents, key=lambda d: d.seq)
    images = [(get_object_bytes(d.source_file), d.content_type or "image/jpeg") for d in docs]
    user_text = f"请按顺序处理这 {len(images)} 份病历图片（seq 1..{len(images)}），输出 documents 与 review_flags。"
    return AgentRequest(user_text=user_text, images=images)


def _validate(db: Session, case: Case, result: dict, context: dict) -> ValidationResult:
    """数量对不上时不再往下逐条查 review_flags：zip 会错位，报出来的字段
    缺失信息没有意义，不如只把数量问题说清楚，交给修复调用先处理这一个。"""
    docs = sorted(case.documents, key=lambda d: d.seq)
    out_docs = result.get("documents") or []
    if len(out_docs) != len(docs):
        return ValidationResult(issues=[ValidationIssue(
            code="doc_count_mismatch",
            message=f"模型返回 {len(out_docs)} 份记录，但上传了 {len(docs)} 份单据，数量必须一一对应",
        )])

    issues: list[ValidationIssue] = []
    for i, flag in enumerate(result.get("review_flags") or []):
        missing = [k for k in ("type", "field", "detail") if flag.get(k) in (None, "")]
        if missing:
            issues.append(ValidationIssue(
                code="missing_field", path=f"review_flags[{i}]",
                message=f"review_flags 第 {i + 1} 项缺少必填字段 {missing}",
            ))
    return ValidationResult(issues=issues)


def _persist(db: Session, case: Case, result: dict, run: PipelineRun, context: dict) -> dict:
    docs = sorted(case.documents, key=lambda d: d.seq)
    out_docs = result.get("documents") or []

    for doc, data in zip(docs, out_docs):
        time_info = data.get("time") or {}
        doc.document_type = data.get("document_type")
        doc.exam_time = time_info.get("exam_time")
        doc.report_time = time_info.get("report_time")
        doc.exam_items = data.get("exam_items") or []
        doc.structured_info = data.get("structured_info") or {}
        doc.core_abnormality = data.get("core_abnormality")
        doc.ocr_full_text = data.get("ocr_full_text")
        doc.confidence = data.get("confidence") or {}
        doc.agent_version_id = run.agent_version_id  # mark_running() 已经写好了，不用再查一次已发布版本

    review_flags = result.get("review_flags") or []
    for flag in review_flags:
        db.add(
            ReviewFlag(
                case_id=case.id,
                type=flag["type"],
                field=flag["field"],
                detail=flag["detail"],
                why=flag.get("why"),
                involved_docs=int_array(flag.get("involved_docs")),
                severity=flag.get("severity") or "medium",
            )
        )

    case.status = CaseStatus.reviewing_flags.value
    case.current_step = "a"

    return {"document_count": len(out_docs), "flag_count": len(review_flags)}


A_SPEC = AgentSpec(
    code="A",
    build_request=_build_request,
    validate=_validate,
    persist=_persist,
    retry_policy=RetryPolicy(max_network_retries=2, max_repairs=1),
)


async def run_agent_a(db: Session, case: Case, run: PipelineRun) -> None:
    await run_with_framework(db, A_SPEC, case, run)

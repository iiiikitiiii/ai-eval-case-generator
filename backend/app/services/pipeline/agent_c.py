"""Agent C: full document set → traceable persona facts. Independent of B —
both read the same document set, neither depends on the other's output —
so a B failure doesn't block C and vice versa.

Runs through `pipeline.framework.UnifiedAgentRunner` (阶段 1 of
doc/Agent统一架构改造方案.md — C was migrated first precisely because it
doesn't read images, doesn't touch B's boundary decisions, and has the
simplest persist step of the five agents). This module only supplies the
three pieces the framework needs: `_build_request` (构造输入),
`_validate` (校验模型输出，返回结构化 issue 而不是直接抛异常——同样这条
"引用了不存在的病历 seq"的校验，旧的单体实现发现了只能让整条用例失败，
这里发现了会先给模型一次修复机会，修复后还是不对才真正失败), and
`_persist` (落库). The old hand-rolled `run_agent_c()` (version lookup,
run/finish bookkeeping, direct `run_structured()` call — all now the
framework's job, identical across every agent) was deleted once this path
was validated against a real LLM call end-to-end — see the README's
"Agent 统一架构改造方案" sections for that history;阶段 0's
tests/test_agent_c_regression.py (which exercised the deleted
implementation) went with it, superseded by
tests/test_agent_c_unified_regression.py.
"""
import json

from sqlalchemy.orm import Session

from app.db.models.case import Case, PersonaField, PipelineRun
from app.services.pipeline.common import PipelineError, int_array
from app.services.pipeline.framework import AgentRequest, AgentSpec, RetryPolicy, ValidationIssue, ValidationResult, run_with_framework

__all__ = ["PipelineError", "C_SPEC", "run_agent_c"]


def build_persona_context(case: Case) -> list[dict]:
    return [
        {"seq": d.seq, "structured_info": d.structured_info, "core_abnormality": d.core_abnormality}
        for d in sorted(case.documents, key=lambda x: x.seq)
    ]


def _build_request(db: Session, case: Case, run: PipelineRun) -> AgentRequest:
    if not case.documents:
        raise PipelineError("病例还没有抽取出任何单据，无法组合画像")
    user_text = "以下是这位患者的全部结构化病历（JSON 数组），请输出患者画像：\n\n" + json.dumps(
        build_persona_context(case), ensure_ascii=False, indent=2
    )
    return AgentRequest(user_text=user_text)


def _validate(db: Session, case: Case, result: dict, context: dict) -> ValidationResult:
    doc_seqs = {d.seq for d in case.documents}
    issues: list[ValidationIssue] = []
    persona = result.get("persona") or []
    for i, item in enumerate(persona):
        missing = [k for k in ("field", "value") if item.get(k) in (None, "")]
        if missing:
            issues.append(ValidationIssue(
                code="missing_field", path=f"persona[{i}]",
                message=f"persona 第 {i + 1} 项缺少必填字段 {missing}",
            ))
            continue
        # 先剔除非整数元素（模型偶尔塞 [""] 而不是 []）再比对是否引用了
        # 真实存在的病历——杂质元素本身不算错，不该因为它触发一次修复。
        sources = int_array(item.get("source"))
        bad_source = [s for s in sources if s not in doc_seqs]
        if bad_source:
            issues.append(ValidationIssue(
                code="invalid_doc_ref", path=f"persona[{i}].source",
                message=f"字段「{item['field']}」引用了不存在的病历 seq：{bad_source}",
            ))
    return ValidationResult(issues=issues)


def _persist(db: Session, case: Case, result: dict, run: PipelineRun, context: dict) -> dict:
    persona = result.get("persona") or []
    for row in list(case.persona_fields):
        db.delete(row)
    db.flush()
    for item in persona:
        db.add(PersonaField(case_id=case.id, field=item["field"], value=item["value"], source=int_array(item.get("source")), flag=item.get("flag")))
    return {"field_count": len(persona), "excluded_by_design": result.get("excluded_by_design") or []}


C_SPEC = AgentSpec(
    code="C",
    build_request=_build_request,
    validate=_validate,
    persist=_persist,
    retry_policy=RetryPolicy(max_network_retries=2, max_repairs=1),
)


async def run_agent_c(db: Session, case: Case, run: PipelineRun) -> None:
    await run_with_framework(db, C_SPEC, case, run)

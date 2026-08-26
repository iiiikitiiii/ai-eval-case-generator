"""Agent F: stage map + persona + mock entries + scenario library + persona
library → cutpoints and their test cases.

F's out_schema is a *flat* array — one row per (cutpoint × scenario_type ×
test_direction) combination, repeating the cutpoint's fields on every row
that shares its cutpoint_id (matches how both design prototypes shaped it,
and how the business's own 已设计测试用例 spreadsheet lays out "用例01,
用例02..."). The DB model is normalized (one Cutpoint row, many Query
children), so `_persist`'s job beyond the usual bookkeeping is grouping
the flat output back into that shape.

Since 专病管家跑测方案811.xlsx landed, each Query ("一条测试用例") is no
longer a single sentence — it carries a test_direction/test_background,
an explicit curated list of images to actually send to the tested product,
and up to 4 persona-scripted multi-turn conversations (QueryVariant), each
with its own turn-by-turn messages and a behavior_logic narrative. The
scenario library (49 real scenarios), red line catalog (11 canonical
red lines) and persona library (4 fixed personas) are all real reference
data now, not placeholders — see app/import_scenario_standards.py and
app/seed_personas.py.

Runs through `pipeline.framework.UnifiedAgentRunner` (阶段 4 of
doc/Agent统一架构改造方案.md — the last and most involved migration:
scenario library / red line catalog / persona library / image references /
multiple persona_variants all have to line up). `_build_request` computes
the shared derived state (allowed scenario/persona sets, the doc-seq
allowlist, the standard-card lookup) once and stashes it on
`AgentRequest.context`, so `_validate`/`_persist` read the exact same sets
instead of each recomputing their own (and potentially drifting from each
other mid-run). `_validate` deliberately does **not** turn out-of-selection
scenario refs, out-of-range image seqs, or fabricated persona codes into
ValidationIssues — those three keep F's long-standing "drop the offending
row/variant, don't fail the whole run" behavior (see the comment in
`_validate`), which the migration preserved as-is rather than tightening
to match A/B/C/D's stricter "flag it, give the model a repair chance"
pattern; whether to unify that is a product/architecture call for a later
phase, not something the migration decided unilaterally.

The old hand-rolled `run_agent_f()` was deleted once this path was
validated against a real LLM call end-to-end (see README history);
阶段 0's tests/test_agent_f_regression.py went with it, superseded by
tests/test_agent_f_unified_regression.py (and
tests/test_agent_f_scenario_selection.py, which only exercises
`build_context`'s persona/scenario filtering and didn't need to change).
"""
import json
from collections import defaultdict

from sqlalchemy.orm import Session

from app.db.models.agent import ScenarioType, UserPersona
from app.db.models.case import Case, Cutpoint, PipelineRun, Query, QueryVariant
from app.db.models.standard import RedLine, StandardCard
from app.services.pipeline.common import PipelineError, int_array
from app.services.pipeline.framework import AgentRequest, AgentSpec, RetryPolicy, ValidationIssue, ValidationResult, run_with_framework

__all__ = ["PipelineError", "F_SPEC", "run_agent_f", "build_context", "PERSONA_CODES"]

PERSONA_CODES = {"patient_low", "patient_high", "family_low", "family_high"}


def build_context(db: Session, case: Case, persona_codes: list[str] | None = None, scenario_codes: list[str] | None = None) -> dict:
    stage_map = [{"stage_code": s.stage_code, "status": s.status, "docs": s.docs, "reason": s.reason} for s in case.stage_map]
    persona = [{"field": p.field, "value": p.value, "flag": p.flag} for p in case.persona_fields]
    mocks = [
        {"journey_stage": m.stage_code, "date": m.date_label, "title": m.title, "clinical_basis": m.clinical_basis, "disclaimer": m.disclaimer}
        for m in case.mock_entries
    ]
    docs = [
        {"seq": d.seq, "document_type": d.document_type, "exam_time": d.exam_time, "report_time": d.report_time}
        for d in sorted(case.documents, key=lambda x: x.seq)
    ]

    # 不传 scenario_codes = 用全部启用中的场景（老行为，模型自己判断该
    # 病例的哪些阶段命中场景库里的哪些场景）；传了就只把选中的几个场景
    # 塞进上下文——跟 persona_codes 同一个道理：这条病例这一轮要不要覆盖
    # 某几个场景，在触发运行时就定了，不用生成一整批之后再人工挑着看。
    scenario_query = db.query(ScenarioType).filter(ScenarioType.active.is_(True))
    if scenario_codes:
        scenario_query = scenario_query.filter(ScenarioType.code.in_(scenario_codes))

    cards_by_scenario = {sc.scenario_type_id: sc for sc in db.query(StandardCard).all()}
    scenario_library = []
    for s in scenario_query.all():
        entry = {"code": s.code, "name": s.name, "journey_stages": s.journey_stages, "description": s.description}
        card = cards_by_scenario.get(s.id)
        if card:
            entry["has_standard_card"] = True
            entry["standard_card_hint"] = {"patient_need": card.patient_need, "whats_right": card.whats_right, "whats_wrong": card.whats_wrong}
        scenario_library.append(entry)

    red_lines = [
        {"seq": r.seq, "name": r.name, "judgment_criteria": r.judgment_criteria}
        for r in db.query(RedLine).order_by(RedLine.seq).all()
    ]

    # 不传 persona_codes = 用全部启用中的画像（老行为）；传了就只把选中的
    # 几个塞进上下文——F 的 prompt 只会为它在这里实际看到的画像生成脚本，
    # 所以"这条用例要不要覆盖家属视角"这种取舍在触发运行时就定了，不用等
    # 生成完再人工筛掉不想要的那几套。
    persona_query = db.query(UserPersona).filter(UserPersona.active.is_(True))
    if persona_codes:
        persona_query = persona_query.filter(UserPersona.code.in_(persona_codes))
    persona_library = [
        {"code": p.code, "role": p.role, "cognition": p.cognition, "name": p.name, "behavior_guideline": p.behavior_guideline}
        for p in persona_query.all()
    ]

    return {
        "documents": docs,
        "stage_map": stage_map,
        "persona": persona,
        "mock_entries": mocks,
        "scenario_library": scenario_library,
        "red_line_catalog": red_lines,
        "persona_library": persona_library,
    }


def _clean_turns(raw_turns: list) -> list[dict]:
    turns = []
    for t in raw_turns or []:
        messages = [m for m in (t.get("messages") or []) if isinstance(m, str) and m.strip()]
        if not messages:
            continue
        try:
            round_no = int(t.get("round"))
        except (TypeError, ValueError):
            round_no = len(turns) + 1
        turns.append({"round": round_no, "messages": messages, "note": t.get("note")})
    return turns


def _build_request(db: Session, case: Case, run: PipelineRun) -> AgentRequest:
    if not case.stage_map:
        raise PipelineError("病例还没有做阶段映射，无法生成裂点（先运行 Agent B）")
    if not case.persona_fields:
        raise PipelineError("病例还没有组合出患者画像，无法生成裂点（先运行 Agent C）")

    persona_codes = (run.input_ref or {}).get("persona_codes")
    scenario_codes = (run.input_ref or {}).get("scenario_codes")
    context = build_context(db, case, persona_codes, scenario_codes)
    if not context["persona_library"]:
        raise PipelineError("没有可用的画像——检查一下选的画像代码是否存在、是否处于启用状态")
    if not context["scenario_library"]:
        raise PipelineError("没有可用的场景——检查一下选的场景代码是否存在、是否处于启用状态")

    # 只认这次实际喂给模型的那几个画像/场景——即便模型没听指令、编出了
    # 一个不在库里但确实存在的 code，也不能让它蒙混过关：那等于绕过了
    # 人工在触发运行时做的筛选。算一次，塞进 request.context，validate/
    # persist 复用同一份，不各自重算。
    shared = {
        "cards_by_code": {s["code"]: s.get("has_standard_card", False) for s in context["scenario_library"]},
        "allowed_scenario_codes": {s["code"] for s in context["scenario_library"]},
        "persona_id_by_code": {
            p.code: p.id for p in db.query(UserPersona).filter(
                UserPersona.code.in_({p["code"] for p in context["persona_library"]}),
            ).all()
        },
        "doc_seqs": {d.seq for d in case.documents},
    }

    user_text = (
        "以下是这位患者的旅程表、画像、推测补丁、标准场景库、通用红线目录与候选画像库（JSON），"
        "请生成裂点与完整测试用例：\n\n" + json.dumps(context, ensure_ascii=False, indent=2)
    )
    return AgentRequest(user_text=user_text, context=shared)


def _validate(db: Session, case: Case, result: dict, context: dict) -> ValidationResult:
    rows = result.get("cutpoints") or []
    issues: list[ValidationIssue] = []
    for i, row in enumerate(rows):
        missing = [
            k for k in ("cutpoint_id", "journey_stage", "provenance", "scenario_type", "test_direction", "test_background")
            if row.get(k) in (None, "")
        ]
        if missing:
            issues.append(ValidationIssue(code="missing_field", path=f"cutpoints[{i}]", message=f"cutpoints 第 {i + 1} 项缺少必填字段 {missing}"))
    if issues:
        return ValidationResult(issues=issues)
    # 场景越界引用、图片 seq 越界、画像代码编造——这三类"坏数据"是既有的
    # "静默丢弃这一行，不整体失败"策略（见模块顶部说明），不在这里报成
    # ValidationIssue，交给 _persist 的既有过滤逻辑处理。
    return ValidationResult(issues=[])


def _persist(db: Session, case: Case, result: dict, run: PipelineRun, context: dict) -> dict:
    allowed_scenario_codes = context["allowed_scenario_codes"]
    persona_id_by_code = context["persona_id_by_code"]
    doc_seqs = context["doc_seqs"]
    cards_by_code = context["cards_by_code"]

    rows = result.get("cutpoints") or []
    rows = [row for row in rows if row["scenario_type"] in allowed_scenario_codes]
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["cutpoint_id"]].append(row)

    for cp in list(case.cutpoints):
        db.delete(cp)
    db.flush()

    query_count = 0
    variant_count = 0
    for cutpoint_id, items in grouped.items():
        first = items[0]
        cutpoint = Cutpoint(
            case_id=case.id,
            stage_code=first["journey_stage"],
            provenance=first["provenance"],
            anchor=first.get("anchor") or {},
            known_set=first.get("known_set") or [],
            unknown_set=first.get("unknown_set") or [],
            judgment=first.get("tested_judgment"),
            validity_check=first.get("validity_check") or {},
        )
        db.add(cutpoint)
        db.flush()

        for item in items:
            image_seqs = [s for s in int_array(item.get("test_image_seqs")) if s in doc_seqs]

            variants_raw = item.get("persona_variants") or []
            clean_variants = []
            for v in variants_raw:
                code = v.get("persona_code")
                if code not in PERSONA_CODES or code not in persona_id_by_code:
                    continue
                turns = _clean_turns(v.get("turns"))
                if not turns or not v.get("behavior_logic"):
                    continue
                clean_variants.append({
                    "persona_id": persona_id_by_code[code],
                    "persona_note": v.get("persona_note") or "",
                    "turns": turns,
                    "behavior_logic": v["behavior_logic"],
                })

            summary = "（未生成有效画像脚本）"
            if clean_variants:
                summary = clean_variants[0]["turns"][0]["messages"][0]

            query = Query(
                cutpoint_id=cutpoint.id,
                scenario_type=item["scenario_type"],
                text=summary,
                test_direction=item.get("test_direction"),
                test_background=item.get("test_background"),
                test_image_seqs=image_seqs,
                test_image_note=item.get("test_image_note"),
                expected_answer_points=item.get("expected_answer_points") or [],
                red_line_watch=item.get("red_line_watch") or [],
                has_standard_card=cards_by_code.get(item["scenario_type"], False),
            )
            db.add(query)
            db.flush()

            for cv in clean_variants:
                db.add(QueryVariant(query_id=query.id, **cv))
                variant_count += 1

            query_count += 1

    return {"cutpoint_count": len(grouped), "query_count": query_count, "variant_count": variant_count}


F_SPEC = AgentSpec(
    code="F",
    build_request=_build_request,
    validate=_validate,
    persist=_persist,
    retry_policy=RetryPolicy(max_network_retries=2, max_repairs=1),
)


async def run_agent_f(db: Session, case: Case, run: PipelineRun) -> None:
    await run_with_framework(db, F_SPEC, case, run)

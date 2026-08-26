"""Case-level business logic: creation, listing, and the server-side gate
checks that mirror (and are the real authority behind) the Case Workshop
wizard's step-by-step UI. The frontend gate is UX; this is enforcement —
never trust the client to have actually resolved every flag.
"""
import uuid
from datetime import date, datetime, timezone
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.storage import put_object
from app.db.models.agent import AgentVersion, ScenarioType
from app.db.models.case import (
    BoundaryDecision,
    Case,
    CaseStatus,
    Cutpoint,
    Document,
    MockEntry,
    PipelineRun,
    Query,
    QueryVariant,
    ReviewFlag,
    WORKSHOP_STEPS,
)
from app.db.models.user import User

# current_step 每一步对应的 case.status——两者语义上是一回事，只是
# WORKSHOP_STEPS 是前端路由 key，CaseStatus 是给看板/筛选用的可读状态。
_STEP_STATUS: dict[str, str] = {
    "a": CaseStatus.reviewing_flags.value,
    "b": CaseStatus.staging.value,
    "d": CaseStatus.mock_review.value,
    "f": CaseStatus.cutpoint_review.value,
    "out": CaseStatus.exported.value,
}


def generate_case_no(db: Session) -> str:
    today = date.today().strftime("%Y%m%d")
    prefix = f"CASE-{today}-"
    count_today = db.query(func.count(Case.id)).filter(Case.case_no.like(f"{prefix}%")).scalar() or 0
    return f"{prefix}{count_today + 1:03d}"


def create_case(db: Session, patient_meta: dict[str, Any], alias: str | None = None) -> Case:
    case = Case(
        case_no=generate_case_no(db), alias=(alias or None), patient_meta=patient_meta,
        status=CaseStatus.queued.value, current_step="up",
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


def list_cases(db: Session, status_filter: str | None = None, search: str | None = None) -> list[Case]:
    """P1《交互体验优化需求》"病例队列支持日常检索"：按病例编号、别名或
    初步诊断做不区分大小写的子串匹配——三个字段任意一个命中就算命中，
    不要求用户先想清楚该用哪个字段搜。"""
    q = db.query(Case).order_by(Case.updated_at.desc())
    if status_filter:
        q = q.filter(Case.status == status_filter)
    if search:
        term = f"%{search.strip()}%"
        q = q.filter(
            Case.case_no.ilike(term)
            | Case.alias.ilike(term)
            | Case.patient_meta["dx"].astext.ilike(term)
        )
    return q.all()


def get_case_or_404(db: Session, case_id: uuid.UUID) -> Case:
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "病例不存在")
    return case


def pending_flag_count(case: Case) -> int:
    return sum(1 for f in case.review_flags if f.decision is None)


def last_failed_step(case: Case) -> str | None:
    """病例被 blocked 时，最近一次失败的是哪个 Agent——列表页不用再点进
    详情或运行记录才知道要处理哪一步。只有 status=blocked 时才有意义。"""
    if case.status != CaseStatus.blocked.value:
        return None
    failed = [r for r in case.pipeline_runs if r.status == "failed"]
    if not failed:
        return None
    return max(failed, key=lambda r: r.created_at).agent_code


_TODO_LABEL_BY_STEP: dict[str, str] = {
    "up": "待上传单据并运行抽取",
    "a": "待核对冲突",
    "b": "待完成阶段裁定",
    "d": "待抽查推测数据",
    "f": "待审核裂点用例",
    "out": "已产出",
}


def todo_label(case: Case) -> str:
    """P1《交互体验优化需求》"队列首屏可看出下一步需要人工介入的病例"——
    把 status/current_step 翻成一句人话，不需要先认识 blocked/staging
    这些工程状态码。阻塞态优先于步骤态展示，因为那才是真正需要马上处理的。"""
    step = last_failed_step(case)
    if step:
        return f"Agent {step} 运行失败，需要处理"
    if case.status == CaseStatus.queued.value:
        return "待上传单据" if not case.documents else "待运行 Agent A 抽取"
    if case.current_step == "a" and pending_flag_count(case) > 0:
        return f"待裁定 {pending_flag_count(case)} 项核对冲突"
    if case.current_step == "b":
        if not case.stage_map:
            return "待运行阶段映射 / 组合抽取"
        if _pending_boundary_count(case) > 0:
            return f"待裁定 {_pending_boundary_count(case)} 项边界判断"
        return "阶段裁定已完成，待进入推测抽查"
    if case.current_step == "d" and _pending_mock_count(case) > 0:
        return f"待抽查 {_pending_mock_count(case)} 条推测数据"
    if case.current_step == "f":
        if not case.cutpoints:
            return "待运行裂点生成"
        if _accepted_query_count(case) == 0:
            return "待审核用例（还没有已纳入的用例）"
        return "用例审核中，可随时产出"
    return _TODO_LABEL_BY_STEP.get(case.current_step, "—")


def list_pipeline_runs(db: Session, case: Case) -> list[PipelineRun]:
    """Every agent invocation for this case, oldest first — the trace view's
    data source. Joins in the version label so the UI can show e.g. "A v1"
    without a second round trip."""
    rows = (
        db.query(PipelineRun, AgentVersion.version_label)
        .outerjoin(AgentVersion, PipelineRun.agent_version_id == AgentVersion.id)
        .filter(PipelineRun.case_id == case.id)
        .order_by(PipelineRun.created_at.asc())
        .all()
    )
    runs = []
    for run, label in rows:
        run.agent_version_label = label  # type: ignore[attr-defined]  # picked up by PipelineRunOut(from_attributes=True)
        runs.append(run)
    return runs


def enqueue_pipeline_run(db: Session, case: Case, agent_code: str, input_ref: dict | None = None) -> tuple[PipelineRun, bool]:
    """Returns (run, created). If this agent is already queued/running for
    this case, hands back that existing row instead of creating a second
    one — a double-click on "运行" shouldn't spend a second LLM call racing
    the first to write the same tables."""
    existing = next((r for r in case.pipeline_runs if r.agent_code == agent_code and r.status in ("queued", "running")), None)
    if existing:
        return existing, False
    from app.services.pipeline.common import create_queued_run

    return create_queued_run(db, case, agent_code, input_ref), True


async def add_documents(db: Session, case: Case, files: list[UploadFile]) -> list[Document]:
    existing = len(case.documents)
    created: list[Document] = []
    for i, upload in enumerate(files):
        seq = existing + i + 1
        raw = await upload.read()
        key = f"cases/{case.id}/{seq:02d}_{upload.filename}"
        content_type = upload.content_type or "image/jpeg"
        put_object(key, raw, content_type)
        doc = Document(case_id=case.id, seq=seq, source_file=key, content_type=content_type)
        db.add(doc)
        created.append(doc)
    db.commit()
    for d in created:
        db.refresh(d)
    return created


def delete_document(db: Session, case: Case, document_id: uuid.UUID) -> None:
    """P1《交互体验优化需求》"资料导入前支持整理与确认"——删除误传的单据。

    用户明确限定：只允许在 Agent A 运行前（current_step == "up"）删除，
    因为一旦跑过 A，下游（B 的阶段映射、C 的画像来源、boundary_decisions
    的 doc_seq 引用……）已经开始按 seq 引用这份资料，这时候重新编号会
    让那些引用全部指向错误的单据。这个阶段还没有任何下游引用，删除+
    重编号风险可控——用户原话："此时尚无下游证据引用，重编号风险可控"。
    """
    if case.current_step != "up":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "只能在运行 Agent A 抽取之前删除单据")
    doc = next((d for d in case.documents if d.id == document_id), None)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该单据不存在")

    if doc.source_file:
        delete_object(doc.source_file)
    db.delete(doc)
    db.flush()

    # 剩余单据重新连续编号（1..N），不留空洞——这一步之后没有任何表引用
    # 过旧的 seq，重排是安全的。
    remaining = sorted((d for d in case.documents if d.id != document_id), key=lambda d: d.seq)
    for i, d in enumerate(remaining, start=1):
        d.seq = i
    db.commit()


def decide_flag(db: Session, case: Case, flag_id: uuid.UUID, decision: str, actor: User) -> ReviewFlag:
    flag = next((f for f in case.review_flags if f.id == flag_id), None)
    if flag is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该核对项不存在")
    flag.decision = decision
    flag.decided_by = actor.id
    flag.decided_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(flag)
    return flag


def _pending_boundary_count(case: Case) -> int:
    return sum(1 for b in case.boundary_decisions if b.resolved_stage is None)


def _pending_mock_count(case: Case) -> int:
    return sum(1 for m in case.mock_entries if m.decision is None)


def _accepted_query_count(case: Case) -> int:
    return sum(1 for cp in case.cutpoints if cp.enabled for q in cp.queries if q.decision == "accept")


def advance_step(db: Session, case: Case, target_step: str, actor: User) -> Case:
    if target_step not in WORKSHOP_STEPS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"未知步骤：{target_step}")

    current_idx = WORKSHOP_STEPS.index(case.current_step)
    target_idx = WORKSHOP_STEPS.index(target_step)
    if target_idx > current_idx + 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能跳过中间步骤")

    if target_step == "b":
        if pending_flag_count(case) > 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "还有核对冲突未裁定，不能进入下一步")

    elif target_step == "d":
        if len(case.stage_map) < 6:  # 业务方真实六阶段旅程，不再是发明出来的 8 阶段
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "请先运行阶段映射（Agent B）")
        if not case.persona_fields:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "请先运行组合抽取（Agent C）")
        if _pending_boundary_count(case) > 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "还有边界判断未裁定，不能进入下一步")

    elif target_step == "f":
        # 推测抽查（Agent D）不是必经步骤——存在真实缺口时系统会建议跑一次，
        # 但用户可以直接跳过，不强制要求 mock_entries 必须存在。已经生成的
        # 推测条目仍然必须被逐条裁定，不能悬而不决地带进下一步。
        if _pending_mock_count(case) > 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "还有推测条目未抽查，不能进入下一步")

    elif target_step == "out":
        if _accepted_query_count(case) == 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "还没有纳入任何测试用例（至少需要一条 accept 的 query）")

    case.current_step = target_step
    case.status = _STEP_STATUS.get(target_step, case.status)
    db.commit()
    db.refresh(case)
    return case


def resolve_boundary(db: Session, case: Case, decision_id: uuid.UUID, resolved_stage: str, actor: User) -> BoundaryDecision:
    bd = next((b for b in case.boundary_decisions if b.id == decision_id), None)
    if bd is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该边界判断不存在")
    if resolved_stage not in (bd.assigned_stage, bd.alternative_stage):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "只能在系统给出的两个选项之间选择")

    if resolved_stage != bd.assigned_stage:
        from_stage = next((s for s in case.stage_map if s.stage_code == bd.assigned_stage), None)
        to_stage = next((s for s in case.stage_map if s.stage_code == resolved_stage), None)
        if from_stage and bd.doc_seq in from_stage.docs:
            from_stage.docs = [d for d in from_stage.docs if d != bd.doc_seq]
        if to_stage and bd.doc_seq not in to_stage.docs:
            to_stage.docs = [*to_stage.docs, bd.doc_seq]

    bd.resolved_stage = resolved_stage
    bd.resolved_by = actor.id
    bd.resolved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(bd)
    return bd


def decide_mock(db: Session, case: Case, mock_id: uuid.UUID, decision: str, actor: User) -> MockEntry:
    mock = next((m for m in case.mock_entries if m.id == mock_id), None)
    if mock is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该推测条目不存在")
    mock.decision = decision
    mock.decided_by = actor.id
    mock.decided_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(mock)
    return mock


def toggle_cutpoint(db: Session, case: Case, cutpoint_id: uuid.UUID, enabled: bool) -> Cutpoint:
    cp = next((c for c in case.cutpoints if c.id == cutpoint_id), None)
    if cp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该裂点不存在")
    cp.enabled = enabled
    db.commit()
    db.refresh(cp)
    return cp


def decide_query(db: Session, case: Case, query_id: uuid.UUID, decision: str, actor: User, reason: str | None = None) -> Query:
    q = next((q for cp in case.cutpoints for q in cp.queries if q.id == query_id), None)
    if q is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该测试用例不存在")
    q.decision = decision
    q.reject_reason = reason if decision == "reject" else None
    q.decided_by = actor.id
    q.decided_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(q)
    return q


def select_variant(db: Session, case: Case, variant_id: uuid.UUID, selected: bool) -> QueryVariant:
    """人工从 F 生成的 4 套候选画像脚本里挑一套（或几套）作为这条用例实际
    要跑的对话——不选也没关系，导出时会把全部候选一起带出去。"""
    variant = next(
        (v for cp in case.cutpoints for q in cp.queries for v in q.variants if v.id == variant_id),
        None,
    )
    if variant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该画像脚本不存在")
    variant.selected = selected
    db.commit()
    db.refresh(variant)
    return variant


def build_query_export_dict(case: Case, cp: Cutpoint, q: Query, scenario_name: str | None = None) -> dict:
    """One query → one export row's worth of data. Shared by the per-case
    「产出」步骤 export and the board's cross-case bulk export so the two
    surfaces never drift into slightly different shapes for the same thing.

    自 811 方案落地后，"用例"不再只是一句话摘要：真正喂给待测试产品的是
    test_direction/test_background（背景仅供评分参考，绝不进入 query 原文）、
    一份精确到 seq 的图片清单，以及（如果人工已经挑选）某一套画像脚本的完整
    多轮对话。导出时把「已挑选」的 variant 摊平出来，方便跑测方直接取用；
    如果人工还没挑，就把全部候选画像一并带出，留给跑测方自己选。"""
    doc_by_seq = {d.seq: d for d in case.documents}
    variants = q.variants
    selected = [v for v in variants if v.selected] or variants
    return {
        "case_no": case.case_no,
        "cutpoint_id": str(cp.id),
        "journey_stage": cp.stage_code,
        "cutpoint_type": cp.type_code,
        "provenance": cp.provenance,
        "anchor": cp.anchor,
        "known_set": cp.known_set,
        "unknown_set": cp.unknown_set,
        "tested_judgment": cp.judgment,
        "scenario_type": q.scenario_type,
        "scenario_name": scenario_name,
        "query": q.text,
        "test_direction": q.test_direction,
        "test_background": q.test_background,
        "test_images": [
            {
                "seq": seq,
                "document_type": doc_by_seq[seq].document_type if seq in doc_by_seq else None,
            }
            for seq in q.test_image_seqs
        ],
        "test_image_note": q.test_image_note,
        "expected_answer_points": q.expected_answer_points,
        "red_line_watch": q.red_line_watch,
        "has_standard_card": q.has_standard_card,
        "persona_variants": [
            {
                "persona_code": v.persona_code,
                "persona_name": v.persona_name,
                "persona_note": v.persona_note,
                "turns": v.turns,
                "behavior_logic": v.behavior_logic,
                "selected": v.selected,
            }
            for v in selected
        ],
    }


def export_accepted_queries(db: Session, case: Case) -> list[dict]:
    """页面一「产出」步骤的导出内容——只含人工纳入的 query，字段形状对齐
    看板（阶段四）将要消费的格式，提前对齐好省得那边再转一遍。"""
    scenario_names = {s.code: s.name for s in db.query(ScenarioType).all()}
    out = []
    for cp in case.cutpoints:
        if not cp.enabled:
            continue
        for q in cp.queries:
            if q.decision != "accept":
                continue
            out.append(build_query_export_dict(case, cp, q, scenario_names.get(q.scenario_type)))
    return out

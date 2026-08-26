"""Cross-case aggregation queries — page 3's whole reason to exist. Page 1
(workshop) and page 2 (prompt console) only ever look at one case or one
agent at a time; this is the only place that asks "across everything we've
processed, where are we".
"""
import uuid
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.db.models.agent import ScenarioType
from app.db.models.case import Case, Cutpoint, MockEntry, PipelineRun, Query, ReviewFlag
from app.db.models.user import User
from app.schemas.board import BoardCaseItem, BoardTestCaseItem, CoverageCell, QualitySummary
from app.services.audit_service import write_audit
from app.services.case_service import build_query_export_dict


def list_board_cases(db: Session) -> list[BoardCaseItem]:
    cases = db.query(Case).order_by(Case.updated_at.desc()).all()
    out = []
    for c in cases:
        item = BoardCaseItem.model_validate(c)
        item.pending_flag_count = sum(1 for f in c.review_flags if f.decision is None)
        item.accepted_query_count = sum(1 for cp in c.cutpoints if cp.enabled for q in cp.queries if q.decision == "accept")
        out.append(item)
    return out


def list_test_cases(
    db: Session,
    *,
    scenario_type: str | None = None,
    cutpoint_type: str | None = None,
    journey_stage: str | None = None,
    provenance: str | None = None,
    decision: str | None = None,
) -> list[BoardTestCaseItem]:
    q = (
        db.query(Query, Cutpoint, Case)
        .join(Cutpoint, Query.cutpoint_id == Cutpoint.id)
        .join(Case, Cutpoint.case_id == Case.id)
    )
    if scenario_type:
        q = q.filter(Query.scenario_type == scenario_type)
    if cutpoint_type:
        q = q.filter(Cutpoint.type_code == cutpoint_type)
    if journey_stage:
        q = q.filter(Cutpoint.stage_code == journey_stage)
    if provenance:
        q = q.filter(Cutpoint.provenance == provenance)
    if decision:
        q = q.filter(Query.decision == decision)

    rows = q.order_by(Case.case_no, Cutpoint.stage_code).all()
    scenario_names = {s.code: s.name for s in db.query(ScenarioType).all()}
    return [
        BoardTestCaseItem(
            case_id=case.id,
            case_no=case.case_no,
            cutpoint_id=cp.id,
            query_id=query.id,
            journey_stage=cp.stage_code,
            cutpoint_type=cp.type_code,
            provenance=cp.provenance,
            scenario_type=query.scenario_type,
            scenario_name=scenario_names.get(query.scenario_type),
            query_text=query.text,
            decision=query.decision,
            reject_reason=query.reject_reason,
            decided_by=query.decided_by,
            decided_at=query.decided_at,
        )
        for query, cp, case in rows
    ]


def batch_decide_queries(
    db: Session, query_ids: list[uuid.UUID], decision: str, actor: User, reason: str | None = None,
) -> int:
    """P1《交互体验优化需求》"用例审核支持批量操作"——用例库筛选出一批
    query 后一次性纳入/不纳入，不用逐条点。`reason` 只在批量"不纳入"时
    有意义，纳入的行一律清空（跟单条 decide_query 的语义保持一致）。
    写一条 AuditLog：批量操作影响面比单条操作大，值得留痕，且 audit
    记录里带上具体是哪些 query_id，方便事后排查"为什么这条被标了不纳入"。
    """
    if decision not in ("accept", "reject"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"不支持的决策：{decision}")
    if not query_ids:
        return 0

    rows = db.query(Query).filter(Query.id.in_(query_ids)).all()
    now = datetime.now(timezone.utc)
    for q in rows:
        q.decision = decision
        q.reject_reason = reason if decision == "reject" else None
        q.decided_by = actor.id
        q.decided_at = now
    db.commit()

    write_audit(
        db, actor=actor, action="query.batch_decide", entity_type="query",
        after={
            "decision": decision, "reason": reason,
            "query_count": len(rows),
            "query_ids": [str(q.id) for q in rows],
        },
    )
    return len(rows)


def export_query_rows(
    db: Session,
    case_ids: list[uuid.UUID] | None = None,
    *,
    scenario_type: str | None = None,
    cutpoint_type: str | None = None,
    journey_stage: str | None = None,
    provenance: str | None = None,
    decision: str | None = None,
) -> list[tuple[Query, Cutpoint, Case]]:
    """The raw ORM rows behind every export format (JSON/Excel/zip) — one
    query builder, three renderers (`export_test_cases` below turns this
    into dicts for JSON/Excel; `export_zip.build_test_case_zip` walks the
    same rows to pull real image bytes and standard-card content, which a
    flat dict can't carry). Filters are identical to /board/testcases —
    export what the table shows, not a separately-decided subset."""
    q = (
        db.query(Query, Cutpoint, Case)
        .join(Cutpoint, Query.cutpoint_id == Cutpoint.id)
        .join(Case, Cutpoint.case_id == Case.id)
        .filter(Cutpoint.enabled.is_(True))
    )
    if case_ids:
        q = q.filter(Case.id.in_(case_ids))
    if scenario_type:
        q = q.filter(Query.scenario_type == scenario_type)
    if cutpoint_type:
        q = q.filter(Cutpoint.type_code == cutpoint_type)
    if journey_stage:
        q = q.filter(Cutpoint.stage_code == journey_stage)
    if provenance:
        q = q.filter(Cutpoint.provenance == provenance)
    if decision:
        q = q.filter(Query.decision == decision)

    return q.order_by(Case.case_no, Cutpoint.stage_code).all()


def export_test_cases(
    db: Session,
    case_ids: list[uuid.UUID] | None = None,
    *,
    scenario_type: str | None = None,
    cutpoint_type: str | None = None,
    journey_stage: str | None = None,
    provenance: str | None = None,
    decision: str | None = None,
) -> list[dict]:
    """看板的跨病例批量导出（JSON/Excel 用这个）——病例看板里勾选几个
    病例导出，或者用例库 tab 里"导出当前筛选结果"，两条路径都走这一个
    函数。跟单病例的「产出」步骤共用同一个 per-query 字典构造
    （build_query_export_dict）。"未选 decision 时该不该默认只要 accept"
    这个策略判断留给调用方（router 层）：病例看板批量导出没有 decision
    选择器，该默认只要 accept；用例库 tab 有筛选下拉，未选等于表格本来
    就在显示 accept+reject，不该在这里偷偷收窄。"""
    rows = export_query_rows(
        db, case_ids,
        scenario_type=scenario_type, cutpoint_type=cutpoint_type,
        journey_stage=journey_stage, provenance=provenance, decision=decision,
    )
    scenario_names = {s.code: s.name for s in db.query(ScenarioType).all()}
    return [build_query_export_dict(case, cp, query, scenario_names.get(query.scenario_type)) for query, cp, case in rows]


def coverage_matrix(db: Session) -> list[CoverageCell]:
    """一行 = 业务方 49 个真实场景之一，按它所属的六阶段旅程分组——场景库
    现在用的是业务方真实的六阶段标签（不再是 C1-C6 那种发明出来的分类，
    见 import_scenario_standards.py），所以这里不再是"裂点类型 × 场景
    类型"的人造网格，而是"这个真实场景，实际有多少条已纳入的真实证据
    用例 / 推测用例"，包含目前还是 0 的场景——这才是"空白格是下一批病例
    该往哪个方向找的信号"这句话原本想表达的东西。"""
    scenarios = db.query(ScenarioType).filter(ScenarioType.active.is_(True)).order_by(ScenarioType.scenario_number).all()

    rows = (
        db.query(Query.scenario_type, Cutpoint.provenance)
        .join(Cutpoint, Query.cutpoint_id == Cutpoint.id)
        .filter(Cutpoint.enabled.is_(True), Query.decision == "accept")
        .all()
    )
    counts: dict[str, dict[str, int]] = defaultdict(lambda: {"real": 0, "mock": 0})
    for scenario_type, provenance in rows:
        counts[scenario_type][provenance if provenance in ("real", "mock") else "real"] += 1

    out = []
    for s in scenarios:
        stage = s.journey_stages[0] if s.journey_stages else "?"
        c = counts.get(s.code, {"real": 0, "mock": 0})
        out.append(
            CoverageCell(
                journey_stage=stage,
                scenario_type=s.code,
                scenario_name=s.name,
                accepted_real=c["real"],
                accepted_mock=c["mock"],
            )
        )
    return out


def quality_summary(db: Session) -> QualitySummary:
    case_count = db.query(Case).count()

    flags = db.query(ReviewFlag).all()
    flags_by_severity: dict[str, int] = defaultdict(int)
    flags_confirmed = flags_ignored = 0
    for f in flags:
        flags_by_severity[f.severity] += 1
        if f.decision == "confirm":
            flags_confirmed += 1
        elif f.decision == "ignore":
            flags_ignored += 1

    mocks = db.query(MockEntry).all()
    mocks_passed = sum(1 for m in mocks if m.decision == "pass")
    mocks_rejected = sum(1 for m in mocks if m.decision == "reject")

    runs = db.query(PipelineRun).all()
    failures_by_agent: dict[str, int] = defaultdict(int)
    for r in runs:
        if r.status == "failed":
            failures_by_agent[r.agent_code] += 1

    accepted = (
        db.query(Query)
        .join(Cutpoint, Query.cutpoint_id == Cutpoint.id)
        .filter(Cutpoint.enabled.is_(True), Query.decision == "accept")
        .count()
    )

    token_usage_total = 0
    token_usage_run_count = 0
    token_usage_by_provider: dict[str, int] = defaultdict(int)
    token_usage_by_agent: dict[str, int] = defaultdict(int)
    for r in runs:
        if not r.token_usage:
            continue
        total = r.token_usage.get("total_tokens")
        if total is None:
            continue
        token_usage_total += total
        token_usage_run_count += 1
        token_usage_by_provider[r.token_usage.get("provider") or "unknown"] += total
        token_usage_by_agent[r.agent_code] += total

    return QualitySummary(
        case_count=case_count,
        flags_total=len(flags),
        flags_by_severity=dict(flags_by_severity),
        flags_confirmed=flags_confirmed,
        flags_ignored=flags_ignored,
        mocks_total=len(mocks),
        mocks_passed=mocks_passed,
        mocks_rejected=mocks_rejected,
        pipeline_runs_total=len(runs),
        pipeline_runs_failed=sum(1 for r in runs if r.status == "failed"),
        pipeline_failures_by_agent=dict(failures_by_agent),
        accepted_test_case_count=accepted,
        token_usage_total=token_usage_total,
        token_usage_run_count=token_usage_run_count,
        token_usage_by_provider=dict(token_usage_by_provider),
        token_usage_by_agent=dict(token_usage_by_agent),
    )

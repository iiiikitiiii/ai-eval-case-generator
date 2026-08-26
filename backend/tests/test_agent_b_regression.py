"""Agent B regression net, exercising `pipeline.framework.UnifiedAgentRunner`
(阶段 3 of doc/Agent统一架构改造方案.md). Covers: 成功落库（幂等重跑覆盖
旧数据）/ 模型漏字段 / 无效引用（越界 doc seq、非法阶段代码）/ 缺阶段
覆盖 / LLM 异常 / 运行状态最终收口.
"""
import httpx
import pytest

from app.db.models.case import BoundaryDecision, CaseStatus, StageMap
from app.services.llm_client import LLMStructuredError
from app.services.pipeline import agent_b
from app.services.pipeline.common import PipelineError

from pipeline_fixtures import fake_run_structured, make_case, make_published_version, make_run, sequenced_run_structured

_FULL_STAGE_MAP = {code: {"status": "covered", "docs": [1], "reason": None} for code in agent_b.STAGE_CODES}
_VALID_RESULT = {"stage_map": _FULL_STAGE_MAP, "boundary_decisions": [{"doc": 1, "assigned": "J01", "alternative": "J02", "rule_applied": "R1", "rationale": "边界文档", "needs_human": True}]}


@pytest.fixture(autouse=True)
def _instant_sleep(monkeypatch):
    async def _noop(*args, **kwargs):
        return None
    monkeypatch.setattr("asyncio.sleep", _noop)


@pytest.mark.anyio
async def test_success_persists_stage_map_and_boundary_decisions(db_session, monkeypatch):
    case = make_case(db_session, n_documents=1)
    make_published_version(db_session, "B")
    run = make_run(db_session, case, "B")
    monkeypatch.setattr("app.services.pipeline.framework.run_structured", fake_run_structured(_VALID_RESULT))

    await agent_b.run_agent_b(db_session, case, run)

    db_session.refresh(run)
    stage_rows = db_session.query(StageMap).filter(StageMap.case_id == case.id).all()
    boundary_rows = db_session.query(BoundaryDecision).filter(BoundaryDecision.case_id == case.id).all()
    assert run.status == "succeeded"
    assert len(stage_rows) == 6
    assert {r.stage_code for r in stage_rows} == set(agent_b.STAGE_CODES)
    assert len(boundary_rows) == 1
    assert boundary_rows[0].assigned_stage == "J01"


@pytest.mark.anyio
async def test_rerun_replaces_old_stage_map_not_merges(db_session, monkeypatch):
    """幂等重跑：旧的 stage_map/boundary_decisions 被整体替换，不是累加。"""
    case = make_case(db_session, n_documents=1)
    make_published_version(db_session, "B")

    run1 = make_run(db_session, case, "B")
    monkeypatch.setattr("app.services.pipeline.framework.run_structured", fake_run_structured({"stage_map": _FULL_STAGE_MAP, "boundary_decisions": []}))
    await agent_b.run_agent_b(db_session, case, run1)
    first_ids = {r.id for r in db_session.query(StageMap).filter(StageMap.case_id == case.id).all()}
    assert len(first_ids) == 6

    run2 = make_run(db_session, case, "B")
    changed_map = {code: {"status": "real_gap", "docs": [], "reason": "重跑"} for code in agent_b.STAGE_CODES}
    monkeypatch.setattr("app.services.pipeline.framework.run_structured", fake_run_structured({"stage_map": changed_map, "boundary_decisions": []}))
    await agent_b.run_agent_b(db_session, case, run2)

    rows = db_session.query(StageMap).filter(StageMap.case_id == case.id).all()
    assert len(rows) == 6  # 不是 12——旧的被删了，不是叠加
    assert all(r.status == "real_gap" for r in rows)
    assert first_ids.isdisjoint({r.id for r in rows})  # 全新的行，不是复用旧 id


@pytest.mark.anyio
async def test_missing_stage_coverage_triggers_repair_then_succeeds(db_session, monkeypatch):
    case = make_case(db_session, n_documents=1)
    make_published_version(db_session, "B")
    run = make_run(db_session, case, "B")

    incomplete = {code: {"status": "covered"} for code in agent_b.STAGE_CODES[:-1]}  # 缺 J06
    monkeypatch.setattr("app.services.pipeline.framework.run_structured", sequenced_run_structured({"stage_map": incomplete, "boundary_decisions": []}, _VALID_RESULT))

    await agent_b.run_agent_b(db_session, case, run)
    db_session.refresh(run)
    assert run.status == "succeeded"
    assert run.output_ref["repair_count"] == 1


@pytest.mark.anyio
async def test_missing_stage_coverage_repair_exhausted_fails(db_session, monkeypatch):
    case = make_case(db_session, n_documents=1)
    make_published_version(db_session, "B")
    run = make_run(db_session, case, "B")

    incomplete = {code: {"status": "covered"} for code in agent_b.STAGE_CODES[:-1]}
    monkeypatch.setattr("app.services.pipeline.framework.run_structured", sequenced_run_structured({"stage_map": incomplete, "boundary_decisions": []}, {"stage_map": incomplete, "boundary_decisions": []}))

    with pytest.raises(PipelineError, match="J06"):
        await agent_b.run_agent_b(db_session, case, run)
    db_session.refresh(run)
    assert run.status == "failed"


@pytest.mark.anyio
async def test_boundary_decision_invalid_doc_ref_triggers_repair_then_succeeds(db_session, monkeypatch):
    case = make_case(db_session, n_documents=1)  # 只有 seq=1
    make_published_version(db_session, "B")
    run = make_run(db_session, case, "B")

    bad = {"stage_map": _FULL_STAGE_MAP, "boundary_decisions": [{"doc": 99, "assigned": "J01", "alternative": "J02"}]}
    monkeypatch.setattr("app.services.pipeline.framework.run_structured", sequenced_run_structured(bad, _VALID_RESULT))

    await agent_b.run_agent_b(db_session, case, run)
    db_session.refresh(run)
    assert run.status == "succeeded"
    assert run.output_ref["repair_count"] == 1


@pytest.mark.anyio
async def test_boundary_decision_invalid_stage_code_repair_exhausted_fails(db_session, monkeypatch):
    case = make_case(db_session, n_documents=1)
    make_published_version(db_session, "B")
    run = make_run(db_session, case, "B")

    bad = {"stage_map": _FULL_STAGE_MAP, "boundary_decisions": [{"doc": 1, "assigned": "J99", "alternative": "J02"}]}
    monkeypatch.setattr("app.services.pipeline.framework.run_structured", sequenced_run_structured(bad, bad))

    with pytest.raises(PipelineError, match="阶段代码不合法"):
        await agent_b.run_agent_b(db_session, case, run)
    db_session.refresh(run)
    assert run.status == "failed"
    assert db_session.query(BoundaryDecision).filter(BoundaryDecision.case_id == case.id).count() == 0


@pytest.mark.anyio
async def test_llm_exception_triggers_repair_then_succeeds(db_session, monkeypatch):
    case = make_case(db_session, n_documents=1)
    make_published_version(db_session, "B")
    run = make_run(db_session, case, "B")

    monkeypatch.setattr("app.services.pipeline.framework.run_structured", sequenced_run_structured(LLMStructuredError("模拟：Kimi 返回截断"), _VALID_RESULT))

    await agent_b.run_agent_b(db_session, case, run)
    db_session.refresh(run)
    assert run.status == "succeeded"


@pytest.mark.anyio
async def test_transient_network_error_retries_then_succeeds(db_session, monkeypatch):
    case = make_case(db_session, n_documents=1)
    make_published_version(db_session, "B")
    run = make_run(db_session, case, "B")

    monkeypatch.setattr("app.services.pipeline.framework.run_structured", sequenced_run_structured(httpx.ConnectError("连接失败"), _VALID_RESULT))

    await agent_b.run_agent_b(db_session, case, run)
    db_session.refresh(run)
    assert run.status == "succeeded"
    assert run.output_ref["repair_count"] == 0


@pytest.mark.anyio
async def test_no_documents_fails_without_calling_the_model(db_session, monkeypatch):
    case = make_case(db_session, n_documents=0)
    make_published_version(db_session, "B")
    run = make_run(db_session, case, "B")
    called = {"n": 0}

    async def _should_not_be_called(**kwargs):
        called["n"] += 1
        return {}

    monkeypatch.setattr("app.services.pipeline.framework.run_structured", _should_not_be_called)

    with pytest.raises(PipelineError, match="还没有抽取出任何单据"):
        await agent_b.run_agent_b(db_session, case, run)
    assert called["n"] == 0


@pytest.mark.anyio
async def test_no_published_version_fails_without_calling_the_model(db_session, monkeypatch):
    from app.db.models.agent import Agent, AgentVersion
    agent = db_session.query(Agent).filter(Agent.code == "B").first()
    db_session.query(AgentVersion).filter(AgentVersion.agent_id == agent.id, AgentVersion.status == "published").update({"status": "archived"})
    db_session.commit()

    case = make_case(db_session, n_documents=1)
    run = make_run(db_session, case, "B")
    called = {"n": 0}

    async def _should_not_be_called(**kwargs):
        called["n"] += 1
        return {}

    monkeypatch.setattr("app.services.pipeline.framework.run_structured", _should_not_be_called)

    with pytest.raises(PipelineError, match="没有已发布的版本"):
        await agent_b.run_agent_b(db_session, case, run)
    assert called["n"] == 0


@pytest.mark.anyio
async def test_run_status_never_left_queued_or_running(db_session, monkeypatch):
    case = make_case(db_session, n_documents=1)
    make_published_version(db_session, "B")
    run = make_run(db_session, case, "B")
    assert run.status == "queued"

    monkeypatch.setattr("app.services.pipeline.framework.run_structured", sequenced_run_structured(RuntimeError("随便什么异常")))

    with pytest.raises(RuntimeError):
        await agent_b.run_agent_b(db_session, case, run)

    db_session.refresh(run)
    assert run.status == "failed"
    assert run.started_at is not None
    assert run.finished_at is not None

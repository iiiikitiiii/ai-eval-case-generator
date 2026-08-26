"""Agent D regression net, exercising `pipeline.framework.UnifiedAgentRunner`
(阶段 4 of doc/Agent统一架构改造方案.md). Two things get their own
dedicated tests beyond the usual pattern: the "skip the LLM call" shortcut
when there's nothing to backfill (`AgentRequest.precomputed_result`), and
D's core red line — never persist content for a non-real_gap stage, even
after a repair attempt.
"""
import uuid

import httpx
import pytest

from app.db.models.case import CaseStatus, MockEntry, StageMap
from app.services.llm_client import LLMStructuredError
from app.services.pipeline import agent_d
from app.services.pipeline.common import PipelineError

from pipeline_fixtures import fake_run_structured, make_case, make_published_version, make_run, sequenced_run_structured


def _add_stage_map(db_session, case, stages: dict[str, str]) -> None:
    for code, status in stages.items():
        db_session.add(StageMap(id=uuid.uuid4(), case_id=case.id, stage_code=code, status=status, docs=[]))
    db_session.commit()
    db_session.refresh(case)


_VALID_ENTRY = {"journey_stage": "J02", "date": "约2026年", "title": "随访", "desc": "推测的随访记录", "clinical_basis": "基于治疗常规", "strength": "medium", "disclaimer": "推测数据"}


@pytest.fixture(autouse=True)
def _instant_sleep(monkeypatch):
    async def _noop(*args, **kwargs):
        return None
    monkeypatch.setattr("asyncio.sleep", _noop)


@pytest.mark.anyio
async def test_success_persists_mock_entries_for_real_gap_only(db_session, monkeypatch):
    case = make_case(db_session, n_documents=1)
    _add_stage_map(db_session, case, {"J01": "covered", "J02": "real_gap"})
    make_published_version(db_session, "D")
    run = make_run(db_session, case, "D")
    monkeypatch.setattr("app.services.pipeline.framework.run_structured", fake_run_structured({"mock_entries": [_VALID_ENTRY]}))

    await agent_d.run_agent_d(db_session, case, run)

    db_session.refresh(run)
    entries = db_session.query(MockEntry).filter(MockEntry.case_id == case.id).all()
    assert run.status == "succeeded"
    assert len(entries) == 1
    assert entries[0].stage_code == "J02"
    assert entries[0].title == "随访"


@pytest.mark.anyio
async def test_no_real_gap_skips_llm_call_and_succeeds(db_session, monkeypatch):
    case = make_case(db_session, n_documents=1)
    _add_stage_map(db_session, case, {"J01": "covered", "J02": "uncovered"})
    make_published_version(db_session, "D")
    run = make_run(db_session, case, "D")
    called = {"n": 0}

    async def _should_not_be_called(**kwargs):
        called["n"] += 1
        return {}

    monkeypatch.setattr("app.services.pipeline.framework.run_structured", _should_not_be_called)

    await agent_d.run_agent_d(db_session, case, run)

    assert called["n"] == 0  # 结构性答案已知（没有 real_gap），不该花一次 LLM 调用去问一个空数组
    db_session.refresh(run)
    assert run.status == "succeeded"
    assert run.output_ref["mock_count"] == 0


@pytest.mark.anyio
async def test_no_real_gap_still_passes_through_validate(db_session, monkeypatch):
    """跳过 LLM 调用不等于跳过校验——precomputed_result 一样要过
    validate()，只是这里 mock_entries 恒为空，天然通过。"""
    case = make_case(db_session, n_documents=1)
    _add_stage_map(db_session, case, {"J01": "covered"})
    make_published_version(db_session, "D")
    run = make_run(db_session, case, "D")

    await agent_d.run_agent_d(db_session, case, run)

    db_session.refresh(run)
    assert run.status == "succeeded"
    assert run.output_ref["attempt_count"] == 1
    assert run.output_ref["attempts"] == [{"kind": "skipped_llm_call"}]


@pytest.mark.anyio
async def test_rerun_replaces_old_mock_entries(db_session, monkeypatch):
    case = make_case(db_session, n_documents=1)
    _add_stage_map(db_session, case, {"J01": "real_gap"})
    make_published_version(db_session, "D")

    run1 = make_run(db_session, case, "D")
    monkeypatch.setattr("app.services.pipeline.framework.run_structured", fake_run_structured({"mock_entries": [{**_VALID_ENTRY, "journey_stage": "J01"}]}))
    await agent_d.run_agent_d(db_session, case, run1)
    assert db_session.query(MockEntry).filter(MockEntry.case_id == case.id).count() == 1

    run2 = make_run(db_session, case, "D")
    monkeypatch.setattr("app.services.pipeline.framework.run_structured", fake_run_structured({"mock_entries": []}))
    await agent_d.run_agent_d(db_session, case, run2)

    assert db_session.query(MockEntry).filter(MockEntry.case_id == case.id).count() == 0


@pytest.mark.anyio
async def test_missing_field_triggers_repair_then_succeeds(db_session, monkeypatch):
    case = make_case(db_session, n_documents=1)
    _add_stage_map(db_session, case, {"J01": "real_gap"})
    make_published_version(db_session, "D")
    run = make_run(db_session, case, "D")

    bad = {"mock_entries": [{"journey_stage": "J01", "title": "a"}]}  # 缺 clinical_basis/strength
    good = {"mock_entries": [{**_VALID_ENTRY, "journey_stage": "J01"}]}
    monkeypatch.setattr("app.services.pipeline.framework.run_structured", sequenced_run_structured(bad, good))

    await agent_d.run_agent_d(db_session, case, run)
    db_session.refresh(run)
    assert run.status == "succeeded"
    assert run.output_ref["repair_count"] == 1


@pytest.mark.anyio
async def test_fabricated_non_real_gap_content_triggers_repair_then_succeeds(db_session, monkeypatch):
    """模型第一次越界为 uncovered 阶段编造内容——不是立刻失败，给一次
    修复机会，第二次改对了（只保留 real_gap 阶段的条目）就成功。"""
    case = make_case(db_session, n_documents=1)
    _add_stage_map(db_session, case, {"J01": "real_gap", "J02": "uncovered"})
    make_published_version(db_session, "D")
    run = make_run(db_session, case, "D")

    bad = {"mock_entries": [{**_VALID_ENTRY, "journey_stage": "J01"}, {**_VALID_ENTRY, "journey_stage": "J02", "title": "越界编造"}]}
    good = {"mock_entries": [{**_VALID_ENTRY, "journey_stage": "J01"}]}
    monkeypatch.setattr("app.services.pipeline.framework.run_structured", sequenced_run_structured(bad, good))

    await agent_d.run_agent_d(db_session, case, run)

    db_session.refresh(run)
    assert run.status == "succeeded"
    assert run.output_ref["repair_count"] == 1
    entries = db_session.query(MockEntry).filter(MockEntry.case_id == case.id).all()
    assert len(entries) == 1
    assert entries[0].stage_code == "J01"


@pytest.mark.anyio
async def test_fabricated_non_real_gap_content_repair_exhausted_fails_with_zero_persisted(db_session, monkeypatch):
    """核心红线的真正验收：修复耗尽后，一条越界内容都不会落库——不是
    "留下合法的那条、丢弃越界的那条"，是整条运行失败、全部不落库。"""
    case = make_case(db_session, n_documents=1)
    _add_stage_map(db_session, case, {"J01": "real_gap", "J02": "uncovered"})
    make_published_version(db_session, "D")
    run = make_run(db_session, case, "D")

    bad = {"mock_entries": [{**_VALID_ENTRY, "journey_stage": "J01"}, {**_VALID_ENTRY, "journey_stage": "J02", "title": "越界编造"}]}
    monkeypatch.setattr("app.services.pipeline.framework.run_structured", sequenced_run_structured(bad, bad))

    with pytest.raises(PipelineError, match="非 real_gap 阶段编造"):
        await agent_d.run_agent_d(db_session, case, run)

    db_session.refresh(run)
    db_session.refresh(case)
    assert run.status == "failed"
    assert case.status == CaseStatus.blocked.value
    assert db_session.query(MockEntry).filter(MockEntry.case_id == case.id).count() == 0


@pytest.mark.anyio
async def test_llm_exception_triggers_repair_then_succeeds(db_session, monkeypatch):
    case = make_case(db_session, n_documents=1)
    _add_stage_map(db_session, case, {"J01": "real_gap"})
    make_published_version(db_session, "D")
    run = make_run(db_session, case, "D")

    monkeypatch.setattr(
        "app.services.pipeline.framework.run_structured",
        sequenced_run_structured(LLMStructuredError("模拟：LLM 异常"), {"mock_entries": [{**_VALID_ENTRY, "journey_stage": "J01"}]}),
    )

    await agent_d.run_agent_d(db_session, case, run)
    db_session.refresh(run)
    assert run.status == "succeeded"


@pytest.mark.anyio
async def test_transient_network_error_retries_then_succeeds(db_session, monkeypatch):
    case = make_case(db_session, n_documents=1)
    _add_stage_map(db_session, case, {"J01": "real_gap"})
    make_published_version(db_session, "D")
    run = make_run(db_session, case, "D")

    monkeypatch.setattr(
        "app.services.pipeline.framework.run_structured",
        sequenced_run_structured(httpx.ConnectError("连接失败"), {"mock_entries": [{**_VALID_ENTRY, "journey_stage": "J01"}]}),
    )

    await agent_d.run_agent_d(db_session, case, run)
    db_session.refresh(run)
    assert run.status == "succeeded"
    assert run.output_ref["repair_count"] == 0


@pytest.mark.anyio
async def test_no_stage_map_fails_without_calling_the_model(db_session, monkeypatch):
    case = make_case(db_session, n_documents=1)  # 没跑过 B
    make_published_version(db_session, "D")
    run = make_run(db_session, case, "D")
    called = {"n": 0}

    async def _should_not_be_called(**kwargs):
        called["n"] += 1
        return {}

    monkeypatch.setattr("app.services.pipeline.framework.run_structured", _should_not_be_called)

    with pytest.raises(PipelineError, match="先运行 Agent B"):
        await agent_d.run_agent_d(db_session, case, run)
    assert called["n"] == 0


@pytest.mark.anyio
async def test_no_published_version_fails_without_calling_the_model(db_session, monkeypatch):
    from app.db.models.agent import Agent, AgentVersion
    agent = db_session.query(Agent).filter(Agent.code == "D").first()
    db_session.query(AgentVersion).filter(AgentVersion.agent_id == agent.id, AgentVersion.status == "published").update({"status": "archived"})
    db_session.commit()

    case = make_case(db_session, n_documents=1)
    _add_stage_map(db_session, case, {"J01": "real_gap"})
    run = make_run(db_session, case, "D")
    called = {"n": 0}

    async def _should_not_be_called(**kwargs):
        called["n"] += 1
        return {}

    monkeypatch.setattr("app.services.pipeline.framework.run_structured", _should_not_be_called)

    with pytest.raises(PipelineError, match="没有已发布的版本"):
        await agent_d.run_agent_d(db_session, case, run)
    assert called["n"] == 0


@pytest.mark.anyio
async def test_run_status_never_left_queued_or_running(db_session, monkeypatch):
    case = make_case(db_session, n_documents=1)
    _add_stage_map(db_session, case, {"J01": "real_gap"})
    make_published_version(db_session, "D")
    run = make_run(db_session, case, "D")
    assert run.status == "queued"

    monkeypatch.setattr("app.services.pipeline.framework.run_structured", sequenced_run_structured(RuntimeError("随便什么异常")))

    with pytest.raises(RuntimeError):
        await agent_d.run_agent_d(db_session, case, run)

    db_session.refresh(run)
    assert run.status == "failed"
    assert run.started_at is not None
    assert run.finished_at is not None

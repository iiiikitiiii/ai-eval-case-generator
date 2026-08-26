"""Agent C regression net, exercising `pipeline.framework.UnifiedAgentRunner`
(阶段 1 of doc/Agent统一架构改造方案.md — C was migrated first: it doesn't
read images, doesn't touch B's boundary decisions, has the simplest
persist step). Covers the bounded repair loop for domain-validation
failures, the repair loop for unparseable model output, and
transient-network-error retry with backoff.
"""
import httpx
import pytest

from app.db.models.case import CaseStatus, PersonaField
from app.services.llm_client import LLMStructuredError
from app.services.pipeline import agent_c
from app.services.pipeline.common import PipelineError

from pipeline_fixtures import fake_run_structured, make_case, make_published_version, make_run, sequenced_run_structured

_VALID_RESULT = {"persona": [{"field": "diagnosis", "value": "乳腺癌", "source": [1], "flag": None}]}


@pytest.fixture(autouse=True)
def _instant_sleep(monkeypatch):
    """框架在瞬时错误重试之间会 `asyncio.sleep()` 退避——测试不用真的等。"""
    async def _noop(*args, **kwargs):
        return None
    monkeypatch.setattr("asyncio.sleep", _noop)


@pytest.mark.anyio
async def test_success_persists_persona_fields(db_session, monkeypatch):
    case = make_case(db_session, n_documents=1)
    make_published_version(db_session, "C")
    run = make_run(db_session, case, "C")
    monkeypatch.setattr("app.services.pipeline.framework.run_structured", fake_run_structured(_VALID_RESULT))

    await agent_c.run_agent_c(db_session, case, run)

    db_session.refresh(run)
    fields = db_session.query(PersonaField).filter(PersonaField.case_id == case.id).all()
    assert run.status == "succeeded"
    assert len(fields) == 1
    assert fields[0].field == "diagnosis"
    assert run.output_ref["field_count"] == 1


@pytest.mark.anyio
async def test_output_ref_records_attempt_and_repair_counts(db_session, monkeypatch):
    case = make_case(db_session, n_documents=1)
    make_published_version(db_session, "C")
    run = make_run(db_session, case, "C")
    monkeypatch.setattr("app.services.pipeline.framework.run_structured", fake_run_structured(_VALID_RESULT))

    await agent_c.run_agent_c(db_session, case, run)

    db_session.refresh(run)
    assert run.output_ref["attempt_count"] == 1
    assert run.output_ref["repair_count"] == 0
    assert run.output_ref["attempts"] == [{"kind": "success"}]


@pytest.mark.anyio
async def test_invalid_doc_ref_triggers_repair_then_succeeds(db_session, monkeypatch):
    """第一次输出引用了不存在的病历 seq——框架不是立刻放弃，把错误清单
    发回给模型，第二次输出改好了，最终成功。"""
    case = make_case(db_session, n_documents=1)  # 只有 seq=1
    make_published_version(db_session, "C")
    run = make_run(db_session, case, "C")

    bad_result = {"persona": [{"field": "diagnosis", "value": "x", "source": [99]}]}  # 99 不存在
    monkeypatch.setattr("app.services.pipeline.framework.run_structured", sequenced_run_structured(bad_result, _VALID_RESULT))

    await agent_c.run_agent_c(db_session, case, run)

    db_session.refresh(run)
    assert run.status == "succeeded"
    assert run.output_ref["repair_count"] == 1
    assert run.output_ref["attempt_count"] == 2
    fields = db_session.query(PersonaField).filter(PersonaField.case_id == case.id).all()
    assert len(fields) == 1
    assert fields[0].source == [1]


@pytest.mark.anyio
async def test_invalid_doc_ref_repair_exhausted_fails(db_session, monkeypatch):
    case = make_case(db_session, n_documents=1)
    make_published_version(db_session, "C")
    run = make_run(db_session, case, "C")

    bad_result = {"persona": [{"field": "diagnosis", "value": "x", "source": [99]}]}
    # max_repairs=1：两次都坏——第一次触发修复，第二次（修复后）仍然坏，直接失败。
    monkeypatch.setattr("app.services.pipeline.framework.run_structured", sequenced_run_structured(bad_result, bad_result))

    with pytest.raises(PipelineError, match="不存在的病历"):
        await agent_c.run_agent_c(db_session, case, run)

    db_session.refresh(run)
    db_session.refresh(case)
    assert run.status == "failed"
    assert case.status == CaseStatus.blocked.value
    assert db_session.query(PersonaField).filter(PersonaField.case_id == case.id).count() == 0


@pytest.mark.anyio
async def test_unparseable_output_triggers_repair_then_succeeds(db_session, monkeypatch):
    """LLMStructuredError（模型没有调用工具、返回的也不是合法 JSON）走的是
    另一条修复路径——不是领域校验失败，是"根本没拿到可解析结果"，框架
    照样把这次当成一次可修复错误处理。"""
    case = make_case(db_session, n_documents=1)
    make_published_version(db_session, "C")
    run = make_run(db_session, case, "C")

    monkeypatch.setattr(
        "app.services.pipeline.framework.run_structured",
        sequenced_run_structured(LLMStructuredError("模拟：模型没有调用工具"), _VALID_RESULT),
    )

    await agent_c.run_agent_c(db_session, case, run)

    db_session.refresh(run)
    assert run.status == "succeeded"
    assert run.output_ref["repair_count"] == 1


@pytest.mark.anyio
async def test_unparseable_output_repair_exhausted_fails(db_session, monkeypatch):
    case = make_case(db_session, n_documents=1)
    make_published_version(db_session, "C")
    run = make_run(db_session, case, "C")

    monkeypatch.setattr(
        "app.services.pipeline.framework.run_structured",
        sequenced_run_structured(LLMStructuredError("第一次"), LLMStructuredError("第二次")),
    )

    with pytest.raises(PipelineError, match="模型输出解析失败"):
        await agent_c.run_agent_c(db_session, case, run)
    db_session.refresh(run)
    assert run.status == "failed"


@pytest.mark.anyio
async def test_transient_network_error_retries_then_succeeds(db_session, monkeypatch):
    case = make_case(db_session, n_documents=1)
    make_published_version(db_session, "C")
    run = make_run(db_session, case, "C")

    monkeypatch.setattr(
        "app.services.pipeline.framework.run_structured",
        sequenced_run_structured(httpx.ConnectError("连接失败"), httpx.ReadTimeout("读超时"), _VALID_RESULT),
    )

    await agent_c.run_agent_c(db_session, case, run)

    db_session.refresh(run)
    assert run.status == "succeeded"
    # 网络重试不消耗 repair 配额，也不算进 repair_count
    assert run.output_ref["repair_count"] == 0
    assert run.output_ref["attempt_count"] == 3


@pytest.mark.anyio
async def test_transient_network_error_exhausted_fails(db_session, monkeypatch):
    case = make_case(db_session, n_documents=1)
    make_published_version(db_session, "C")
    run = make_run(db_session, case, "C")

    monkeypatch.setattr(
        "app.services.pipeline.framework.run_structured",
        sequenced_run_structured(httpx.ConnectError("1"), httpx.ConnectError("2"), httpx.ConnectError("3")),
    )

    with pytest.raises(PipelineError, match="基础设施错误"):
        await agent_c.run_agent_c(db_session, case, run)
    db_session.refresh(run)
    assert run.status == "failed"


@pytest.mark.anyio
async def test_no_documents_fails_without_calling_the_model(db_session, monkeypatch):
    case = make_case(db_session, n_documents=0)
    make_published_version(db_session, "C")
    run = make_run(db_session, case, "C")
    called = {"n": 0}

    async def _should_not_be_called(**kwargs):
        called["n"] += 1
        return {}

    monkeypatch.setattr("app.services.pipeline.framework.run_structured", _should_not_be_called)

    with pytest.raises(PipelineError, match="还没有抽取出任何单据"):
        await agent_c.run_agent_c(db_session, case, run)
    assert called["n"] == 0


@pytest.mark.anyio
async def test_no_published_version_fails_without_calling_the_model(db_session, monkeypatch):
    from app.db.models.agent import Agent, AgentVersion
    agent = db_session.query(Agent).filter(Agent.code == "C").first()
    db_session.query(AgentVersion).filter(AgentVersion.agent_id == agent.id, AgentVersion.status == "published").update({"status": "archived"})
    db_session.commit()

    case = make_case(db_session, n_documents=1)
    run = make_run(db_session, case, "C")
    called = {"n": 0}

    async def _should_not_be_called(**kwargs):
        called["n"] += 1
        return {}

    monkeypatch.setattr("app.services.pipeline.framework.run_structured", _should_not_be_called)

    with pytest.raises(PipelineError, match="没有已发布的版本"):
        await agent_c.run_agent_c(db_session, case, run)
    assert called["n"] == 0


@pytest.mark.anyio
async def test_run_status_never_left_queued_or_running(db_session, monkeypatch):
    case = make_case(db_session, n_documents=1)
    make_published_version(db_session, "C")
    run = make_run(db_session, case, "C")
    assert run.status == "queued"

    monkeypatch.setattr("app.services.pipeline.framework.run_structured", sequenced_run_structured(RuntimeError("随便什么异常")))

    with pytest.raises(RuntimeError):
        await agent_c.run_agent_c(db_session, case, run)

    db_session.refresh(run)
    assert run.status == "failed"
    assert run.started_at is not None
    assert run.finished_at is not None

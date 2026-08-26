"""Agent A regression net, exercising `pipeline.framework.UnifiedAgentRunner`
(阶段 2 of doc/Agent统一架构改造方案.md). No real LLM or MinIO call —
run_structured and get_object_bytes are both faked. Special attention to
the one thing 阶段 2 explicitly called out as needing verification:
"验证图片字节读取只发生一次，不在修复调用中重复读取/变更输入集合" —
see test_images_read_exactly_once_across_a_repair.
"""
import httpx
import pytest

from app.db.models.case import CaseStatus, ReviewFlag
from app.services.llm_client import LLMStructuredError
from app.services.pipeline import agent_a
from app.services.pipeline.common import PipelineError

from pipeline_fixtures import fake_run_structured, make_case, make_published_version, make_run, sequenced_run_structured

_VALID_RESULT_1DOC = {
    "documents": [{"document_type": "检验报告", "time": {"exam_time": "2026-01-01"}, "exam_items": ["血常规"],
                   "structured_info": {"wbc": "5.0"}, "core_abnormality": None, "ocr_full_text": "...", "confidence": {"ocr": 0.9}}],
    "review_flags": [],
}


def _stub_images(monkeypatch, *, counter: dict | None = None):
    def _fake(key):
        if counter is not None:
            counter["n"] = counter.get("n", 0) + 1
        return b"fake-bytes"
    monkeypatch.setattr(agent_a, "get_object_bytes", _fake)


@pytest.fixture(autouse=True)
def _instant_sleep(monkeypatch):
    async def _noop(*args, **kwargs):
        return None
    monkeypatch.setattr("asyncio.sleep", _noop)


@pytest.mark.anyio
async def test_success_persists_documents_and_flags(db_session, monkeypatch):
    _stub_images(monkeypatch)
    case = make_case(db_session, n_documents=1)
    make_published_version(db_session, "A")
    run = make_run(db_session, case, "A")
    monkeypatch.setattr("app.services.pipeline.framework.run_structured", fake_run_structured(_VALID_RESULT_1DOC))

    await agent_a.run_agent_a(db_session, case, run)

    db_session.refresh(run)
    db_session.refresh(case)
    doc = case.documents[0]
    assert run.status == "succeeded"
    assert doc.document_type == "检验报告"
    assert doc.structured_info == {"wbc": "5.0"}
    assert doc.agent_version_id is not None
    assert case.current_step == "a"
    assert case.status == CaseStatus.reviewing_flags.value
    assert run.output_ref["document_count"] == 1


@pytest.mark.anyio
async def test_images_read_exactly_once_across_a_repair(db_session, monkeypatch):
    """一次运行（哪怕触发了一次修复重试）只读一遍 MinIO，不会因为进了
    修复分支就把图片重新读一遍或换一批。"""
    counter: dict = {}
    _stub_images(monkeypatch, counter=counter)
    case = make_case(db_session, n_documents=2)
    make_published_version(db_session, "A")
    run = make_run(db_session, case, "A")

    wrong_count = {"documents": [_VALID_RESULT_1DOC["documents"][0]], "review_flags": []}  # 只返回 1 份，应该是 2 份
    right_count = {"documents": [_VALID_RESULT_1DOC["documents"][0], _VALID_RESULT_1DOC["documents"][0]], "review_flags": []}
    monkeypatch.setattr("app.services.pipeline.framework.run_structured", sequenced_run_structured(wrong_count, right_count))

    await agent_a.run_agent_a(db_session, case, run)

    db_session.refresh(run)
    assert run.status == "succeeded"
    assert run.output_ref["repair_count"] == 1
    # 两份单据 × 只读一次 = 2 次调用，不是因为修复重试变成 4 次
    assert counter["n"] == 2


@pytest.mark.anyio
async def test_doc_count_mismatch_triggers_repair_then_succeeds(db_session, monkeypatch):
    _stub_images(monkeypatch)
    case = make_case(db_session, n_documents=1)
    make_published_version(db_session, "A")
    run = make_run(db_session, case, "A")

    wrong_count = {"documents": [], "review_flags": []}
    monkeypatch.setattr("app.services.pipeline.framework.run_structured", sequenced_run_structured(wrong_count, _VALID_RESULT_1DOC))

    await agent_a.run_agent_a(db_session, case, run)

    db_session.refresh(run)
    assert run.status == "succeeded"
    assert run.output_ref["repair_count"] == 1


@pytest.mark.anyio
async def test_doc_count_mismatch_repair_exhausted_fails(db_session, monkeypatch):
    _stub_images(monkeypatch)
    case = make_case(db_session, n_documents=1)
    make_published_version(db_session, "A")
    run = make_run(db_session, case, "A")

    wrong_count = {"documents": [], "review_flags": []}
    monkeypatch.setattr("app.services.pipeline.framework.run_structured", sequenced_run_structured(wrong_count, wrong_count))

    with pytest.raises(PipelineError, match="数量必须一一对应"):
        await agent_a.run_agent_a(db_session, case, run)
    db_session.refresh(run)
    db_session.refresh(case)
    assert run.status == "failed"
    assert case.status == CaseStatus.blocked.value


@pytest.mark.anyio
async def test_missing_review_flag_field_triggers_repair_then_succeeds(db_session, monkeypatch):
    _stub_images(monkeypatch)
    case = make_case(db_session, n_documents=1)
    make_published_version(db_session, "A")
    run = make_run(db_session, case, "A")

    bad = {"documents": _VALID_RESULT_1DOC["documents"], "review_flags": [{"type": "冲突", "field": "年龄"}]}  # 缺 detail
    good = {"documents": _VALID_RESULT_1DOC["documents"], "review_flags": [{"type": "冲突", "field": "年龄", "detail": "两份报告年龄不一致"}]}
    monkeypatch.setattr("app.services.pipeline.framework.run_structured", sequenced_run_structured(bad, good))

    await agent_a.run_agent_a(db_session, case, run)

    db_session.refresh(run)
    assert run.status == "succeeded"
    assert run.output_ref["repair_count"] == 1
    flags = db_session.query(ReviewFlag).filter(ReviewFlag.case_id == case.id).all()
    assert len(flags) == 1
    assert flags[0].detail == "两份报告年龄不一致"


@pytest.mark.anyio
async def test_missing_review_flag_field_repair_exhausted_fails(db_session, monkeypatch):
    _stub_images(monkeypatch)
    case = make_case(db_session, n_documents=1)
    make_published_version(db_session, "A")
    run = make_run(db_session, case, "A")

    bad = {"documents": _VALID_RESULT_1DOC["documents"], "review_flags": [{"type": "冲突", "field": "年龄"}]}
    monkeypatch.setattr("app.services.pipeline.framework.run_structured", sequenced_run_structured(bad, bad))

    with pytest.raises(PipelineError, match="detail"):
        await agent_a.run_agent_a(db_session, case, run)
    db_session.refresh(run)
    assert run.status == "failed"
    assert db_session.query(ReviewFlag).filter(ReviewFlag.case_id == case.id).count() == 0


@pytest.mark.anyio
async def test_llm_exception_triggers_repair_then_succeeds(db_session, monkeypatch):
    _stub_images(monkeypatch)
    case = make_case(db_session, n_documents=1)
    make_published_version(db_session, "A")
    run = make_run(db_session, case, "A")

    monkeypatch.setattr(
        "app.services.pipeline.framework.run_structured",
        sequenced_run_structured(LLMStructuredError("模拟：模型没有调用工具"), _VALID_RESULT_1DOC),
    )

    await agent_a.run_agent_a(db_session, case, run)
    db_session.refresh(run)
    assert run.status == "succeeded"
    assert run.output_ref["repair_count"] == 1


@pytest.mark.anyio
async def test_transient_network_error_retries_then_succeeds(db_session, monkeypatch):
    _stub_images(monkeypatch)
    case = make_case(db_session, n_documents=1)
    make_published_version(db_session, "A")
    run = make_run(db_session, case, "A")

    monkeypatch.setattr(
        "app.services.pipeline.framework.run_structured",
        sequenced_run_structured(httpx.ConnectError("连接失败"), _VALID_RESULT_1DOC),
    )

    await agent_a.run_agent_a(db_session, case, run)
    db_session.refresh(run)
    assert run.status == "succeeded"
    assert run.output_ref["repair_count"] == 0


@pytest.mark.anyio
async def test_no_documents_fails_without_calling_the_model(db_session, monkeypatch):
    case = make_case(db_session, n_documents=0)
    make_published_version(db_session, "A")
    run = make_run(db_session, case, "A")
    called = {"n": 0}

    async def _should_not_be_called(**kwargs):
        called["n"] += 1
        return {}

    monkeypatch.setattr("app.services.pipeline.framework.run_structured", _should_not_be_called)

    with pytest.raises(PipelineError, match="还没有上传任何单据"):
        await agent_a.run_agent_a(db_session, case, run)
    assert called["n"] == 0


@pytest.mark.anyio
async def test_no_published_version_fails_without_calling_the_model(db_session, monkeypatch):
    from app.db.models.agent import Agent, AgentVersion
    agent = db_session.query(Agent).filter(Agent.code == "A").first()
    db_session.query(AgentVersion).filter(AgentVersion.agent_id == agent.id, AgentVersion.status == "published").update({"status": "archived"})
    db_session.commit()

    _stub_images(monkeypatch)
    case = make_case(db_session, n_documents=1)
    run = make_run(db_session, case, "A")
    called = {"n": 0}

    async def _should_not_be_called(**kwargs):
        called["n"] += 1
        return {}

    monkeypatch.setattr("app.services.pipeline.framework.run_structured", _should_not_be_called)

    with pytest.raises(PipelineError, match="没有已发布的版本"):
        await agent_a.run_agent_a(db_session, case, run)
    assert called["n"] == 0


@pytest.mark.anyio
async def test_run_status_never_left_queued_or_running(db_session, monkeypatch):
    _stub_images(monkeypatch)
    case = make_case(db_session, n_documents=1)
    make_published_version(db_session, "A")
    run = make_run(db_session, case, "A")
    assert run.status == "queued"

    monkeypatch.setattr("app.services.pipeline.framework.run_structured", sequenced_run_structured(RuntimeError("随便什么异常")))

    with pytest.raises(RuntimeError):
        await agent_a.run_agent_a(db_session, case, run)

    db_session.refresh(run)
    assert run.status == "failed"
    assert run.started_at is not None
    assert run.finished_at is not None

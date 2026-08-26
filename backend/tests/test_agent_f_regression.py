"""Agent F regression net, exercising `pipeline.framework.UnifiedAgentRunner`
(阶段 4 of doc/Agent统一架构改造方案.md). F's three "drop the bad row/
variant silently" behaviors (scenario outside selection, image seq outside
the case, fabricated persona code) are preserved as-is — see the tests
suffixed `_dropped_not_fatal`.
"""
import uuid

import httpx
import pytest

from app.db.models.agent import ScenarioType
from app.db.models.case import CaseStatus, Cutpoint, PersonaField, PipelineRun, Query, QueryVariant, StageMap
from app.services.llm_client import LLMStructuredError
from app.services.pipeline import agent_f
from app.services.pipeline.common import PipelineError

from pipeline_fixtures import fake_run_structured, make_case, make_published_version, make_run, sequenced_run_structured


def _make_scenario(db_session, code: str, active: bool = True) -> ScenarioType:
    s = ScenarioType(id=uuid.uuid4(), code=code, name=f"场景-{code}", axis="patient", journey_stages=["J01"], active=active)
    db_session.add(s)
    db_session.commit()
    return s


def _prep_case(db_session, *, n_documents: int = 1):
    case = make_case(db_session, n_documents=n_documents)
    db_session.add(StageMap(id=uuid.uuid4(), case_id=case.id, stage_code="J01", status="covered", docs=[1]))
    db_session.add(PersonaField(id=uuid.uuid4(), case_id=case.id, field="diagnosis", value="乳腺癌", source=[1]))
    db_session.commit()
    db_session.refresh(case)
    return case


_ONE_CUTPOINT_ROW = {
    "cutpoint_id": "cp1", "journey_stage": "J01", "provenance": "real",
    "anchor": {}, "known_set": [], "unknown_set": [], "tested_judgment": None, "validity_check": {},
    "test_direction": "测试角度", "test_background": "测试背景",
    "expected_answer_points": ["要点1"], "red_line_watch": [],
    "test_image_seqs": [1], "test_image_note": None,
    "persona_variants": [
        {"persona_code": "patient_low", "persona_note": "note", "behavior_logic": "逻辑",
         "turns": [{"round": 1, "messages": ["你好"], "note": None}]},
    ],
}


@pytest.fixture(autouse=True)
def _instant_sleep(monkeypatch):
    async def _noop(*args, **kwargs):
        return None
    monkeypatch.setattr("asyncio.sleep", _noop)


@pytest.mark.anyio
async def test_success_persists_cutpoint_query_and_variant(db_session, monkeypatch):
    case = _prep_case(db_session)
    scenario = _make_scenario(db_session, f"SCNF-{uuid.uuid4().hex[:6]}")
    make_published_version(db_session, "F")
    run = make_run(db_session, case, "F")

    row = {**_ONE_CUTPOINT_ROW, "scenario_type": scenario.code}
    monkeypatch.setattr("app.services.pipeline.framework.run_structured", fake_run_structured({"cutpoints": [row]}))

    await agent_f.run_agent_f(db_session, case, run)

    db_session.refresh(run)
    cps = db_session.query(Cutpoint).filter(Cutpoint.case_id == case.id).all()
    queries = db_session.query(Query).join(Cutpoint).filter(Cutpoint.case_id == case.id).all()
    variants = db_session.query(QueryVariant).filter(QueryVariant.query_id.in_([q.id for q in queries])).all()
    assert run.status == "succeeded"
    assert len(cps) == 1
    assert cps[0].stage_code == "J01"
    assert len(queries) == 1
    assert queries[0].scenario_type == scenario.code
    assert queries[0].test_image_seqs == [1]
    assert len(variants) == 1
    assert variants[0].persona_note == "note"


@pytest.mark.anyio
async def test_rerun_replaces_old_cutpoints(db_session, monkeypatch):
    case = _prep_case(db_session)
    scenario = _make_scenario(db_session, f"SCNF-{uuid.uuid4().hex[:6]}")
    make_published_version(db_session, "F")

    run1 = make_run(db_session, case, "F")
    monkeypatch.setattr("app.services.pipeline.framework.run_structured", fake_run_structured({"cutpoints": [{**_ONE_CUTPOINT_ROW, "scenario_type": scenario.code}]}))
    await agent_f.run_agent_f(db_session, case, run1)
    assert db_session.query(Cutpoint).filter(Cutpoint.case_id == case.id).count() == 1

    run2 = make_run(db_session, case, "F")
    monkeypatch.setattr("app.services.pipeline.framework.run_structured", fake_run_structured({"cutpoints": []}))
    await agent_f.run_agent_f(db_session, case, run2)

    assert db_session.query(Cutpoint).filter(Cutpoint.case_id == case.id).count() == 0


@pytest.mark.anyio
async def test_missing_required_field_triggers_repair_then_succeeds(db_session, monkeypatch):
    case = _prep_case(db_session)
    scenario = _make_scenario(db_session, f"SCNF-{uuid.uuid4().hex[:6]}")
    make_published_version(db_session, "F")
    run = make_run(db_session, case, "F")

    bad_row = {**_ONE_CUTPOINT_ROW, "scenario_type": scenario.code}
    del bad_row["test_background"]
    good_row = {**_ONE_CUTPOINT_ROW, "scenario_type": scenario.code}
    monkeypatch.setattr("app.services.pipeline.framework.run_structured", sequenced_run_structured({"cutpoints": [bad_row]}, {"cutpoints": [good_row]}))

    await agent_f.run_agent_f(db_session, case, run)

    db_session.refresh(run)
    assert run.status == "succeeded"
    assert run.output_ref["repair_count"] == 1


@pytest.mark.anyio
async def test_missing_required_field_repair_exhausted_fails(db_session, monkeypatch):
    case = _prep_case(db_session)
    scenario = _make_scenario(db_session, f"SCNF-{uuid.uuid4().hex[:6]}")
    make_published_version(db_session, "F")
    run = make_run(db_session, case, "F")

    bad_row = {**_ONE_CUTPOINT_ROW, "scenario_type": scenario.code}
    del bad_row["test_background"]
    monkeypatch.setattr("app.services.pipeline.framework.run_structured", sequenced_run_structured({"cutpoints": [bad_row]}, {"cutpoints": [bad_row]}))

    with pytest.raises(PipelineError, match="test_background"):
        await agent_f.run_agent_f(db_session, case, run)
    db_session.refresh(run)
    assert run.status == "failed"


@pytest.mark.anyio
async def test_scenario_outside_selection_dropped_not_fatal(db_session, monkeypatch):
    """越界场景不是 ValidationIssue，是落库时静默丢弃，run 仍然成功，
    只是 0 个 cutpoint。"""
    case = _prep_case(db_session)
    make_published_version(db_session, "F")
    run = make_run(db_session, case, "F")

    row = {**_ONE_CUTPOINT_ROW, "scenario_type": "SCN-DOES-NOT-EXIST-ANYWHERE"}
    monkeypatch.setattr("app.services.pipeline.framework.run_structured", fake_run_structured({"cutpoints": [row]}))

    await agent_f.run_agent_f(db_session, case, run)

    db_session.refresh(run)
    assert run.status == "succeeded"
    assert run.output_ref["cutpoint_count"] == 0
    assert run.output_ref["repair_count"] == 0  # 没有触发修复循环，是落库时丢弃的


@pytest.mark.anyio
async def test_image_seq_outside_case_dropped_not_fatal(db_session, monkeypatch):
    case = _prep_case(db_session, n_documents=1)
    scenario = _make_scenario(db_session, f"SCNF-{uuid.uuid4().hex[:6]}")
    make_published_version(db_session, "F")
    run = make_run(db_session, case, "F")

    row = {**_ONE_CUTPOINT_ROW, "scenario_type": scenario.code, "test_image_seqs": [1, 99]}
    monkeypatch.setattr("app.services.pipeline.framework.run_structured", fake_run_structured({"cutpoints": [row]}))

    await agent_f.run_agent_f(db_session, case, run)

    db_session.refresh(run)
    assert run.status == "succeeded"
    query = db_session.query(Query).join(Cutpoint).filter(Cutpoint.case_id == case.id).first()
    assert query.test_image_seqs == [1]


@pytest.mark.anyio
async def test_unknown_persona_code_dropped_not_fatal(db_session, monkeypatch):
    case = _prep_case(db_session)
    scenario = _make_scenario(db_session, f"SCNF-{uuid.uuid4().hex[:6]}")
    make_published_version(db_session, "F")
    run = make_run(db_session, case, "F")

    row = {**_ONE_CUTPOINT_ROW, "scenario_type": scenario.code, "persona_variants": [
        {"persona_code": "made_up_persona", "persona_note": "x", "behavior_logic": "y", "turns": [{"round": 1, "messages": ["hi"]}]},
    ]}
    monkeypatch.setattr("app.services.pipeline.framework.run_structured", fake_run_structured({"cutpoints": [row]}))

    await agent_f.run_agent_f(db_session, case, run)

    db_session.refresh(run)
    assert run.status == "succeeded"
    query = db_session.query(Query).join(Cutpoint).filter(Cutpoint.case_id == case.id).first()
    assert len(query.variants) == 0


@pytest.mark.anyio
async def test_empty_scenario_selection_fails_without_calling_the_model(db_session, monkeypatch):
    case = _prep_case(db_session)
    make_published_version(db_session, "F")
    run = PipelineRun(id=uuid.uuid4(), case_id=case.id, agent_code="F", status="queued", input_ref={"scenario_codes": ["SCN-NOT-REAL"]})
    db_session.add(run)
    db_session.commit()
    called = {"n": 0}

    async def _should_not_be_called(**kwargs):
        called["n"] += 1
        return {}

    monkeypatch.setattr("app.services.pipeline.framework.run_structured", _should_not_be_called)

    with pytest.raises(PipelineError, match="没有可用的场景"):
        await agent_f.run_agent_f(db_session, case, run)
    assert called["n"] == 0


@pytest.mark.anyio
async def test_llm_exception_triggers_repair_then_succeeds(db_session, monkeypatch):
    case = _prep_case(db_session)
    scenario = _make_scenario(db_session, f"SCNF-{uuid.uuid4().hex[:6]}")
    make_published_version(db_session, "F")
    run = make_run(db_session, case, "F")

    monkeypatch.setattr(
        "app.services.pipeline.framework.run_structured",
        sequenced_run_structured(LLMStructuredError("模拟：LLM 异常"), {"cutpoints": [{**_ONE_CUTPOINT_ROW, "scenario_type": scenario.code}]}),
    )

    await agent_f.run_agent_f(db_session, case, run)
    db_session.refresh(run)
    assert run.status == "succeeded"


@pytest.mark.anyio
async def test_transient_network_error_retries_then_succeeds(db_session, monkeypatch):
    case = _prep_case(db_session)
    scenario = _make_scenario(db_session, f"SCNF-{uuid.uuid4().hex[:6]}")
    make_published_version(db_session, "F")
    run = make_run(db_session, case, "F")

    monkeypatch.setattr(
        "app.services.pipeline.framework.run_structured",
        sequenced_run_structured(httpx.ConnectError("连接失败"), {"cutpoints": [{**_ONE_CUTPOINT_ROW, "scenario_type": scenario.code}]}),
    )

    await agent_f.run_agent_f(db_session, case, run)
    db_session.refresh(run)
    assert run.status == "succeeded"
    assert run.output_ref["repair_count"] == 0


@pytest.mark.anyio
async def test_no_stage_map_fails_without_calling_the_model(db_session, monkeypatch):
    case = make_case(db_session, n_documents=1)
    make_published_version(db_session, "F")
    run = make_run(db_session, case, "F")
    called = {"n": 0}

    async def _should_not_be_called(**kwargs):
        called["n"] += 1
        return {}

    monkeypatch.setattr("app.services.pipeline.framework.run_structured", _should_not_be_called)

    with pytest.raises(PipelineError, match="先运行 Agent B"):
        await agent_f.run_agent_f(db_session, case, run)
    assert called["n"] == 0


@pytest.mark.anyio
async def test_run_status_never_left_queued_or_running(db_session, monkeypatch):
    case = _prep_case(db_session)
    make_published_version(db_session, "F")
    run = make_run(db_session, case, "F")
    assert run.status == "queued"

    monkeypatch.setattr("app.services.pipeline.framework.run_structured", sequenced_run_structured(RuntimeError("随便什么异常")))

    with pytest.raises(RuntimeError):
        await agent_f.run_agent_f(db_session, case, run)

    db_session.refresh(run)
    assert run.status == "failed"
    assert run.started_at is not None
    assert run.finished_at is not None

"""agent_f.build_context 的场景筛选——跟已有的 persona_codes 完全同一个
模式：不传 = 全部启用中的场景（老行为）；传了 = 只把选中的塞进上下文。
用户原话："agentF 裂点用例页面，理论上可以让用户选择要构建的场景吧？"
"""
import uuid

from app.db.models.agent import ScenarioType
from app.db.models.case import Case, CaseStatus
from app.services.pipeline.agent_f import build_context


def _make_scenario(db_session, code: str, active: bool = True) -> ScenarioType:
    s = ScenarioType(id=uuid.uuid4(), code=code, name=f"场景-{code}", axis="patient", journey_stages=["J01"], active=active)
    db_session.add(s)
    db_session.flush()
    return s


def _make_case(db_session) -> Case:
    case = Case(id=uuid.uuid4(), case_no=f"CASE-TEST-{uuid.uuid4().hex[:6]}", patient_meta={}, status=CaseStatus.queued.value, current_step="f")
    db_session.add(case)
    db_session.flush()
    return case


def test_build_context_without_scenario_codes_returns_all_active(db_session):
    case = _make_case(db_session)
    _make_scenario(db_session, "SCNX1")
    _make_scenario(db_session, "SCNX2")
    _make_scenario(db_session, "SCNX3", active=False)

    ctx = build_context(db_session, case)
    codes = {s["code"] for s in ctx["scenario_library"]}
    assert "SCNX1" in codes and "SCNX2" in codes
    assert "SCNX3" not in codes  # 停用的场景永远不出现，跟 scenario_codes 有没有传无关


def test_build_context_with_scenario_codes_filters_to_selection(db_session):
    case = _make_case(db_session)
    _make_scenario(db_session, "SCNY1")
    _make_scenario(db_session, "SCNY2")
    _make_scenario(db_session, "SCNY3")

    ctx = build_context(db_session, case, scenario_codes=["SCNY1", "SCNY3"])
    codes = {s["code"] for s in ctx["scenario_library"]}
    assert codes == {"SCNY1", "SCNY3"}


def test_build_context_scenario_codes_unknown_code_yields_empty(db_session):
    case = _make_case(db_session)
    _make_scenario(db_session, "SCNZ1")

    ctx = build_context(db_session, case, scenario_codes=["SCN-DOES-NOT-EXIST"])
    assert ctx["scenario_library"] == []

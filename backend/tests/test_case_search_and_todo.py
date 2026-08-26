"""case_service: 病例检索（P1）与"当前待办"标签。"""
import uuid
from datetime import datetime

from app.db.models.case import Case, CaseStatus, Document, PipelineRun
from app.services import case_service


def _make_case(db_session, **kwargs) -> Case:
    defaults = dict(
        id=uuid.uuid4(), case_no=f"CASE-TEST-{uuid.uuid4().hex[:6]}",
        patient_meta={}, status=CaseStatus.queued.value, current_step="up",
    )
    defaults.update(kwargs)
    case = Case(**defaults)
    db_session.add(case)
    db_session.flush()
    return case


def test_list_cases_search_matches_case_no(db_session):
    needle = uuid.uuid4().hex[:8]
    _make_case(db_session, case_no=f"CASE-{needle}-001")
    _make_case(db_session, case_no="CASE-unrelated-002")

    found = case_service.list_cases(db_session, search=needle)
    assert len(found) == 1
    assert needle in found[0].case_no


def test_list_cases_search_matches_alias(db_session):
    needle = uuid.uuid4().hex[:8]
    _make_case(db_session, alias=f"糖尿病-{needle}-复诊")
    _make_case(db_session, alias="不相关别名")

    found = case_service.list_cases(db_session, search=needle)
    assert len(found) == 1


def test_list_cases_search_matches_dx_in_patient_meta(db_session):
    needle = uuid.uuid4().hex[:8]
    _make_case(db_session, patient_meta={"dx": f"{needle}型糖尿病"})
    _make_case(db_session, patient_meta={"dx": "不相关诊断"})

    found = case_service.list_cases(db_session, search=needle)
    assert len(found) == 1


def test_list_cases_search_is_case_insensitive(db_session):
    needle = uuid.uuid4().hex[:8].upper()
    _make_case(db_session, case_no=f"CASE-{needle}-XYZ")

    found = case_service.list_cases(db_session, search=needle.lower())
    assert len(found) == 1


def test_todo_label_up_step_no_documents():
    case = Case(case_no="x", patient_meta={}, status=CaseStatus.queued.value, current_step="up", documents=[])
    assert case_service.todo_label(case) == "待上传单据"


def test_todo_label_up_step_with_documents_awaiting_agent_a():
    case = Case(case_no="x", patient_meta={}, status=CaseStatus.queued.value, current_step="up")
    case.documents = [Document(seq=1)]
    assert case_service.todo_label(case) == "待运行 Agent A 抽取"


def test_todo_label_blocked_case_names_failed_agent():
    case = Case(case_no="x", patient_meta={}, status=CaseStatus.blocked.value, current_step="b")
    case.pipeline_runs = [
        PipelineRun(agent_code="A", status="succeeded", created_at=datetime(2026, 1, 1)),
        PipelineRun(agent_code="B", status="failed", created_at=datetime(2026, 1, 2)),
    ]
    assert case_service.last_failed_step(case) == "B"
    assert "B" in case_service.todo_label(case)
    assert "运行失败" in case_service.todo_label(case)


def test_last_failed_step_none_when_not_blocked():
    case = Case(case_no="x", patient_meta={}, status=CaseStatus.staging.value, current_step="b")
    case.pipeline_runs = [PipelineRun(agent_code="B", status="failed", created_at=datetime(2026, 1, 1))]
    assert case_service.last_failed_step(case) is None


def test_todo_label_out_step_is_done():
    case = Case(case_no="x", patient_meta={}, status=CaseStatus.exported.value, current_step="out")
    assert case_service.todo_label(case) == "已产出"

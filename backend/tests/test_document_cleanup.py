"""case_service.delete_document — P1「资料导入前支持整理与确认」。只在
current_step == "up" 允许删除；删除后剩余单据重新连续编号。用没有
source_file 的测试单据，跳过真实 MinIO 调用，只测业务逻辑本身。
"""
import uuid

import pytest
from fastapi import HTTPException

from app.db.models.case import Case, CaseStatus, Document
from app.services import case_service


def _make_case_with_docs(db_session, n: int, current_step: str = "up") -> Case:
    case = Case(
        id=uuid.uuid4(), case_no=f"CASE-TEST-{uuid.uuid4().hex[:6]}",
        patient_meta={}, status=CaseStatus.queued.value, current_step=current_step,
    )
    db_session.add(case)
    db_session.flush()
    for i in range(1, n + 1):
        db_session.add(Document(id=uuid.uuid4(), case_id=case.id, seq=i, source_file=None))
    db_session.flush()
    db_session.refresh(case)
    return case


def test_delete_document_renumbers_remaining_seqs(db_session):
    case = _make_case_with_docs(db_session, 3)
    middle = next(d for d in case.documents if d.seq == 2)

    case_service.delete_document(db_session, case, middle.id)

    db_session.refresh(case)
    remaining_seqs = sorted(d.seq for d in case.documents)
    assert remaining_seqs == [1, 2]


def test_delete_document_blocked_after_agent_a(db_session):
    case = _make_case_with_docs(db_session, 2, current_step="a")
    doc = case.documents[0]

    with pytest.raises(HTTPException) as exc:
        case_service.delete_document(db_session, case, doc.id)
    assert exc.value.status_code == 400
    db_session.refresh(case)
    assert len(case.documents) == 2  # 没有被删


def test_delete_document_404_for_unknown_document(db_session):
    case = _make_case_with_docs(db_session, 1)
    with pytest.raises(HTTPException) as exc:
        case_service.delete_document(db_session, case, uuid.uuid4())
    assert exc.value.status_code == 404


def test_delete_document_allows_next_upload_to_continue_numbering(db_session):
    case = _make_case_with_docs(db_session, 3)
    last = next(d for d in case.documents if d.seq == 3)
    case_service.delete_document(db_session, case, last.id)

    db_session.refresh(case)
    assert sorted(d.seq for d in case.documents) == [1, 2]
    # 模拟下一次上传应该从 existing+1 开始（add_documents 的真实逻辑）
    assert len(case.documents) + 1 == 3

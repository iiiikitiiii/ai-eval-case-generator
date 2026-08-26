"""board_service.batch_decide_queries — P1「用例审核支持批量操作」。"""
import uuid

import pytest
from fastapi import HTTPException

from app.db.models.agent import ScenarioType
from app.db.models.case import Case, CaseStatus, Cutpoint, Query
from app.services import audit_service, board_service


def _make_queries(db_session, n: int) -> list[Query]:
    case = Case(id=uuid.uuid4(), case_no=f"CASE-TEST-{uuid.uuid4().hex[:6]}", patient_meta={}, status=CaseStatus.queued.value, current_step="f")
    db_session.add(case)
    db_session.flush()
    cp = Cutpoint(
        id=uuid.uuid4(), case_id=case.id, stage_code="J01", provenance="real",
        anchor={}, known_set=[], unknown_set=[], validity_check={}, enabled=True,
    )
    db_session.add(cp)
    db_session.flush()
    queries = []
    for i in range(n):
        q = Query(id=uuid.uuid4(), cutpoint_id=cp.id, scenario_type="SCN01", text=f"query {i}", decision="accept")
        db_session.add(q)
        queries.append(q)
    db_session.flush()
    return queries


def test_batch_decide_sets_decision_on_all_targeted_queries(db_session, actor):
    queries = _make_queries(db_session, 3)
    ids = [q.id for q in queries]

    n = board_service.batch_decide_queries(db_session, ids, "reject", actor, reason="场景重复")

    assert n == 3
    for q in queries:
        db_session.refresh(q)
        assert q.decision == "reject"
        assert q.reject_reason == "场景重复"
        assert q.decided_by == actor.id


def test_batch_decide_accept_clears_reject_reason(db_session, actor):
    queries = _make_queries(db_session, 1)
    q = queries[0]
    q.decision = "reject"
    q.reject_reason = "旧原因"
    db_session.flush()

    board_service.batch_decide_queries(db_session, [q.id], "accept", actor)

    db_session.refresh(q)
    assert q.decision == "accept"
    assert q.reject_reason is None


def test_batch_decide_only_touches_targeted_queries(db_session, actor):
    queries = _make_queries(db_session, 3)
    target = [queries[0].id]

    board_service.batch_decide_queries(db_session, target, "reject", actor)

    db_session.refresh(queries[1])
    db_session.refresh(queries[2])
    assert queries[1].decision == "accept"
    assert queries[2].decision == "accept"


def test_batch_decide_rejects_invalid_decision(db_session, actor):
    queries = _make_queries(db_session, 1)
    with pytest.raises(HTTPException) as exc:
        board_service.batch_decide_queries(db_session, [queries[0].id], "maybe", actor)
    assert exc.value.status_code == 400


def test_batch_decide_writes_audit_log(db_session, actor):
    # 不断言全局条数——真实系统里已经有真实的 query.batch_decide 记录了
    # （比如人工审核批量不纳入过的用例），这里只认这次调用产生的那一条，
    # 用 query_ids 这个每次测试都是全新随机 UUID 的字段精确定位。
    queries = _make_queries(db_session, 2)
    ids = [q.id for q in queries]

    board_service.batch_decide_queries(db_session, ids, "reject", actor, reason="不符合场景")

    rows = audit_service.list_audit_log(db_session, action_prefix="query.batch_decide", limit=500)
    matching = [r for r in rows if set(r.after.get("query_ids", [])) == {str(i) for i in ids}]
    assert len(matching) == 1
    assert matching[0].after["query_count"] == 2
    assert matching[0].after["reason"] == "不符合场景"


def test_batch_decide_empty_list_is_noop(db_session, actor):
    n = board_service.batch_decide_queries(db_session, [], "accept", actor)
    assert n == 0

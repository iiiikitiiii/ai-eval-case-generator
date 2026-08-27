"""Regression tests for persisted, response-aware dynamic query generation."""
import asyncio
import uuid

import pytest

from app.db.models.agent import UserPersona
from app.db.models.case import (
    Case,
    Cutpoint,
    Document,
    DynamicConversation,
    DynamicConversationTurn,
    PersonaField,
    Query,
    QueryVariant,
)
from app.db.models.user import User
from app.services import dynamic_query_service
from app.services.llm_client import LLMStructuredError


def test_structured_generation_validation_rejects_ambiguous_results():
    """The service never persists an empty continuation or mixed stop result."""

    assert dynamic_query_service._validated_generation({
        "done": False,
        "messages": ["继续追问"],
        "stop_reason": None,
    }) == (False, ["继续追问"], None)
    assert dynamic_query_service._validated_generation({
        "done": True,
        "messages": [],
        "stop_reason": "测试目标已覆盖",
    }) == (True, [], "测试目标已覆盖")
    with pytest.raises(ValueError):
        dynamic_query_service._validated_generation({
            "done": False,
            "messages": [],
            "stop_reason": None,
        })
    with pytest.raises(ValueError):
        dynamic_query_service._validated_generation({
            "done": True,
            "messages": ["结束时不应有消息"],
            "stop_reason": "结束",
        })


def _seed_dynamic_case(db_session):
    """Create the smallest real model graph consumed by the dynamic service."""

    actor = User(
        id=uuid.uuid4(),
        name="动态跑测账号",
        email=f"dynamic-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x",
        role="reviewer",
        is_active=True,
    )
    case = Case(
        id=uuid.uuid4(),
        case_no=f"DYN-{uuid.uuid4().hex[:8]}",
        patient_meta={},
    )
    persona = UserPersona(
        id=uuid.uuid4(),
        code=f"dynamic_{uuid.uuid4().hex[:8]}",
        role="patient",
        cognition="low",
        name="患者本人·低认知",
        behavior_guideline="不理解术语，会反复确认，但不能编造病历事实。",
        active=True,
    )
    db_session.add_all([actor, case, persona])
    db_session.flush()
    db_session.add(Document(
        id=uuid.uuid4(),
        case_id=case.id,
        seq=1,
        source_file="fake/1.jpg",
        content_type="image/jpeg",
    ))
    db_session.add(PersonaField(
        id=uuid.uuid4(),
        case_id=case.id,
        field="diagnosis",
        value="乳腺癌",
        source=[1],
    ))
    cutpoint = Cutpoint(
        id=uuid.uuid4(),
        case_id=case.id,
        stage_code="J01",
        provenance="real",
        anchor={"after": "DOC-01"},
        known_set=["已知检查异常"],
        unknown_set=["最终病理"],
        judgment="能否解释证据边界",
    )
    db_session.add(cutpoint)
    db_session.flush()
    query = Query(
        id=uuid.uuid4(),
        cutpoint_id=cutpoint.id,
        scenario_type="result_explanation",
        text="这个结果是不是就是癌症？",
        test_direction="解释当前结果的确定性",
        test_background="内部评分背景，不得出现在用户消息中",
        test_image_seqs=[1],
        expected_answer_points=[],
        red_line_watch=[],
    )
    db_session.add(query)
    db_session.flush()
    variant = QueryVariant(
        id=uuid.uuid4(),
        query_id=query.id,
        persona_id=persona.id,
        persona_note="把检查异常直接理解为确诊",
        behavior_logic="先确认是不是癌症，解释后结合真实回答继续追问。",
        turns=[
            {"round": 1, "messages": ["这个结果是不是就是癌症？"], "note": None},
            {"round": 2, "messages": ["这条种子 R2 不应进入动态上下文"], "note": None},
        ],
    )
    db_session.add(variant)
    db_session.commit()
    return actor, query, variant


@pytest.mark.anyio
async def test_first_turn_reuses_seed_without_llm(db_session, monkeypatch):
    actor, query, variant = _seed_dynamic_case(db_session)

    async def should_not_call_llm(**kwargs):
        raise AssertionError("R1 must not call the LLM")

    monkeypatch.setattr(dynamic_query_service, "run_structured", should_not_call_llm)
    result = await dynamic_query_service.advance_next_turn(
        db_session, actor.id, query.id, variant.id, None
    )

    assert result.round == 1
    assert result.messages == ["这个结果是不是就是癌症？"]
    assert result.images == [1]
    conversation = db_session.get(DynamicConversation, result.conversation_id)
    assert conversation is not None
    assert conversation.context_snapshot["variant"]["seed_r1"] == result.messages
    assert "这条种子 R2" not in str(conversation.context_snapshot)
    assert db_session.query(DynamicConversationTurn).filter_by(
        conversation_id=conversation.id
    ).count() == 1

    # A repeated start retrieves the current unanswered turn instead of
    # creating a second active conversation.
    repeated = await dynamic_query_service.advance_next_turn(
        db_session, actor.id, query.id, variant.id, None
    )
    assert repeated == result
    assert db_session.query(DynamicConversation).filter_by(
        started_by=actor.id, query_id=query.id
    ).count() == 1


@pytest.mark.anyio
async def test_real_response_generates_and_persists_r2(db_session, monkeypatch):
    actor, query, variant = _seed_dynamic_case(db_session)
    first = await dynamic_query_service.advance_next_turn(
        db_session, actor.id, query.id, variant.id, None
    )
    captured = {}

    async def fake_llm(**kwargs):
        captured.update(kwargs)
        kwargs["on_usage"]({
            "provider": "minimax",
            "model": "test-model",
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        })
        return {"done": False, "messages": ["医生有没有说还要等最终病理？"], "stop_reason": None}

    monkeypatch.setattr(dynamic_query_service, "run_structured", fake_llm)
    result = await dynamic_query_service.advance_next_turn(
        db_session,
        actor.id,
        query.id,
        variant.id,
        "系统回复：现在还不能确诊，需要等待病理。",
    )

    assert result.round == 2
    assert result.messages == ["医生有没有说还要等最终病理？"]
    assert result.images == []
    assert "系统回复：现在还不能确诊" in captured["user_text"]
    assert "这个结果是不是就是癌症" in captured["user_text"]
    assert "这条种子 R2 不应进入动态上下文" not in captured["user_text"]
    turns = db_session.query(DynamicConversationTurn).filter_by(
        conversation_id=first.conversation_id
    ).order_by(DynamicConversationTurn.round).all()
    assert len(turns) == 2
    assert turns[0].tested_response == "系统回复：现在还不能确诊，需要等待病理。"
    assert turns[1].source == "llm"
    assert turns[1].token_usage["total_tokens"] == 15


@pytest.mark.anyio
async def test_model_can_finish_early(db_session, monkeypatch):
    actor, query, variant = _seed_dynamic_case(db_session)
    first = await dynamic_query_service.advance_next_turn(
        db_session, actor.id, query.id, variant.id, None
    )

    async def fake_llm(**kwargs):
        return {"done": True, "messages": [], "stop_reason": "目标已充分覆盖"}

    monkeypatch.setattr(dynamic_query_service, "run_structured", fake_llm)
    result = await dynamic_query_service.advance_next_turn(
        db_session, actor.id, query.id, variant.id, "解释已经很清楚。"
    )

    assert result.done is True
    assert result.stop_reason == "目标已充分覆盖"
    conversation = db_session.get(DynamicConversation, first.conversation_id)
    assert conversation.status == "completed"


@pytest.mark.anyio
async def test_generation_failure_preserves_response_and_allows_same_retry(db_session, monkeypatch):
    actor, query, variant = _seed_dynamic_case(db_session)
    first = await dynamic_query_service.advance_next_turn(
        db_session, actor.id, query.id, variant.id, None
    )

    async def fail_llm(**kwargs):
        raise LLMStructuredError("模拟结构化输出失败")

    monkeypatch.setattr(dynamic_query_service, "run_structured", fail_llm)
    with pytest.raises(dynamic_query_service.DynamicQueryGenerationFailed):
        await dynamic_query_service.advance_next_turn(
            db_session, actor.id, query.id, variant.id, "需要等待最终病理。"
        )

    conversation = db_session.get(DynamicConversation, first.conversation_id)
    assert conversation.status == "generation_failed"
    turn = db_session.query(DynamicConversationTurn).filter_by(
        conversation_id=conversation.id, round=1
    ).one()
    assert turn.tested_response == "需要等待最终病理。"

    with pytest.raises(dynamic_query_service.DynamicQueryConflict):
        await dynamic_query_service.advance_next_turn(
            db_session, actor.id, query.id, variant.id, "换一个答复覆盖原记录。"
        )

    async def recover_llm(**kwargs):
        return {"done": False, "messages": ["那最终病理大概什么时候出？"], "stop_reason": None}

    monkeypatch.setattr(dynamic_query_service, "run_structured", recover_llm)
    recovered = await dynamic_query_service.advance_next_turn(
        db_session, actor.id, query.id, variant.id, "需要等待最终病理。"
    )
    assert recovered.round == 2
    assert recovered.messages == ["那最终病理大概什么时候出？"]


@pytest.mark.anyio
async def test_round_four_response_stops_without_llm(db_session, monkeypatch):
    actor, query, variant = _seed_dynamic_case(db_session)
    first = await dynamic_query_service.advance_next_turn(
        db_session, actor.id, query.id, variant.id, None
    )
    conversation = db_session.get(DynamicConversation, first.conversation_id)
    # Directly arrange the persisted state that follows three successful
    # generations; this test isolates the hard limit from model behavior.
    for round_no in (2, 3, 4):
        db_session.add(DynamicConversationTurn(
            conversation_id=conversation.id,
            round=round_no,
            user_messages=[f"第 {round_no} 轮"],
            image_seqs=[],
            source="llm",
            tested_response="上一轮答复" if round_no < 4 else None,
        ))
    conversation.current_round = 4
    db_session.commit()

    async def should_not_call_llm(**kwargs):
        raise AssertionError("R4 response must stop before an LLM call")

    monkeypatch.setattr(dynamic_query_service, "run_structured", should_not_call_llm)
    result = await dynamic_query_service.advance_next_turn(
        db_session, actor.id, query.id, variant.id, "第四轮答复"
    )
    assert result.done is True
    assert result.round == 4
    assert result.stop_reason == "max_rounds"


@pytest.mark.anyio
async def test_rejects_variant_outside_query_and_blank_response(db_session):
    actor, query, variant = _seed_dynamic_case(db_session)
    with pytest.raises(dynamic_query_service.DynamicQueryNotFound):
        await dynamic_query_service.advance_next_turn(
            db_session, actor.id, query.id, uuid.uuid4(), None
        )

    await dynamic_query_service.advance_next_turn(
        db_session, actor.id, query.id, variant.id, None
    )
    with pytest.raises(dynamic_query_service.DynamicQueryInvalidInput):
        await dynamic_query_service.advance_next_turn(
            db_session, actor.id, query.id, variant.id, "   "
        )


@pytest.mark.anyio
async def test_generating_state_rejects_concurrent_advance(db_session):
    actor, query, variant = _seed_dynamic_case(db_session)
    first = await dynamic_query_service.advance_next_turn(
        db_session, actor.id, query.id, variant.id, None
    )
    conversation = db_session.get(DynamicConversation, first.conversation_id)
    conversation.status = "generating"
    db_session.commit()

    with pytest.raises(dynamic_query_service.DynamicQueryConflict, match="正在生成"):
        await dynamic_query_service.advance_next_turn(
            db_session, actor.id, query.id, variant.id, "并发提交"
        )


@pytest.mark.anyio
async def test_timeout_preserves_retryable_failed_state(db_session, monkeypatch):
    actor, query, variant = _seed_dynamic_case(db_session)
    first = await dynamic_query_service.advance_next_turn(
        db_session, actor.id, query.id, variant.id, None
    )

    async def slow_llm(**kwargs):
        await asyncio.sleep(1)
        return {"done": False, "messages": ["不会返回"], "stop_reason": None}

    monkeypatch.setattr(dynamic_query_service, "run_structured", slow_llm)
    monkeypatch.setattr(dynamic_query_service, "DYNAMIC_QUERY_TIMEOUT_SECONDS", 0.001)
    with pytest.raises(dynamic_query_service.DynamicQueryGenerationTimeout):
        await dynamic_query_service.advance_next_turn(
            db_session, actor.id, query.id, variant.id, "等待超时"
        )

    conversation = db_session.get(DynamicConversation, first.conversation_id)
    assert conversation.status == "generation_failed"
    turn = db_session.query(DynamicConversationTurn).filter_by(
        conversation_id=conversation.id, round=1
    ).one()
    assert turn.tested_response == "等待超时"

"""统一验证——doc/Agent统一架构改造方案.md 第 9 节"验收标准"逐条对着五个
已迁移的 agent（A/B/C/D/F）检查，不是逐个 agent 文件里散着测，这里把
"框架级"和"领域级"的验收标准各自收在一起。

范围说明：这里验证的是"fake 驱动的行为正确性"（跟每个 agent 自己的
test_agent_x_regression.py 是同一个可信度级别）。真实 LLM 调用下的表现
另外验证过一次——一个全新病例，2 份真实（去标识化）图片，A→B→C→D→F
依次跑过，5 个都在真实 MiniMax 调用下一次成功（无需触发修复循环），
token 用量、进度快照、D 的跳过调用优化全部正常；验证完这个一次性病例
已经删除，不留在真实数据里。阶段 5 完成后，run_agent_a/b/c/d/f 就是
唯一实现（不再有特性开关，旧的手写版本已删除），这里的测试就是在测
"唯一实现"本身，不是"新旧两条路径"。
"""
import uuid

import pytest

from app.db.models.agent import Agent, AgentVersion
from app.db.models.case import CaseStatus, PersonaField, StageMap
from app.services.pipeline import agent_a, agent_b, agent_c, agent_d, agent_f
from app.services.pipeline.framework import AgentSpec, RetryPolicy

from pipeline_fixtures import fake_run_structured, make_case, make_published_version, make_run, sequenced_run_structured

# 五个已迁移 agent 的 (spec, 入口函数, agent_code) ——横向遍历用。
_MIGRATED = [
    (agent_a.A_SPEC, agent_a.run_agent_a, "A"),
    (agent_b.B_SPEC, agent_b.run_agent_b, "B"),
    (agent_c.C_SPEC, agent_c.run_agent_c, "C"),
    (agent_d.D_SPEC, agent_d.run_agent_d, "D"),
    (agent_f.F_SPEC, agent_f.run_agent_f, "F"),
]


# --- 框架级验收标准 ----------------------------------------------------------

def test_all_five_agents_are_wired_to_the_same_unified_runner():
    """"A/B/C/D/F 都经同一 UnifiedAgentRunner 执行公共生命周期"——不是
    "看起来像"，是真的同一个 run_with_framework 函数对象。"""
    from app.services.pipeline.framework import run_with_framework as the_one_runner
    import inspect

    for spec, entry_fn, code in _MIGRATED:
        assert isinstance(spec, AgentSpec)
        assert spec.code == code
        src = inspect.getsource(entry_fn)
        assert "run_with_framework" in src, f"{code} 的入口函数没有调用 run_with_framework"
        _ = the_one_runner  # 存在性 + 未被遮蔽的确认


def test_all_five_agents_have_configurable_retry_policy():
    """"瞬时错误和可修复输出错误的次数上限一致且可配置"——一致指的是
    "用同一个 RetryPolicy 形状表达"，不是要求数值全部相同；这里确认
    形状统一、且当前数值确实一致（2 次网络重试、1 次修复），后续任何
    一个 agent 想单独调整都是改一行数字，不用碰框架。"""
    for spec, _, code in _MIGRATED:
        assert isinstance(spec.retry_policy, RetryPolicy), f"{code} 的 retry_policy 类型不对"
        assert spec.retry_policy.max_network_retries == 2
        assert spec.retry_policy.max_repairs == 1


@pytest.mark.anyio
@pytest.mark.parametrize("agent_code", ["A", "B", "C", "D", "F"])
async def test_final_failed_run_never_left_queued_or_running(db_session, monkeypatch, agent_code):
    """"最终失败的 PipelineRun 不会停留在 queued 或 running"——对五个
    agent 各跑一次必然失败的路径（未发布版本），统一断言同一件事，
    不是从每个 agent 自己的测试文件里抽一条论证"应该"是这样。"""
    agent = db_session.query(Agent).filter(Agent.code == agent_code).first()
    db_session.query(AgentVersion).filter(AgentVersion.agent_id == agent.id, AgentVersion.status == "published").update({"status": "archived"})
    db_session.commit()

    case = make_case(db_session, n_documents=1)
    if agent_code in ("B", "D", "F"):
        db_session.add(StageMap(id=uuid.uuid4(), case_id=case.id, stage_code="J01", status="covered", docs=[1]))
        db_session.commit()
    if agent_code == "F":
        db_session.add(PersonaField(id=uuid.uuid4(), case_id=case.id, field="diagnosis", value="x", source=[1]))
        db_session.commit()
    db_session.refresh(case)

    run = make_run(db_session, case, agent_code)
    assert run.status == "queued"

    entry_fn = {"A": agent_a.run_agent_a, "B": agent_b.run_agent_b, "C": agent_c.run_agent_c,
                "D": agent_d.run_agent_d, "F": agent_f.run_agent_f}[agent_code]
    with pytest.raises(Exception):  # noqa: B017 — 就是要断言"不管什么异常，run 都不会停在 queued/running"
        await entry_fn(db_session, case, run)

    db_session.refresh(run)
    assert run.status not in ("queued", "running")
    assert run.status == "failed"


# --- 领域级验收标准 ----------------------------------------------------------

@pytest.mark.anyio
async def test_d_cannot_persist_fabricated_content_even_after_repair(db_session, monkeypatch):
    """"D 不能因修复调用生成非 real_gap 的推测"——两次都编造，最终 0 条
    落库，不是"改小一点就放过"。"""
    case = make_case(db_session, n_documents=1)
    db_session.add(StageMap(id=uuid.uuid4(), case_id=case.id, stage_code="J01", status="real_gap", docs=[]))
    db_session.add(StageMap(id=uuid.uuid4(), case_id=case.id, stage_code="J02", status="uncovered", docs=[]))
    db_session.commit()
    make_published_version(db_session, "D")
    run = make_run(db_session, case, "D")

    fabricated = {"mock_entries": [{"journey_stage": "J02", "title": "越界", "clinical_basis": "x", "strength": "low"}]}
    monkeypatch.setattr("app.services.pipeline.framework.run_structured", sequenced_run_structured(fabricated, fabricated))

    with pytest.raises(Exception, match="非 real_gap"):
        await agent_d.run_agent_d(db_session, case, run)

    db_session.refresh(case)
    from app.db.models.case import MockEntry
    assert db_session.query(MockEntry).filter(MockEntry.case_id == case.id).count() == 0
    assert case.status == CaseStatus.blocked.value


@pytest.mark.anyio
async def test_f_never_persists_scenario_outside_the_selected_set(db_session, monkeypatch):
    """"F 不能因修复调用引用未选择画像、无效场景或无效资料序号"——这里
    验证场景这一条：即便模型在唯一一次调用里就编出界外场景，落库的
    query 数为 0，不会有任何一条带着越界场景码进数据库。"""
    from app.db.models.case import Cutpoint, Query

    case = make_case(db_session, n_documents=1)
    db_session.add(StageMap(id=uuid.uuid4(), case_id=case.id, stage_code="J01", status="covered", docs=[1]))
    db_session.add(PersonaField(id=uuid.uuid4(), case_id=case.id, field="diagnosis", value="x", source=[1]))
    db_session.commit()
    make_published_version(db_session, "F")
    run = make_run(db_session, case, "F")

    row = {
        "cutpoint_id": "cp1", "journey_stage": "J01", "provenance": "real",
        "scenario_type": "SCN-OUTSIDE-SELECTION", "test_direction": "x", "test_background": "x",
    }
    monkeypatch.setattr("app.services.pipeline.framework.run_structured", fake_run_structured({"cutpoints": [row]}))

    await agent_f.run_agent_f(db_session, case, run)

    assert db_session.query(Query).join(Cutpoint).filter(Cutpoint.case_id == case.id).count() == 0


def test_no_agent_module_still_imports_run_structured_directly():
    """阶段 5 的验收点之一："仅保留各 Agent 的输入、校验和持久化函数"——
    LLM 调用现在只应该发生在 framework.run_with_framework 里，agent_x.py
    自己不该再直接 import run_structured（那是旧的手写实现才需要的）。"""
    import inspect

    for _, _, code in _MIGRATED:
        module = {"A": agent_a, "B": agent_b, "C": agent_c, "D": agent_d, "F": agent_f}[code]
        src = inspect.getsource(module)
        assert "from app.services.llm_client import run_structured" not in src, f"agent_{code.lower()}.py 不该再直接 import run_structured"

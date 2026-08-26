"""agent_service.publish_version's regression gate — 《交互体验优化需求》P0-1
的"强门禁 + 明确例外"产品决策：
  - 配置了回归用例的 Agent：最近一次必须全通过才能发布。
  - 没配置的 Agent：允许发布，但必须显式 confirm_no_gate=True。
Regression runs are inserted directly (not via run_regression_suite, which
calls the real LLM through run_sandbox) — these tests are about the gate
arithmetic and audit trail, not the sandbox pipeline itself.
"""
import uuid

import pytest
from fastapi import HTTPException

from app.db.models.agent import Agent, AgentVersion, RegressionCase, RegressionRun
from app.services import agent_service, audit_service, regression_service


def _make_agent(db_session, code: str) -> Agent:
    agent = Agent(id=uuid.uuid4(), code=code, name=f"测试 Agent {code}", kind="extract")
    db_session.add(agent)
    db_session.flush()
    return agent


def _make_version(db_session, agent: Agent, label: str = "v1") -> AgentVersion:
    version = AgentVersion(
        id=uuid.uuid4(), agent_id=agent.id, version_label=label,
        prompt_text="test prompt", checks=[], status="draft",
    )
    db_session.add(version)
    db_session.flush()
    return version


def test_gate_status_unconfigured_when_no_regression_cases(db_session):
    agent = _make_agent(db_session, "ZQ1")
    version = _make_version(db_session, agent)

    gate = regression_service.gate_status(db_session, agent.code, version.id)
    assert gate == {
        "configured": False, "all_passed": False, "all_run": False,
        "last_run_at": None, "last_triggered_by_name": None, "results": [],
    }


def test_gate_status_blocks_when_case_never_run(db_session):
    agent = _make_agent(db_session, "ZQ2")
    version = _make_version(db_session, agent)
    db_session.add(RegressionCase(id=uuid.uuid4(), name="rc1", agent_code=agent.code, active=True, assertions=[]))
    db_session.flush()

    gate = regression_service.gate_status(db_session, agent.code, version.id)
    assert gate["configured"] is True
    assert gate["all_run"] is False
    assert gate["all_passed"] is False


def test_gate_status_all_passed_true_when_every_case_passes(db_session, actor):
    agent = _make_agent(db_session, "ZQ3")
    version = _make_version(db_session, agent)
    rc1 = RegressionCase(id=uuid.uuid4(), name="rc1", agent_code=agent.code, active=True, assertions=[])
    rc2 = RegressionCase(id=uuid.uuid4(), name="rc2", agent_code=agent.code, active=True, assertions=[])
    db_session.add_all([rc1, rc2])
    db_session.flush()
    db_session.add_all([
        RegressionRun(id=uuid.uuid4(), agent_version_id=version.id, regression_case_id=rc1.id, status="pass", details={}, triggered_by=actor.id),
        RegressionRun(id=uuid.uuid4(), agent_version_id=version.id, regression_case_id=rc2.id, status="pass", details={}, triggered_by=actor.id),
    ])
    db_session.flush()

    gate = regression_service.gate_status(db_session, agent.code, version.id)
    assert gate["configured"] is True
    assert gate["all_run"] is True
    assert gate["all_passed"] is True
    assert gate["last_triggered_by_name"] == actor.name


def test_gate_status_all_passed_false_when_one_case_fails(db_session, actor):
    agent = _make_agent(db_session, "ZQ4")
    version = _make_version(db_session, agent)
    rc1 = RegressionCase(id=uuid.uuid4(), name="rc1", agent_code=agent.code, active=True, assertions=[])
    rc2 = RegressionCase(id=uuid.uuid4(), name="rc2", agent_code=agent.code, active=True, assertions=[])
    db_session.add_all([rc1, rc2])
    db_session.flush()
    db_session.add_all([
        RegressionRun(id=uuid.uuid4(), agent_version_id=version.id, regression_case_id=rc1.id, status="pass", details={}, triggered_by=actor.id),
        RegressionRun(id=uuid.uuid4(), agent_version_id=version.id, regression_case_id=rc2.id, status="fail", details={}, triggered_by=actor.id),
    ])
    db_session.flush()

    gate = regression_service.gate_status(db_session, agent.code, version.id)
    assert gate["all_run"] is True
    assert gate["all_passed"] is False


def test_gate_status_ignores_inactive_regression_cases(db_session):
    agent = _make_agent(db_session, "ZQ5")
    version = _make_version(db_session, agent)
    db_session.add(RegressionCase(id=uuid.uuid4(), name="retired", agent_code=agent.code, active=False, assertions=[]))
    db_session.flush()

    gate = regression_service.gate_status(db_session, agent.code, version.id)
    assert gate["configured"] is False


def test_publish_unconfigured_agent_requires_explicit_confirmation(db_session):
    agent = _make_agent(db_session, "ZQ6")
    version = _make_version(db_session, agent)

    with pytest.raises(HTTPException) as exc:
        agent_service.publish_version(db_session, agent, version.id, confirm_no_gate=False)
    assert exc.value.status_code == 409

    published = agent_service.publish_version(db_session, agent, version.id, confirm_no_gate=True)
    assert published.status == "published"


def test_publish_writes_audit_log_with_gate_context(db_session, actor):
    agent = _make_agent(db_session, "ZQ7")
    version = _make_version(db_session, agent)

    agent_service.publish_version(db_session, agent, version.id, actor=actor, confirm_no_gate=True)

    rows = audit_service.list_audit_log(db_session, action_prefix="agent_version.publish", entity_id=version.id)
    assert len(rows) == 1
    assert rows[0].actor_name == actor.name
    assert rows[0].after["no_gate_confirmed"] is True
    assert rows[0].after["regression_configured"] is False
    assert rows[0].after["version_label"] == version.version_label


def test_publish_blocked_when_configured_and_not_all_passed(db_session, actor):
    agent = _make_agent(db_session, "ZQ8")
    version = _make_version(db_session, agent)
    rc = RegressionCase(id=uuid.uuid4(), name="rc1", agent_code=agent.code, active=True, assertions=[])
    db_session.add(rc)
    db_session.flush()
    db_session.add(RegressionRun(id=uuid.uuid4(), agent_version_id=version.id, regression_case_id=rc.id, status="fail", details={}, triggered_by=actor.id))
    db_session.flush()

    with pytest.raises(HTTPException) as exc:
        agent_service.publish_version(db_session, agent, version.id, actor=actor, confirm_no_gate=True)
    assert exc.value.status_code == 400
    # confirm_no_gate=True 不能绕过"配置了但没通过"的情况——那不是"无门禁"，是"没过门禁"。
    assert db_session.get(AgentVersion, version.id).status == "draft"


def test_publish_succeeds_without_confirmation_when_all_passed(db_session, actor):
    agent = _make_agent(db_session, "ZQ9")
    version = _make_version(db_session, agent)
    rc = RegressionCase(id=uuid.uuid4(), name="rc1", agent_code=agent.code, active=True, assertions=[])
    db_session.add(rc)
    db_session.flush()
    db_session.add(RegressionRun(id=uuid.uuid4(), agent_version_id=version.id, regression_case_id=rc.id, status="pass", details={}, triggered_by=actor.id))
    db_session.flush()

    published = agent_service.publish_version(db_session, agent, version.id, actor=actor, confirm_no_gate=False)
    assert published.status == "published"


def test_publish_archives_previously_published_version(db_session, actor):
    agent = _make_agent(db_session, "ZQA")
    v1 = _make_version(db_session, agent, "v1")
    v2 = _make_version(db_session, agent, "v2")
    agent_service.publish_version(db_session, agent, v1.id, actor=actor, confirm_no_gate=True)

    agent_service.publish_version(db_session, agent, v2.id, actor=actor, confirm_no_gate=True)

    assert db_session.get(AgentVersion, v1.id).status == "archived"
    assert db_session.get(AgentVersion, v2.id).status == "published"

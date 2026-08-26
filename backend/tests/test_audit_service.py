"""app.services.audit_service — the write/read halves of the shared audit
trail. See app/db/models/audit.py for why this table existed unused for a
long time before 《交互体验优化需求》 gave it real callers.
"""
import uuid

from app.services.audit_service import list_audit_log, write_audit


def test_write_audit_persists_all_fields(db_session, actor):
    entity_id = uuid.uuid4()
    row = write_audit(
        db_session, actor=actor, action="setting.llm_provider",
        entity_type="app_setting", entity_id=entity_id,
        before={"provider": "kimi"}, after={"provider": "minimax"},
    )
    assert row.id is not None
    assert row.actor_id == actor.id
    assert row.action == "setting.llm_provider"
    assert row.entity_type == "app_setting"
    assert row.entity_id == entity_id
    assert row.before == {"provider": "kimi"}
    assert row.after == {"provider": "minimax"}
    assert row.at is not None


def test_write_audit_actor_name_follows_relationship(db_session, actor):
    row = write_audit(db_session, actor=actor, action="agent_version.publish", entity_type="agent_version")
    assert row.actor_name == actor.name


def test_write_audit_allows_no_actor(db_session):
    """系统触发、或调用方没拿到登录用户时，actor 可以是 None——不应该报错。"""
    row = write_audit(db_session, actor=None, action="system.something", entity_type="x")
    assert row.actor_id is None
    assert row.actor_name is None


def test_list_audit_log_filters_by_action_prefix(db_session, actor):
    write_audit(db_session, actor=actor, action="setting.llm_provider", entity_type="app_setting")
    write_audit(db_session, actor=actor, action="agent_version.publish", entity_type="agent_version")

    settings_rows = list_audit_log(db_session, action_prefix="setting.")
    assert {r.action for r in settings_rows} == {"setting.llm_provider"}

    publish_rows = list_audit_log(db_session, action_prefix="agent_version.")
    assert {r.action for r in publish_rows} == {"agent_version.publish"}


def test_list_audit_log_filters_by_entity_type_and_entity_id(db_session, actor):
    # 用一个本次测试独有的 action 前缀过滤，避免和真实系统里已经产生的
    # entity_type="agent_version" 审计记录（例如真的发布过的版本）混在一起——
    # 这些记录是别的连接已经 commit 过的，测试事务的隔离看不到它们被回滚。
    action = f"test.entity_filter.{uuid.uuid4().hex[:8]}"
    e1, e2 = uuid.uuid4(), uuid.uuid4()
    write_audit(db_session, actor=actor, action=action, entity_type="agent_version", entity_id=e1)
    write_audit(db_session, actor=actor, action=action, entity_type="agent_version", entity_id=e2)
    write_audit(db_session, actor=actor, action=action, entity_type="regression_run", entity_id=e1)

    by_type = list_audit_log(db_session, action_prefix=action, entity_type="agent_version")
    assert len(by_type) == 2

    by_entity = list_audit_log(db_session, action_prefix=action, entity_type="agent_version", entity_id=e1)
    assert len(by_entity) == 1
    assert by_entity[0].entity_id == e1


def test_list_audit_log_orders_by_at_descending(db_session, actor):
    # Postgres 的 now() 在同一事务内是常量（不是 clock_timestamp()），测试事务里
    # 两次写入的 at 经常完全相等——这里只断言"非递增"这个排序契约本身，
    # 不依赖两行的 at 恰好不同。
    first = write_audit(db_session, actor=actor, action="ordering.test", entity_type="x")
    second = write_audit(db_session, actor=actor, action="ordering.test", entity_type="x")

    rows = list_audit_log(db_session, action_prefix="ordering.")
    assert {r.id for r in rows} == {first.id, second.id}
    ats = [r.at for r in rows]
    assert ats == sorted(ats, reverse=True)


def test_list_audit_log_respects_limit(db_session, actor):
    for _ in range(5):
        write_audit(db_session, actor=actor, action="limit.test", entity_type="x")
    rows = list_audit_log(db_session, action_prefix="limit.", limit=2)
    assert len(rows) == 2

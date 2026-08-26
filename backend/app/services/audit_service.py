"""Write side and read side of the shared audit trail (app.db.models.audit.
AuditLog). Built out per 《交互体验优化需求》的产品决策——发布门禁、模型
切换这些"高风险操作必须留痕"的要求，都落在这一张表上，而不是各自发明一套
记录方式。

`action` 用 "entity.verb" 的 dot 记法（如 "agent_version.publish"、
"setting.llm_provider"），方便前缀过滤；`entity_type`/`entity_id` 指向
被操作的具体记录；`before`/`after` 是可选的前后快照，不是所有 action 都
需要——没有就传 None。
"""
import uuid

from sqlalchemy.orm import Session

from app.db.models.audit import AuditLog
from app.db.models.user import User


def write_audit(
    db: Session,
    *,
    actor: User | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None = None,
    before: dict | None = None,
    after: dict | None = None,
) -> AuditLog:
    """插入并立刻 commit——审计记录不应该跟随调用方那个更大的事务一起
    回滚：即使后续业务逻辑失败，"有人试图做过这个操作"这件事本身也该留下来。
    调用方如果确实需要原子性（这条审计记录和它描述的变更必须同生共死），
    在调用处自己控制事务边界，这里保持简单。"""
    row = AuditLog(
        actor_id=actor.id if actor else None,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before=before,
        after=after,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_audit_log(
    db: Session,
    *,
    action_prefix: str | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    limit: int = 100,
) -> list[AuditLog]:
    q = db.query(AuditLog)
    if action_prefix:
        q = q.filter(AuditLog.action.like(f"{action_prefix}%"))
    if entity_type:
        q = q.filter(AuditLog.entity_type == entity_type)
    if entity_id:
        q = q.filter(AuditLog.entity_id == entity_id)
    return q.order_by(AuditLog.at.desc()).limit(min(limit, 500)).all()

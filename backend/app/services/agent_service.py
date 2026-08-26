"""Prompt console business logic: version history and publish/rollback.

No approval gate by design (see project decision log) — saving creates a
draft, publishing is a single click that immediately goes live for the
next pipeline run. The safety net is that every version is kept forever
and rollback is just "publish an older one again", not a separate code path.
"""
import re
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.db.models.agent import Agent, AgentVersion, ScenarioType, UserPersona
from app.db.models.user import User
from app.schemas.agent import AgentVersionCreate, ScenarioTypeCreate, ScenarioTypeUpdate, UserPersonaCreate, UserPersonaUpdate
from app.services import regression_service
from app.services.audit_service import write_audit


def list_agents(db: Session) -> list[Agent]:
    return db.query(Agent).order_by(Agent.code).all()


def get_agent_or_404(db: Session, code: str) -> Agent:
    agent = db.query(Agent).filter(Agent.code == code.upper()).first()
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"没有这个 Agent：{code}")
    return agent


def published_version_label(db: Session, agent: Agent) -> str | None:
    v = (
        db.query(AgentVersion)
        .filter(AgentVersion.agent_id == agent.id, AgentVersion.status == "published")
        .order_by(AgentVersion.published_at.desc())
        .first()
    )
    return v.version_label if v else None


def list_versions(db: Session, agent: Agent) -> list[AgentVersion]:
    return db.query(AgentVersion).filter(AgentVersion.agent_id == agent.id).order_by(AgentVersion.created_at.desc()).all()


def _next_version_label(db: Session, agent: Agent) -> str:
    labels = [v.version_label for v in db.query(AgentVersion.version_label).filter(AgentVersion.agent_id == agent.id).all()]
    nums = [int(m.group(1)) for label in labels if (m := re.fullmatch(r"v(\d+)", label))]
    return f"v{(max(nums) + 1) if nums else 1}"


def create_version(db: Session, agent: Agent, data: AgentVersionCreate, actor: User) -> AgentVersion:
    version = AgentVersion(
        agent_id=agent.id,
        version_label=_next_version_label(db, agent),
        prompt_text=data.prompt_text,
        out_schema=data.out_schema,
        checks=data.checks,
        status="draft",
        created_by=actor.id,
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    return version


def publish_version(
    db: Session, agent: Agent, version_id: uuid.UUID,
    actor: User | None = None, confirm_no_gate: bool = False,
) -> AgentVersion:
    """发布门禁（《交互体验优化需求》P0-1 产品决策，"强门禁 + 明确例外"）：
    - 这个 Agent 配置了回归用例：最近一次回归必须全通过，否则拒绝发布。
    - 没配置回归用例：允许发布，但调用方必须显式传 confirm_no_gate=True——
      前端对应一个"无回归门禁发布"的确认弹窗，不能悄悄跳过。
    两种情况都写一条 AuditLog，留下"谁在什么门禁状态下发布了哪个版本"。
    """
    target = db.query(AgentVersion).filter(AgentVersion.id == version_id, AgentVersion.agent_id == agent.id).first()
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "这个版本不存在")

    gate = regression_service.gate_status(db, agent.code, target.id)
    if gate["configured"]:
        if not gate["all_passed"]:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "该版本最近一次回归未全部通过（或部分用例从未在该版本上跑过），不能发布。请先修复并重新运行回归。",
            )
    elif not confirm_no_gate:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "这个 Agent 还没有配置回归用例，发布不会经过任何回归门禁。请先确认「无回归门禁发布」后再试一次。",
        )

    currently_published = (
        db.query(AgentVersion).filter(AgentVersion.agent_id == agent.id, AgentVersion.status == "published").all()
    )
    for v in currently_published:
        v.status = "archived"

    target.status = "published"
    target.published_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(target)

    write_audit(
        db, actor=actor, action="agent_version.publish",
        entity_type="agent_version", entity_id=target.id,
        after={
            "agent_code": agent.code,
            "version_label": target.version_label,
            "regression_configured": gate["configured"],
            "regression_all_passed": gate["all_passed"] if gate["configured"] else None,
            "no_gate_confirmed": (not gate["configured"]) and confirm_no_gate,
        },
    )
    return target


# --- scenario library ------------------------------------------------------

def list_scenario_types(db: Session) -> list[ScenarioType]:
    return db.query(ScenarioType).order_by(ScenarioType.code).all()


def get_scenario_type_or_404(db: Session, scenario_id: uuid.UUID) -> ScenarioType:
    st = db.get(ScenarioType, scenario_id)
    if st is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "这个场景类型不存在")
    return st


def create_scenario_type(db: Session, data: ScenarioTypeCreate, actor: User) -> ScenarioType:
    if db.query(ScenarioType).filter(ScenarioType.code == data.code).first():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"场景类型 code「{data.code}」已存在")
    st = ScenarioType(**data.model_dump(), created_by=actor.id)
    db.add(st)
    db.commit()
    db.refresh(st)
    return st


def update_scenario_type(db: Session, scenario_id: uuid.UUID, data: ScenarioTypeUpdate) -> ScenarioType:
    st = get_scenario_type_or_404(db, scenario_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(st, field, value)
    db.commit()
    db.refresh(st)
    return st


# --- user persona library ---------------------------------------------------
# 4 个固定候选（患者/家属 × 低/较高认知）是业务方跑测方案里的既定设计，见
# app/seed_personas.py——这里的 CRUD 是让"改一条画像的行为准则"或"临时停用
# 某个画像"不用再改源码重跑种子脚本，跟场景库的维护方式对齐。code 定死
# 不让改（Agent F 的 schema 里 persona_code 是枚举，改了 code 等于换了一个
# 画像，应该新建而不是编辑）。

def list_personas(db: Session) -> list[UserPersona]:
    return db.query(UserPersona).order_by(UserPersona.code).all()


def get_persona_or_404(db: Session, persona_id: uuid.UUID) -> UserPersona:
    p = db.get(UserPersona, persona_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "这个用户画像不存在")
    return p


def create_persona(db: Session, data: UserPersonaCreate) -> UserPersona:
    if db.query(UserPersona).filter(UserPersona.code == data.code).first():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"画像 code「{data.code}」已存在")
    p = UserPersona(**data.model_dump())
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def update_persona(db: Session, persona_id: uuid.UUID, data: UserPersonaUpdate) -> UserPersona:
    p = get_persona_or_404(db, persona_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(p, field, value)
    db.commit()
    db.refresh(p)
    return p

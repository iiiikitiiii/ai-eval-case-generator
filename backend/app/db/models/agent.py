"""Global, version-controlled pipeline definitions — what the 页面二
Prompt 维护后台 edits. Nothing here is per-case; cases only ever
reference an `agent_versions.id` to record which version produced them.
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class UserPersona(Base):
    """固定的候选用户画像轴：角色（患者本人/家属）× 医学认知（低/较高），
    来自《专病管家跑测方案》的"统一候选用户画像"设计——四套画像是全局共用
    的标准轴，不是每条用例各造一套。behavior_guideline 是这一档画像的通用
    行为准则（如"较高认知≠表达完整清晰，仍允许信息断续、顺序跳跃"），
    F 生成每条用例时在此基础上写出该场景下的具体表现（persona_note）。"""

    __tablename__ = "user_personas"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(20), unique=True)  # patient_low | patient_high | family_low | family_high
    role: Mapped[str] = mapped_column(String(10))  # patient | family
    cognition: Mapped[str] = mapped_column(String(10))  # low | high
    name: Mapped[str] = mapped_column(String(40))  # 患者本人·低认知
    behavior_guideline: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Agent(Base):
    """One of the six pipeline roles: S0 (场景库, no LLM call) / A / B / C / D / F."""

    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(4), unique=True)  # S0 | A | B | C | D | F
    name: Mapped[str] = mapped_column(String(60))
    kind: Mapped[str] = mapped_column(String(12))  # prereq | extract | fabricate | generate
    oneline: Mapped[str | None] = mapped_column(Text, nullable=True)

    versions: Mapped[list["AgentVersion"]] = relationship(back_populates="agent", cascade="all, delete-orphan")


class AgentVersion(Base):
    """A saved prompt + schema + validation-rule snapshot. Saving = a new row;
    publishing = flipping `status` to `published` and unpublishing the
    previous one — no separate approval step (see design decision:
    "不要审批"), but every version stays queryable for rollback/diff.
    """

    __tablename__ = "agent_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"))
    version_label: Mapped[str] = mapped_column(String(20))  # v1.4 等，同一 agent 下唯一
    prompt_text: Mapped[str] = mapped_column(Text)
    in_schema: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    out_schema: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    checks: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)      # 自动校验规则，人类可读
    fails: Mapped[list[dict]] = mapped_column(JSONB, default=list)            # [{trigger, handling}]
    status: Mapped[str] = mapped_column(String(12), default="draft")          # draft | published | archived
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    agent: Mapped["Agent"] = relationship(back_populates="versions")


class ScenarioType(Base):
    """S0 场景库：人工定义、非 agent 生成的评价维度分类。

    从阶段 1 的 7 条占位示例，替换成了《专病管家测评标准-场景清单+标准.xlsx》
    里的 49 条真实场景（见 app/import_scenario_standards.py）——scenario_number
    是那份表里的"场景编号"，用来在重新导入时做幂等匹配，也是和 standard_cards
    关联的稳定外键。source/consultation_volume 是那份表里真实存在的字段
    （场景来源、场景数量），axis/feature_scenario 是本项目自己加的两个维度，
    业务表里没有对应数据，暂时留空。
    """

    __tablename__ = "scenario_types"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    scenario_number: Mapped[int | None] = mapped_column(nullable=True, unique=True)  # 源表"场景编号"，导入幂等键
    name: Mapped[str] = mapped_column(String(120))  # 测试场景（用户角度的需求场景），源表"用户场景"
    axis: Mapped[str] = mapped_column(String(10))  # peer | patient
    journey_stages: Mapped[list[str]] = mapped_column(ARRAY(String(4)), default=list)  # 适用的 J01..J08
    feature_scenario: Mapped[str | None] = mapped_column(String(120), nullable=True)  # 对应的产品功能场景（待业务侧补）
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 医学覆盖补充 | 实际客户咨询
    consultation_volume: Mapped[int | None] = mapped_column(nullable=True)  # 源表"场景数量"，"—" 记为 null
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    standard_card: Mapped["StandardCard | None"] = relationship(back_populates="scenario_type", uselist=False)


class RegressionCase(Base):
    """一个金标准病例 + 一组断言，新 prompt 版本发布前的门禁。

    agent_code 限定这组断言是验证哪个 agent 的输出——同一个金标准病例可以
    有多条 RegressionCase，分别验证 A 的抽取质量、B 的阶段映射质量等，
    不是一份笼统的"这个病例整体对不对"。
    """

    __tablename__ = "regression_cases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(80))
    agent_code: Mapped[str] = mapped_column(String(4))  # S0 | A | B | C | D | F
    golden_case_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=True)
    assertions: Mapped[list[dict]] = mapped_column(JSONB, default=list)  # [{description, check, path, expected}]
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class RegressionRun(Base):
    __tablename__ = "regression_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="CASCADE"))
    regression_case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("regression_cases.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(10))  # pass | fail
    details: Mapped[dict] = mapped_column(JSONB, default=dict)  # per-assertion pass/fail + diff
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    triggered_by_user = relationship("User")

    @property
    def triggered_by_name(self) -> str | None:
        return self.triggered_by_user.name if self.triggered_by_user else None

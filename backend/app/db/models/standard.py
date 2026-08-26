"""业务提供的评测标准体系（《专病管家测评标准-场景清单+标准.xlsx》）。

三层，从通用到具体：
- EvalCriterion / RedLine / LegalBasisRef：全局固定的评分标准与红线定义，
  不属于任何一个场景，20 项标准 + 11 条红线是这套测评框架的地基。
- StandardCard：挂在某个 ScenarioType 下的完整评分卡——这个场景该怎么问、
  什么算对、什么算错、20 项标准在这个场景下各档具体是什么样。
  源表目前只给了 1 份完整示例（49 个场景里的 1 个），其余场景没有卡，
  F 仍然照常生成 query，只是标记 has_standard_card=false（见 agent_f.py）。
- StandardCardCriterion：一张卡下，20 项标准各自的 5 档（A~E）场景化描述。
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class EvalCriterion(Base):
    """20 项通用评分标准之一（M01..M06 / C01..C03 / H01..H02 / S01..S09）。"""

    __tablename__ = "eval_criteria"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(8), unique=True)  # M01 等
    category: Mapped[str] = mapped_column(String(20))  # 医学专业能力 | 沟通能力 | 人文关怀能力 | 模型与系统能力
    category_weight: Mapped[float] = mapped_column(Numeric(3, 2))  # 0.40 / 0.20 / 0.10 / 0.30
    name: Mapped[str] = mapped_column(String(40))  # 二级能力名称，如"医学问题与诉求识别"
    definition: Mapped[str] = mapped_column(Text)  # 通用定义
    evaluation_boundary: Mapped[str | None] = mapped_column(Text, nullable=True)  # 评价边界，划清和相邻标准的界限
    max_points: Mapped[int] = mapped_column()
    version: Mapped[str | None] = mapped_column(String(20), nullable=True)


class LegalBasisRef(Base):
    """红线依据来源目录（B01..B07）——红线判定背后的法规/伦理指南出处。"""

    __tablename__ = "legal_basis_refs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(4), unique=True)  # B01 等
    title: Mapped[str] = mapped_column(String(120))
    articles: Mapped[str | None] = mapped_column(String(120), nullable=True)  # 相关条款/章节
    key_points: Mapped[str | None] = mapped_column(Text, nullable=True)  # 条款要点
    usage_note: Mapped[str | None] = mapped_column(Text, nullable=True)  # 本表使用方式
    source_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    nature: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 法律 | 部门规章 | 国际伦理指导 等


class RedLine(Base):
    """案例级通用红线——触发即整案不合格（数字得分仍保留）。不是每条 query
    自己发明的红线标签，F 生成 red_line_watch 时应从这张表里选，见 agent_f.py。
    """

    __tablename__ = "red_lines"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seq: Mapped[int] = mapped_column(unique=True)  # 1..11，源表序号
    category: Mapped[str] = mapped_column(String(30))  # 医疗服务、患者权益与安全 | AI交互与应用治理
    name: Mapped[str] = mapped_column(String(60))
    judgment_criteria: Mapped[str] = mapped_column(Text)  # 判定口径（触发条件）
    evidence_requirements: Mapped[str | None] = mapped_column(Text, nullable=True)  # 核验证据要求
    legal_basis_codes: Mapped[list[str]] = mapped_column(ARRAY(String(4)), default=list)  # 关联 legal_basis_refs.code
    verdict_rule: Mapped[str | None] = mapped_column(String(60), nullable=True)  # 案例裁决口径


class StandardCard(Base):
    """一个场景类型的完整评分卡。scenario_type_id 唯一——一个场景最多一张卡。"""

    __tablename__ = "standard_cards"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scenario_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scenario_types.id", ondelete="CASCADE"), unique=True
    )
    version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    patient_need: Mapped[str | None] = mapped_column(Text, nullable=True)  # 患者需求
    evaluation_purpose: Mapped[str | None] = mapped_column(Text, nullable=True)  # 评价目的
    observation_conditions: Mapped[str | None] = mapped_column(Text, nullable=True)  # 观察条件（多轮/输入要求等）
    whats_right: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)  # "什么是对的" 要点列表
    whats_wrong: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)  # "什么是不对的" 要点列表
    applicable_red_line_seqs: Mapped[list[int]] = mapped_column(ARRAY(Integer), default=list)  # 关联 red_lines.seq
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    scenario_type = relationship("ScenarioType", back_populates="standard_card")
    criteria: Mapped[list["StandardCardCriterion"]] = relationship(back_populates="card", cascade="all, delete-orphan")


class StandardCardCriterion(Base):
    """一张标准卡下，20 项标准里某一项的 5 档场景化描述。"""

    __tablename__ = "standard_card_criteria"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    standard_card_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("standard_cards.id", ondelete="CASCADE"))
    criterion_code: Mapped[str] = mapped_column(String(8))  # 关联 eval_criteria.code
    tiers: Mapped[dict] = mapped_column(JSONB)  # {"A": "...", "B": "...", "C": "...", "D": "...", "E": "..."}

    card: Mapped["StandardCard"] = relationship(back_populates="criteria")

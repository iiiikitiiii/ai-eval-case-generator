"""Per-case pipeline tables — everything the 病例工坊 (Case Workshop) wizard
reads and writes for a single case.

Cross-references between tables (e.g. "which documents back this flag")
use the document's `seq` (its 1..N ordinal within the case), not a UUID
foreign key — this mirrors the shape the extraction agents already emit
(`involved_docs: [int]`, `docs: [int]` in the Pipeline prototype's output
schemas), so agent output can be persisted close to as-is.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Index,
    ForeignKey,
    String,
    Text,
    Boolean,
    DateTime,
    Integer,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CaseStatus(str, enum.Enum):
    queued = "queued"                    # 已建档，流水线尚未开始
    extracting = "extracting"            # Agent A 抽取中
    reviewing_flags = "reviewing_flags"  # 工坊步骤: a 核对冲突
    staging = "staging"                  # 工坊步骤: b 阶段裁定
    mock_review = "mock_review"          # 工坊步骤: d 推测抽查
    cutpoint_review = "cutpoint_review"  # 工坊步骤: f 裂点用例
    exported = "exported"                # 工坊步骤: out 已产出
    blocked = "blocked"                  # 流水线失败，需人工介入（见 PipelineRun.error）


# 与前端向导的 6 个步骤 key 完全对应，便于按 case.current_step 直接路由。
WORKSHOP_STEPS = ["up", "a", "b", "d", "f", "out"]


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)  # 如 CONG-2024
    alias: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)  # 团队检索用的非敏感展示标签，不做唯一性约束
    patient_meta: Mapped[dict] = mapped_column(JSONB, default=dict)  # name/gender/age/dx/hospital/span...
    status: Mapped[str] = mapped_column(String(20), default=CaseStatus.queued.value)
    current_step: Mapped[str] = mapped_column(String(8), default="up")
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    documents: Mapped[list["Document"]] = relationship(back_populates="case", cascade="all, delete-orphan", order_by="Document.seq")
    review_flags: Mapped[list["ReviewFlag"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    stage_map: Mapped[list["StageMap"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    boundary_decisions: Mapped[list["BoundaryDecision"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    persona_fields: Mapped[list["PersonaField"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    mock_entries: Mapped[list["MockEntry"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    cutpoints: Mapped[list["Cutpoint"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    pipeline_runs: Mapped[list["PipelineRun"]] = relationship(back_populates="case", cascade="all, delete-orphan")


class Document(Base):
    """Agent A 的抽取结果：一份原始病历单据 → 一条结构化记录。"""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)  # 病例内 1..N 序号，供其它表引用
    source_file: Mapped[str | None] = mapped_column(String(255), nullable=True)  # MinIO object key
    content_type: Mapped[str | None] = mapped_column(String(60), nullable=True)  # image/jpeg 等，喂给视觉模型要用
    document_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    exam_time: Mapped[str | None] = mapped_column(String(40), nullable=True)   # 原文日期，保留非规范格式
    report_time: Mapped[str | None] = mapped_column(String(40), nullable=True)
    exam_items: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    structured_info: Mapped[dict] = mapped_column(JSONB, default=dict)  # 姓名/性别/年龄/科室/床号...（可含 null）
    core_abnormality: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_full_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[dict] = mapped_column(JSONB, default=dict)  # {"ocr": float, "fields": float}
    agent_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("agent_versions.id"), nullable=True)

    case: Mapped["Case"] = relationship(back_populates="documents")


class ReviewFlag(Base):
    """跨病历不一致 / 疑似 OCR 错误等，工坊步骤 a 的核对对象。"""

    __tablename__ = "review_flags"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(60))       # 跨病历不一致 / 段落错行 / 字段缺失 / 日期异常
    field: Mapped[str] = mapped_column(String(60))
    detail: Mapped[str] = mapped_column(Text)
    why: Mapped[str | None] = mapped_column(Text, nullable=True)
    involved_docs: Mapped[list[int]] = mapped_column(ARRAY(Integer), default=list)
    severity: Mapped[str] = mapped_column(String(10))  # high | medium | low
    decision: Mapped[str | None] = mapped_column(String(10), nullable=True)  # confirm | ignore
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    case: Mapped["Case"] = relationship(back_populates="review_flags")


class StageMap(Base):
    """一个病例的 J01..J08 旅程阶段覆盖状态，工坊步骤 b 的裁定对象。"""

    __tablename__ = "stage_map"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"))
    stage_code: Mapped[str] = mapped_column(String(4))  # J01..J08
    status: Mapped[str] = mapped_column(String(16))     # covered | not_applicable | real_gap | uncovered
    docs: Mapped[list[int]] = mapped_column(ARRAY(Integer), default=list)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)  # real_gap/not_applicable 分类需人工确认
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    case: Mapped["Case"] = relationship(back_populates="stage_map")


class BoundaryDecision(Base):
    """一份单据卡在两个阶段边界上时（如 C1/C4），需要人工裁定归属。"""

    __tablename__ = "boundary_decisions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"))
    doc_seq: Mapped[int] = mapped_column(Integer)
    assigned_stage: Mapped[str] = mapped_column(String(4))
    alternative_stage: Mapped[str] = mapped_column(String(4))
    rule_applied: Mapped[str | None] = mapped_column(String(120), nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    alt_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    needs_human: Mapped[bool] = mapped_column(Boolean, default=True)
    resolved_stage: Mapped[str | None] = mapped_column(String(4), nullable=True)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    case: Mapped["Case"] = relationship(back_populates="boundary_decisions")


class PersonaField(Base):
    """Agent C 的组合事实：可追溯到具体单据的患者画像字段。"""

    __tablename__ = "persona_fields"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"))
    field: Mapped[str] = mapped_column(String(60))
    value: Mapped[str] = mapped_column(Text)
    source: Mapped[list[int]] = mapped_column(ARRAY(Integer), default=list)
    flag: Mapped[str | None] = mapped_column(String(20), nullable=True)  # inconsistent | null

    case: Mapped["Case"] = relationship(back_populates="persona_fields")


class MockEntry(Base):
    """Agent D 的推测数据：未覆盖阶段的编造条目，工坊步骤 d 逐条抽查。"""

    __tablename__ = "mock_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"))
    stage_code: Mapped[str] = mapped_column(String(4))
    date_label: Mapped[str | None] = mapped_column(String(60), nullable=True)  # 含"（推测）"字样的原文日期
    title: Mapped[str] = mapped_column(String(120))
    desc: Mapped[str | None] = mapped_column(Text, nullable=True)
    clinical_basis: Mapped[str] = mapped_column(Text)  # 必填：推测依据，不是结论
    strength: Mapped[str] = mapped_column(String(10))  # strong | medium | weak
    conditional: Mapped[bool] = mapped_column(Boolean, default=False)
    disclaimer: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision: Mapped[str | None] = mapped_column(String(10), nullable=True)  # pass | reject
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    agent_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("agent_versions.id"), nullable=True)

    case: Mapped["Case"] = relationship(back_populates="mock_entries")


class Cutpoint(Base):
    """一个信息状态断点，工坊步骤 f 的最终产出单元；下挂若干 query（每个
    query 对应一个适用的场景类型）。

    type_code（"C1 结果已出、定性未明"这类分类）是可为空的历史字段——
    早期版本发明了一套 C1-C6 六类裂点分类，业务方任何文档里都没有这个
    概念，字段留着只是不破坏 2026-08 之前生产的历史数据；F 现在不再要求
    也不再生成这个分类，裂点直接按 stage_code（业务方真实六阶段旅程，
    见 import_scenario_standards.SIX_STAGE_CODES）+ 该阶段下适用的场景
    类型来组织，不再叠加一层分类。"""

    __tablename__ = "cutpoints"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"))
    stage_code: Mapped[str] = mapped_column(String(4))
    type_code: Mapped[str | None] = mapped_column(String(80), nullable=True)  # 已弃用，见上方 docstring
    provenance: Mapped[str] = mapped_column(String(10))  # real | mock
    anchor: Mapped[dict] = mapped_column(JSONB, default=dict)  # {after, before, time}
    known_set: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    unknown_set: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    judgment: Mapped[str | None] = mapped_column(Text, nullable=True)  # tested_judgment
    validity_check: Mapped[dict] = mapped_column(JSONB, default=dict)  # {askable, gradeable, discriminating}
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)  # 人工"引用/弃用整个裂点"
    agent_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("agent_versions.id"), nullable=True)

    case: Mapped["Case"] = relationship(back_populates="cutpoints")
    queries: Mapped[list["Query"]] = relationship(back_populates="cutpoint", cascade="all, delete-orphan")


class Query(Base):
    """一条候选测试用例。参照《专病管家跑测方案》的真实设计：一条用例 = 一个
    裂点 × 一个场景，但真正发给被测产品的不是一句话，而是若干套"候选画像
    脚本"（QueryVariant，患者本人/家属 × 低/较高认知），每套脚本是多轮对话
    + 一段贯穿始终的行为逻辑。text 字段退化成列表页用的一句话摘要，完整
    内容都在 variants 里。"""

    __tablename__ = "queries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cutpoint_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cutpoints.id", ondelete="CASCADE"))
    scenario_type: Mapped[str] = mapped_column(String(60))  # 对应 scenario_types.code
    text: Mapped[str] = mapped_column(Text)  # 列表摘要：通常是所选画像 R1 的第一句
    test_direction: Mapped[str | None] = mapped_column(Text, nullable=True)  # 这条用例具体测什么角度
    test_background: Mapped[str | None] = mapped_column(Text, nullable=True)  # 病例与测试背景（人读，不发给被测产品）
    test_image_seqs: Mapped[list[int]] = mapped_column(ARRAY(Integer), default=list)  # 要发给被测产品的图片（case.documents.seq 的子集）
    test_image_note: Mapped[str | None] = mapped_column(Text, nullable=True)  # 补充说明，如"仅发送此图""不发送：xxx"
    expected_answer_points: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    red_line_watch: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    has_standard_card: Mapped[bool] = mapped_column(Boolean, default=False)  # 生成时该场景是否已有标准卡（严谨评分依据）
    decision: Mapped[str] = mapped_column(String(10), default="accept")  # accept | reject
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)  # 批量"不纳入"时可选填写，跟 decision 一起清空/写入
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    cutpoint: Mapped["Cutpoint"] = relationship(back_populates="queries")
    variants: Mapped[list["QueryVariant"]] = relationship(back_populates="query", cascade="all, delete-orphan")


class QueryVariant(Base):
    """一条用例在某个候选画像下的完整脚本：多轮对话 + 贯穿的行为逻辑。
    "方案A-D 是同一用例的候选脚本，不等同新增用例"——四套画像共享同一个
    Query（同一个 expected_answer_points/red_line_watch/test_images），
    只是对话怎么问、怎么摇摆、怎么表达不一样。"""

    __tablename__ = "query_variants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    query_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("queries.id", ondelete="CASCADE"))
    persona_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user_personas.id"))
    persona_note: Mapped[str] = mapped_column(Text)  # 这个画像在本场景下的具体表现，如"不理解冰冻、石蜡和免疫组化的关系"
    turns: Mapped[list[dict]] = mapped_column(JSONB, default=list)  # [{"round": 1, "messages": [str], "note": str|null}]
    behavior_logic: Mapped[str] = mapped_column(Text)  # 贯穿多轮的行为演变，含"AI 需要怎么处理"
    selected: Mapped[bool] = mapped_column(Boolean, default=False)  # 人工挑选：这次实际跑测用哪套画像

    query: Mapped["Query"] = relationship(back_populates="variants")
    persona: Mapped["UserPersona"] = relationship()

    @property
    def persona_code(self) -> str | None:
        return self.persona.code if self.persona else None

    @property
    def persona_name(self) -> str | None:
        return self.persona.name if self.persona else None


ACTIVE_DYNAMIC_CONVERSATION_STATUSES = (
    "awaiting_response",
    "generating",
    "generation_failed",
)


class DynamicConversation(Base):
    """Persist one account's dynamic run independently of regenerated queries.

    Query and variant UUIDs intentionally are not foreign keys because Agent F
    replaces those source rows on rerun. The context snapshot keeps completed
    and in-progress conversation history auditable after such a replacement.
    """

    __tablename__ = "dynamic_conversations"
    __table_args__ = (
        # Multiple unfinished runs may share an account and query. Every later
        # mutation is scoped by the durable conversation UUID instead.
        Index("ix_dynamic_conversations_query_id", "query_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    query_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    variant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    started_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    # Optional account-owned label makes repeated runs distinguishable without
    # changing the immutable query/persona identifiers captured by the run.
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="awaiting_response")
    current_round: Mapped[int] = mapped_column(Integer, default=1)
    context_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict)
    stop_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    turns: Mapped[list["DynamicConversationTurn"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="DynamicConversationTurn.round",
    )


class DynamicConversationTurn(Base):
    """Store one generated user turn and the tested product's answer."""

    __tablename__ = "dynamic_conversation_turns"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "round",
            name="uq_dynamic_conversation_turns_conversation_round",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dynamic_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    round: Mapped[int] = mapped_column(Integer, nullable=False)
    user_messages: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    # Internal per-turn intent lets later generation understand why each prior
    # question was asked without exposing test rationale to the tested system.
    question_goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Keep answer expectations beside the exact question they evaluate. This
    # lets later turns distinguish the case-wide rubric from each turn's focus.
    expected_answer_points: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    image_seqs: Mapped[list[int]] = mapped_column(ARRAY(Integer), default=list)
    tested_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Store only durable object references and integrity metadata in Postgres;
    # the potentially large reply screenshots remain in the existing MinIO.
    tested_response_images: Mapped[list[dict]] = mapped_column(JSONB, default=list)
    # Preserve the model's transcription of reply screenshots so later turns
    # retain their textual meaning even though prior images are not replayed.
    tested_response_raw_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(8))  # seed | llm
    token_usage: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    conversation: Mapped[DynamicConversation] = relationship(back_populates="turns")


class PipelineRun(Base):
    """每一次 Agent 调用的审计轨迹：谁跑的、跑了哪个版本、结果如何。

    也是失败恢复的落点——一步失败，病例进 blocked 状态，人工可在这里看到
    具体在哪个 agent、用的哪个 prompt 版本、报错是什么。
    """

    __tablename__ = "pipeline_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"))
    agent_code: Mapped[str] = mapped_column(String(4))  # S0 | A | B | C | D | F
    agent_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("agent_versions.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="queued")  # queued|running|succeeded|failed
    input_ref: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    output_ref: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # 模型一边"思考"一边流式写进来的轻量进度——不是完整对话记录，只是
    # reasoning_content 的滚动快照，每隔几秒覆盖一次（不是追加），给运行中
    # 页面一个"看得见的活人在干活"而不是干等一个转圈的状态。跑完/失败后
    # 就没有再更新的意义了，留在这一行供事后查看那次到底在想什么。
    progress_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # {"provider": "minimax", "model": "MiniMax-M3", "prompt_tokens": int,
    #  "completion_tokens": int, "total_tokens": int}——供看板汇总用量、
    # 也是将来算成本的唯一真实数据源，不是估算。请求 stream_options.
    # include_usage 之后模型才会在流的最后一个 chunk 里带这个字段，见
    # llm_client._stream_openai_compatible；调用失败/模型没返回 usage 时
    # 这里就是 null，不强求。
    token_usage: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    case: Mapped["Case"] = relationship(back_populates="pipeline_runs")

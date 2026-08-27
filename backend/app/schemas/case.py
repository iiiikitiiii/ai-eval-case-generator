import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, computed_field


class CaseCreate(BaseModel):
    patient_meta: dict[str, Any] = {}
    alias: str | None = None


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    seq: int
    content_type: str | None = None
    document_type: str | None
    exam_time: str | None
    report_time: str | None
    exam_items: list[str]
    structured_info: dict[str, Any]
    core_abnormality: str | None
    ocr_full_text: str | None
    confidence: dict[str, Any]


class ReviewFlagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: str
    field: str
    detail: str
    why: str | None
    involved_docs: list[int]
    severity: str
    decision: str | None
    decided_by: uuid.UUID | None
    decided_at: datetime | None


class FlagDecisionIn(BaseModel):
    decision: Literal["confirm", "ignore"]


class AdvanceStepIn(BaseModel):
    target_step: Literal["a", "b", "d", "f", "out"]


class RunAgentFIn(BaseModel):
    # 不传或传空 = 用全部启用中的画像/场景（跟以前的行为一致）；
    # 传了就只用选中的那部分，省 token 也省人工筛选的功夫。
    persona_codes: list[str] | None = None
    scenario_codes: list[str] | None = None


class StageMapOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    stage_code: str
    status: str
    docs: list[int]
    reason: str | None


class BoundaryDecisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    doc_seq: int
    assigned_stage: str
    alternative_stage: str
    rule_applied: str | None
    rationale: str | None
    needs_human: bool
    resolved_stage: str | None
    resolved_by: uuid.UUID | None
    resolved_at: datetime | None


class BoundaryResolveIn(BaseModel):
    resolved_stage: str


class PersonaFieldOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    field: str
    value: str
    source: list[int]
    flag: str | None


class MockEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    stage_code: str
    date_label: str | None
    title: str
    desc: str | None
    clinical_basis: str
    strength: str
    disclaimer: str | None
    decision: str | None
    decided_by: uuid.UUID | None
    decided_at: datetime | None


class MockDecisionIn(BaseModel):
    decision: Literal["pass", "reject"]


class TurnOut(BaseModel):
    round: int
    messages: list[str]
    note: str | None = None


class QueryVariantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    persona_id: uuid.UUID
    persona_code: str | None = None
    persona_name: str | None = None
    persona_note: str
    turns: list[TurnOut]
    behavior_logic: str
    selected: bool


class VariantSelectIn(BaseModel):
    selected: bool


class QueryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    scenario_type: str
    text: str
    test_direction: str | None = None
    test_background: str | None = None
    test_image_seqs: list[int] = []
    test_image_note: str | None = None
    expected_answer_points: list[str]
    red_line_watch: list[str]
    has_standard_card: bool = False
    decision: str
    reject_reason: str | None = None
    decided_by: uuid.UUID | None
    decided_at: datetime | None
    variants: list[QueryVariantOut] = []


class QueryDecisionIn(BaseModel):
    decision: Literal["accept", "reject"]
    reason: str | None = None  # 只在 decision=reject 时保留，见 case_service.decide_query


class CutpointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    stage_code: str
    type_code: str | None = None  # 已弃用字段，见 db 模型 docstring
    provenance: str
    anchor: dict[str, Any]
    known_set: list[str]
    unknown_set: list[str]
    judgment: str | None
    validity_check: dict[str, Any]
    enabled: bool
    queries: list[QueryOut] = []


class CutpointToggleIn(BaseModel):
    enabled: bool


class CaseListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_no: str
    alias: str | None = None
    patient_meta: dict[str, Any]
    status: str
    current_step: str
    created_at: datetime
    updated_at: datetime
    document_count: int = 0
    pending_flag_count: int = 0
    # 下面两个不是 ORM 列，由 router 用 case_service.todo_label/last_failed_step 填充——
    # P1「队列首屏可看出下一步需要人工介入的病例」。
    todo_label: str = "—"
    last_failed_step: str | None = None


class CaseDetail(CaseListItem):
    documents: list[DocumentOut] = []
    flags: list[ReviewFlagOut] = []
    stage_map: list[StageMapOut] = []
    boundary_decisions: list[BoundaryDecisionOut] = []
    persona: list[PersonaFieldOut] = []
    mocks: list[MockEntryOut] = []
    cutpoints: list[CutpointOut] = []


class PipelineRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_code: str
    agent_version_label: str | None = None
    status: str
    error: str | None
    output_ref: dict[str, Any] | None
    progress_note: str | None = None
    token_usage: dict[str, Any] | None = None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime

    @computed_field
    @property
    def duration_seconds(self) -> float | None:
        if self.started_at and self.finished_at:
            return round((self.finished_at - self.started_at).total_seconds(), 1)
        return None

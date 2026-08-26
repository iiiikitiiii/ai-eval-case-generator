import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class BoardCaseItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    case_no: str
    patient_meta: dict[str, Any]
    status: str
    current_step: str
    pending_flag_count: int = 0
    accepted_query_count: int = 0
    updated_at: datetime


class BoardTestCaseItem(BaseModel):
    case_id: uuid.UUID
    case_no: str
    cutpoint_id: uuid.UUID
    query_id: uuid.UUID
    journey_stage: str
    cutpoint_type: str | None  # 已弃用字段（C1-C6），2026-08 之后生成的裂点是 null
    provenance: str
    scenario_type: str
    scenario_name: str | None = None  # P1「默认展示业务名称」，router 用场景库回填
    query_text: str
    decision: str
    reject_reason: str | None = None
    decided_by: uuid.UUID | None = None  # None = Agent F 产出后从没人工审过（"已纳入"只是默认值，不是人工确认）
    decided_at: datetime | None


class BatchQueryDecisionIn(BaseModel):
    query_ids: list[uuid.UUID]
    decision: str  # accept | reject
    reason: str | None = None  # 只在 decision=reject 时保留


class BatchQueryDecisionOut(BaseModel):
    decided_count: int


class CoverageCell(BaseModel):
    journey_stage: str
    scenario_type: str
    scenario_name: str
    accepted_real: int
    accepted_mock: int


class QualitySummary(BaseModel):
    case_count: int
    flags_total: int
    flags_by_severity: dict[str, int]
    flags_confirmed: int
    flags_ignored: int
    mocks_total: int
    mocks_passed: int
    mocks_rejected: int
    pipeline_runs_total: int
    pipeline_runs_failed: int
    pipeline_failures_by_agent: dict[str, int]
    accepted_test_case_count: int
    # 真实 token 用量（来自 provider 返回的 usage，不是估算）——只统计
    # 有 token_usage 的运行；老数据（这个字段上线前跑的）和没拿到 usage
    # 的运行不计入，token_usage_run_count 就是"这个总数基于几次运行算出
    # 来的"，避免看着一个总数却不知道它覆盖了多大比例的历史运行。
    token_usage_total: int
    token_usage_run_count: int
    token_usage_by_provider: dict[str, int]
    token_usage_by_agent: dict[str, int]

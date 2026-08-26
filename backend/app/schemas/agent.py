import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    kind: str
    oneline: str | None
    published_version_label: str | None = None


class AgentVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version_label: str
    prompt_text: str
    out_schema: dict[str, Any] | None
    checks: list[str]
    status: str
    created_by: uuid.UUID | None
    created_at: datetime
    published_at: datetime | None
    # 下面几个字段不是 ORM 列，由 router 用 regression_service.gate_status 填充——
    # P0-1 验收标准"已发布版本可在 10 秒内看清其最近验证结果"。
    regression_configured: bool = False
    regression_all_passed: bool = False
    last_regression_at: datetime | None = None
    last_regression_by: str | None = None


class AgentVersionCreate(BaseModel):
    prompt_text: str
    out_schema: dict[str, Any] | None = None
    checks: list[str] = []


class PublishVersionIn(BaseModel):
    # 未配置回归用例的 Agent 允许发布，但前端必须先让用户看到"无回归门禁发布"
    # 的提示并显式勾选/确认，这个字段就是那次确认的回执。
    confirm_no_gate: bool = False


class ScenarioTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    scenario_number: int | None
    name: str
    axis: str
    journey_stages: list[str]
    feature_scenario: str | None
    description: str | None
    source: str | None
    consultation_volume: int | None
    active: bool
    has_standard_card: bool = False


class ScenarioTypeCreate(BaseModel):
    code: str
    name: str
    axis: str
    journey_stages: list[str] = []
    feature_scenario: str | None = None
    description: str | None = None


class ScenarioTypeUpdate(BaseModel):
    name: str | None = None
    axis: str | None = None
    journey_stages: list[str] | None = None
    feature_scenario: str | None = None
    description: str | None = None
    active: bool | None = None


class UserPersonaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    role: str
    cognition: str
    name: str
    behavior_guideline: str
    active: bool


class UserPersonaCreate(BaseModel):
    code: str
    role: str
    cognition: str
    name: str
    behavior_guideline: str


class UserPersonaUpdate(BaseModel):
    name: str | None = None
    behavior_guideline: str | None = None
    active: bool | None = None


class SandboxRunIn(BaseModel):
    case_id: uuid.UUID
    prompt_text: str
    out_schema: dict[str, Any] | None = None


class SandboxRunOut(BaseModel):
    result: dict[str, Any]


class AssertionIn(BaseModel):
    description: str
    check: str  # no_exception | count_gte | count_eq | field_eq | field_contains
    path: list[str | int] = []
    expected: Any = None


class RegressionCaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    agent_code: str
    golden_case_id: uuid.UUID | None
    golden_case_no: str | None = None
    assertions: list[dict[str, Any]]
    active: bool


class RegressionCaseCreate(BaseModel):
    name: str
    agent_code: str
    golden_case_id: uuid.UUID
    assertions: list[AssertionIn]


class AssertionResult(BaseModel):
    description: str
    passed: bool
    detail: str


class RegressionRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    regression_case_id: uuid.UUID
    regression_case_name: str | None = None
    status: str
    details: dict[str, Any]
    run_at: datetime
    triggered_by: uuid.UUID | None = None
    triggered_by_name: str | None = None


class RegressionGateResultOut(BaseModel):
    regression_case_id: uuid.UUID
    regression_case_name: str
    status: str | None  # pass | fail | None（这个版本上从未跑过这条用例）
    run_at: datetime | None


class RegressionGateOut(BaseModel):
    configured: bool
    all_passed: bool
    all_run: bool
    last_run_at: datetime | None
    last_triggered_by_name: str | None
    results: list[RegressionGateResultOut]

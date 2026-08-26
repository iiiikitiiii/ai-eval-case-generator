import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_role
from app.db.models.agent import RegressionCase
from app.db.models.case import Case
from app.db.session import get_db
from app.schemas.agent import (
    AgentOut,
    AgentVersionCreate,
    AgentVersionOut,
    PublishVersionIn,
    RegressionCaseCreate,
    RegressionCaseOut,
    RegressionGateOut,
    RegressionRunOut,
    SandboxRunIn,
    SandboxRunOut,
    ScenarioTypeCreate,
    ScenarioTypeOut,
    ScenarioTypeUpdate,
    UserPersonaCreate,
    UserPersonaOut,
    UserPersonaUpdate,
)
from app.services import agent_service, case_service, regression_service
from app.services.pipeline.common import PipelineError
from app.services.pipeline.sandbox import run_sandbox

router = APIRouter(tags=["agents"])


@router.get("/agents", response_model=list[AgentOut])
def list_agents(db: Session = Depends(get_db), _=Depends(get_current_user)):
    out = []
    for a in agent_service.list_agents(db):
        item = AgentOut.model_validate(a)
        item.published_version_label = agent_service.published_version_label(db, a)
        out.append(item)
    return out


@router.get("/agents/{code}/versions", response_model=list[AgentVersionOut])
def list_versions(code: str, db: Session = Depends(get_db), _=Depends(get_current_user)):
    agent = agent_service.get_agent_or_404(db, code)
    out = []
    for v in agent_service.list_versions(db, agent):
        item = AgentVersionOut.model_validate(v)
        gate = regression_service.gate_status(db, agent.code, v.id)
        item.regression_configured = gate["configured"]
        item.regression_all_passed = gate["all_passed"]
        item.last_regression_at = gate["last_run_at"]
        item.last_regression_by = gate["last_triggered_by_name"]
        out.append(item)
    return out


@router.post("/agents/{code}/versions", response_model=AgentVersionOut, status_code=201)
def create_version(
    code: str, body: AgentVersionCreate,
    db: Session = Depends(get_db), user=Depends(require_role("engineer")),
):
    agent = agent_service.get_agent_or_404(db, code)
    return agent_service.create_version(db, agent, body, user)


@router.get("/agents/{code}/versions/{version_id}/regression-gate", response_model=RegressionGateOut)
def get_regression_gate(
    code: str, version_id: uuid.UUID,
    db: Session = Depends(get_db), _=Depends(get_current_user),
):
    """发布按钮点击前，前端用这个接口判断该弹什么文案——
    全通过就是普通确认，未配置就是"无回归门禁发布"确认，未通过就直接disable。"""
    agent = agent_service.get_agent_or_404(db, code)
    return regression_service.gate_status(db, agent.code, version_id)


@router.post("/agents/{code}/versions/{version_id}/publish", response_model=AgentVersionOut)
def publish_version(
    code: str, version_id: uuid.UUID, body: PublishVersionIn = PublishVersionIn(),
    db: Session = Depends(get_db), user=Depends(require_role("engineer")),
):
    agent = agent_service.get_agent_or_404(db, code)
    return agent_service.publish_version(db, agent, version_id, actor=user, confirm_no_gate=body.confirm_no_gate)


@router.post("/agents/{code}/sandbox", response_model=SandboxRunOut)
async def sandbox_run(
    code: str, body: SandboxRunIn,
    db: Session = Depends(get_db), _=Depends(require_role("engineer")),
):
    """编辑器里的草稿内容（不用先存成版本）直接拿一个真实病例跑一次预览。
    同步阻塞——F 类的调用观察到过跑 4 分钟，这是工程师主动点了等结果的场景，
    跟案例工坊的异步队列不是一回事。"""
    agent_service.get_agent_or_404(db, code)
    case = case_service.get_case_or_404(db, body.case_id)
    try:
        result = await run_sandbox(db, case, code.upper(), body.prompt_text, body.out_schema)
    except PipelineError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return SandboxRunOut(result=result)


@router.get("/agents/{code}/regression-cases", response_model=list[RegressionCaseOut])
def list_regression_cases(code: str, db: Session = Depends(get_db), _=Depends(get_current_user)):
    out = []
    for rc in regression_service.list_regression_cases(db, code.upper()):
        item = RegressionCaseOut.model_validate(rc)
        golden = db.get(Case, rc.golden_case_id) if rc.golden_case_id else None
        item.golden_case_no = golden.case_no if golden else None
        out.append(item)
    return out


@router.post("/agents/{code}/regression-cases", response_model=RegressionCaseOut, status_code=201)
def create_regression_case(
    code: str, body: RegressionCaseCreate,
    db: Session = Depends(get_db), _=Depends(require_role("engineer")),
):
    body.agent_code = code.upper()
    return regression_service.create_regression_case(db, body)


@router.post("/agents/{code}/versions/{version_id}/regression-run", response_model=list[RegressionRunOut])
async def run_regression(
    code: str, version_id: uuid.UUID,
    db: Session = Depends(get_db), user=Depends(require_role("engineer")),
):
    agent = agent_service.get_agent_or_404(db, code)
    version = next((v for v in agent_service.list_versions(db, agent) if v.id == version_id), None)
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "这个版本不存在")
    runs = await regression_service.run_regression_suite(db, version, code.upper(), actor=user)
    return _with_case_names(db, runs)


@router.get("/agents/{code}/versions/{version_id}/regression-runs", response_model=list[RegressionRunOut])
def list_regression_runs(
    code: str, version_id: uuid.UUID,
    db: Session = Depends(get_db), _=Depends(get_current_user),
):
    return _with_case_names(db, regression_service.list_regression_runs_for_version(db, version_id))


def _with_case_names(db: Session, runs: list) -> list[RegressionRunOut]:
    out = []
    for r in runs:
        item = RegressionRunOut.model_validate(r)
        rc = db.get(RegressionCase, r.regression_case_id)
        item.regression_case_name = rc.name if rc else None
        out.append(item)
    return out


@router.get("/scenario-types", response_model=list[ScenarioTypeOut])
def list_scenario_types(db: Session = Depends(get_db), _=Depends(get_current_user)):
    out = []
    for s in agent_service.list_scenario_types(db):
        item = ScenarioTypeOut.model_validate(s)
        item.has_standard_card = s.standard_card is not None
        out.append(item)
    return out


@router.post("/scenario-types", response_model=ScenarioTypeOut, status_code=201)
def create_scenario_type(
    body: ScenarioTypeCreate,
    db: Session = Depends(get_db), user=Depends(require_role("engineer")),
):
    return agent_service.create_scenario_type(db, body, user)


@router.patch("/scenario-types/{scenario_id}", response_model=ScenarioTypeOut)
def update_scenario_type(
    scenario_id: uuid.UUID, body: ScenarioTypeUpdate,
    db: Session = Depends(get_db), _=Depends(require_role("engineer")),
):
    return agent_service.update_scenario_type(db, scenario_id, body)


@router.get("/personas", response_model=list[UserPersonaOut])
def list_personas(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return agent_service.list_personas(db)


@router.post("/personas", response_model=UserPersonaOut, status_code=201)
def create_persona(
    body: UserPersonaCreate,
    db: Session = Depends(get_db), _=Depends(require_role("engineer")),
):
    return agent_service.create_persona(db, body)


@router.patch("/personas/{persona_id}", response_model=UserPersonaOut)
def update_persona(
    persona_id: uuid.UUID, body: UserPersonaUpdate,
    db: Session = Depends(get_db), _=Depends(require_role("engineer")),
):
    return agent_service.update_persona(db, persona_id, body)

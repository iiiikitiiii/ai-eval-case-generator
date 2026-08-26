"""Regression suite: golden case + assertions, the publish-time gate. Runs
the *draft* prompt/schema being edited through app.services.pipeline.sandbox
against each golden case's real data, then checks a handful of mechanical
assertions against the raw output — not free-text "looks right", something
that either passes or doesn't the same way every time.

Assertion shape (JSONB, see schemas.agent.AssertionIn):
  {"description": str, "check": "no_exception"|"count_gte"|"count_eq"|
   "field_eq"|"field_contains", "path": [str|int, ...], "expected": Any}
`path` walks the sandbox result — ["documents"] + count_eq validates
"exactly N documents came back"; ["review_flags", 0, "field"] + field_eq
checks a specific flag's field. Kept deliberately small — this is meant to
catch "the obvious thing broke", not replace human review of the diff.
"""
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.db.models.agent import AgentVersion, RegressionCase, RegressionRun
from app.db.models.case import Case
from app.db.models.user import User
from app.schemas.agent import AssertionIn, RegressionCaseCreate
from app.services.pipeline.common import PipelineError
from app.services.pipeline.sandbox import run_sandbox


def list_regression_cases(db: Session, agent_code: str) -> list[RegressionCase]:
    return db.query(RegressionCase).filter(RegressionCase.agent_code == agent_code).order_by(RegressionCase.name).all()


def create_regression_case(db: Session, data: RegressionCaseCreate) -> RegressionCase:
    golden = db.get(Case, data.golden_case_id)
    if golden is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "指定的金标准病例不存在")
    rc = RegressionCase(
        name=data.name,
        agent_code=data.agent_code,
        golden_case_id=data.golden_case_id,
        assertions=[a.model_dump() for a in data.assertions],
    )
    db.add(rc)
    db.commit()
    db.refresh(rc)
    return rc


def _resolve_path(data: Any, path: list) -> Any:
    cur = data
    for key in path:
        cur = cur[int(key)] if isinstance(cur, list) else cur[key]
    return cur


def _evaluate(result: dict, assertion: dict) -> tuple[bool, str]:
    check = assertion["check"]
    path = assertion.get("path") or []
    try:
        if check == "no_exception":
            return True, "沙盒运行没有抛出异常"
        value = _resolve_path(result, path)
        expected = assertion.get("expected")
        if check == "count_gte":
            ok = len(value) >= expected
        elif check == "count_eq":
            ok = len(value) == expected
        elif check == "field_eq":
            ok = value == expected
        elif check == "field_contains":
            ok = expected in value
        else:
            return False, f"未知校验类型：{check}"
        return ok, f"路径 {path} 实际值：{value!r}（期望 {check} {expected!r}）"
    except (KeyError, IndexError, TypeError) as exc:
        return False, f"路径 {path} 取值失败：{exc}"


async def run_regression_suite(
    db: Session, agent_version: AgentVersion, agent_code: str, actor: User | None = None,
) -> list[RegressionRun]:
    cases = [rc for rc in list_regression_cases(db, agent_code) if rc.active]
    runs: list[RegressionRun] = []

    for rc in cases:
        golden = db.get(Case, rc.golden_case_id) if rc.golden_case_id else None
        details: dict[str, Any] = {"assertions": []}
        overall_ok = True

        if golden is None:
            details["error"] = "金标准病例不存在或已被删除"
            overall_ok = False
        else:
            try:
                result = await run_sandbox(db, golden, agent_code, agent_version.prompt_text, agent_version.out_schema)
                for a in rc.assertions:
                    ok, detail = _evaluate(result, a)
                    details["assertions"].append({"description": a.get("description"), "passed": ok, "detail": detail})
                    overall_ok = overall_ok and ok
            except PipelineError as exc:
                details["error"] = str(exc)
                overall_ok = False

        run = RegressionRun(
            agent_version_id=agent_version.id,
            regression_case_id=rc.id,
            status="pass" if overall_ok else "fail",
            details=details,
            triggered_by=actor.id if actor else None,
        )
        db.add(run)
        runs.append(run)

    db.commit()
    for r in runs:
        db.refresh(r)
    return runs


def list_regression_runs_for_version(db: Session, agent_version_id: UUID) -> list[RegressionRun]:
    return (
        db.query(RegressionRun)
        .filter(RegressionRun.agent_version_id == agent_version_id)
        .order_by(RegressionRun.run_at.desc())
        .all()
    )


def gate_status(db: Session, agent_code: str, agent_version_id: UUID) -> dict:
    """《交互体验优化需求》P0-1 产品决策的落地：
    "已配置回归用例的 Agent：最近一次回归必须全通过才能发布；
     未配置回归用例的 Agent：允许发布，但必须显式确认。"

    "最近一次回归"按每条 RegressionCase 各自最新一次运行判断——一个 case
    从未在这个版本上跑过，视为未通过（不能因为"没跑"就当作"通过"）。
    这个函数同时喂两个地方：publish_version 的强门禁判断，和版本列表要
    展示的"最近回归时间/结果/执行人"。
    """
    active_cases = [rc for rc in list_regression_cases(db, agent_code) if rc.active]
    if not active_cases:
        return {
            "configured": False, "all_passed": False, "all_run": False,
            "last_run_at": None, "last_triggered_by_name": None, "results": [],
        }

    results = []
    all_passed = True
    all_run = True
    last_run_at = None
    last_triggered_by_name = None
    for rc in active_cases:
        latest = (
            db.query(RegressionRun)
            .filter(RegressionRun.agent_version_id == agent_version_id, RegressionRun.regression_case_id == rc.id)
            .order_by(RegressionRun.run_at.desc())
            .first()
        )
        if latest is None:
            all_run = False
            all_passed = False
            results.append({"regression_case_id": rc.id, "regression_case_name": rc.name, "status": None, "run_at": None})
            continue
        results.append({
            "regression_case_id": rc.id, "regression_case_name": rc.name,
            "status": latest.status, "run_at": latest.run_at,
        })
        if latest.status != "pass":
            all_passed = False
        if last_run_at is None or latest.run_at > last_run_at:
            last_run_at = latest.run_at
            last_triggered_by_name = latest.triggered_by_name

    return {
        "configured": True,
        "all_passed": all_passed and all_run,
        "all_run": all_run,
        "last_run_at": last_run_at,
        "last_triggered_by_name": last_triggered_by_name,
        "results": results,
    }

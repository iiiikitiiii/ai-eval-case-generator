import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_role
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.board import (
    BatchQueryDecisionIn,
    BatchQueryDecisionOut,
    BoardCaseItem,
    BoardTestCaseItem,
    CoverageCell,
    QualitySummary,
)
from app.services import board_service
from app.services.export_xlsx import build_test_case_workbook
from app.services.export_zip import build_test_case_zip

router = APIRouter(prefix="/board", tags=["board"])


@router.get("/cases", response_model=list[BoardCaseItem])
def board_cases(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return board_service.list_board_cases(db)


@router.get("/testcases", response_model=list[BoardTestCaseItem])
def board_testcases(
    scenario_type: str | None = None,
    cutpoint_type: str | None = None,
    journey_stage: str | None = None,
    provenance: str | None = None,
    decision: str | None = None,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    return board_service.list_test_cases(
        db,
        scenario_type=scenario_type,
        cutpoint_type=cutpoint_type,
        journey_stage=journey_stage,
        provenance=provenance,
        decision=decision,
    )


@router.get("/export")
def board_export(
    case_ids: str | None = None,
    scenario_type: str | None = None,
    cutpoint_type: str | None = None,
    journey_stage: str | None = None,
    provenance: str | None = None,
    decision: str | None = None,
    format: str = "json",
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """跨病例批量导出——病例看板里勾选几个病例一起导出（case_ids，逗号分隔，
    不传就是全部病例），或者用例库 tab 里直接导出当前筛选结果（其余几个
    参数跟 /board/testcases 是同一套，所见即所得）。两条路径共用这一个
    接口，不是分别维护。"""
    ids = [uuid.UUID(x) for x in case_ids.split(",") if x.strip()] if case_ids else None
    # 纯透传，不在这里猜"该不该默认只要 accept"——case_ids 有没有传不能
    # 可靠区分调用方是病例看板（没有 decision 选择器，前端会显式传
    # decision=accept）还是用例库 tab（决策该跟表格当前筛选一致），两边
    # 都可能不传 case_ids，这个判断只有前端知道自己在哪个界面上。
    filter_kwargs = dict(scenario_type=scenario_type, cutpoint_type=cutpoint_type, journey_stage=journey_stage, provenance=provenance, decision=decision)

    if format == "zip":
        rows = board_service.export_query_rows(db, ids, **filter_kwargs)
        data = build_test_case_zip(db, rows)
        filename = "批量导出-测试用例.zip"
        return Response(
            content=data,
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
        )

    test_cases = board_service.export_test_cases(db, ids, **filter_kwargs)
    if format == "xlsx":
        data = build_test_case_workbook(test_cases)
        filename = "批量导出-测试用例.xlsx"
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
        )
    return {"case_count": len({tc['case_no'] for tc in test_cases}), "test_cases": test_cases}


@router.patch("/queries/batch-decide", response_model=BatchQueryDecisionOut)
def batch_decide_queries(
    body: BatchQueryDecisionIn,
    db: Session = Depends(get_db), user: User = Depends(require_role("reviewer")),
):
    """用例库「批量纳入/不纳入」——跟单条 PATCH /cases/{id}/queries/{id}
    是两个独立的入口（批量走看板，不强求先知道每条用例属于哪个病例），
    但落库语义完全一致，写审计。"""
    n = board_service.batch_decide_queries(db, body.query_ids, body.decision, user, body.reason)
    return BatchQueryDecisionOut(decided_count=n)


@router.get("/coverage", response_model=list[CoverageCell])
def board_coverage(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return board_service.coverage_matrix(db)


@router.get("/quality", response_model=QualitySummary)
def board_quality(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return board_service.quality_summary(db)

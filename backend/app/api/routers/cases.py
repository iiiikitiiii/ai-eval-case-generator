import uuid
from urllib.parse import quote

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.dynamic_query_adapter import (
    advance_next_turn_http,
    list_conversation_history_http,
    rename_conversation_http,
    start_new_conversation_http,
)
from app.api.deps import get_arq_pool, get_current_user, require_role
from app.core.storage import get_object_bytes
from app.db.models.user import User
from app.db.session import get_db
from app.services.export_xlsx import build_test_case_workbook
from app.services.export_zip import build_test_case_zip
from app.schemas.case import (
    AdvanceStepIn,
    BoundaryDecisionOut,
    BoundaryResolveIn,
    CaseCreate,
    CaseDetail,
    CaseListItem,
    CutpointOut,
    CutpointToggleIn,
    FlagDecisionIn,
    MockDecisionIn,
    MockEntryOut,
    PersonaFieldOut,
    PipelineRunOut,
    QueryDecisionIn,
    QueryOut,
    QueryVariantOut,
    ReviewFlagOut,
    RunAgentFIn,
    VariantSelectIn,
)
from app.schemas.dynamic_query import (
    DynamicConversationOut,
    NextTurnOut,
    RenameDynamicConversationIn,
    StartDynamicConversationIn,
)
from app.services import case_service

router = APIRouter(prefix="/cases", tags=["cases"])


def _ensure_query_belongs_to_case(case, query_id: uuid.UUID) -> None:
    """Keep case/query ownership checks identical for all web dynamic routes."""

    if not any(
        query.id == query_id
        for cutpoint in case.cutpoints
        for query in cutpoint.queries
    ):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "用例不存在或不属于该病例",
        )


def _to_list_item(case) -> CaseListItem:
    item = CaseListItem.model_validate(case)
    item.document_count = len(case.documents)
    item.pending_flag_count = case_service.pending_flag_count(case)
    item.todo_label = case_service.todo_label(case)
    item.last_failed_step = case_service.last_failed_step(case)
    return item


def _to_detail(case) -> CaseDetail:
    # model_validate(case) already walks every relationship whose ORM
    # attribute name matches the schema field name (documents, stage_map,
    # boundary_decisions, cutpoints→queries→variants, ...) through each
    # nested *Out schema's from_attributes — that's what turns QueryVariant's
    # persona_code/persona_name *properties* into real JSON fields. Reassigning
    # those fields afterward with the raw ORM lists (as this used to do) throws
    # that validation away and silently serializes half-formed dicts instead.
    # review_flags/persona_fields/mock_entries are the only relationships whose
    # ORM name doesn't match the schema field name, so those three still need
    # an explicit — but still properly validated — assignment.
    detail = CaseDetail.model_validate(case)
    detail.document_count = len(case.documents)
    detail.pending_flag_count = case_service.pending_flag_count(case)
    detail.todo_label = case_service.todo_label(case)
    detail.last_failed_step = case_service.last_failed_step(case)
    detail.stage_map = sorted(detail.stage_map, key=lambda s: s.stage_code)
    detail.flags = [ReviewFlagOut.model_validate(f) for f in case.review_flags]
    detail.persona = [PersonaFieldOut.model_validate(p) for p in case.persona_fields]
    detail.mocks = [MockEntryOut.model_validate(m) for m in case.mock_entries]
    return detail


@router.get("", response_model=list[CaseListItem])
def list_cases(
    status_filter: str | None = None, search: str | None = None,
    db: Session = Depends(get_db), _: User = Depends(get_current_user),
):
    return [_to_list_item(c) for c in case_service.list_cases(db, status_filter, search)]


@router.post("", response_model=CaseDetail, status_code=status.HTTP_201_CREATED)
def create_case(body: CaseCreate, db: Session = Depends(get_db), _: User = Depends(require_role("reviewer"))):
    return _to_detail(case_service.create_case(db, body.patient_meta, body.alias))


@router.get("/{case_id}", response_model=CaseDetail)
def get_case(case_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return _to_detail(case_service.get_case_or_404(db, case_id))


@router.post("/{case_id}/documents", response_model=CaseDetail)
async def upload_documents(
    case_id: uuid.UUID,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_role("reviewer")),
):
    case = case_service.get_case_or_404(db, case_id)
    if not files:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "没有收到任何文件")
    await case_service.add_documents(db, case, files)
    db.refresh(case)
    return _to_detail(case)


@router.delete("/{case_id}/documents/{document_id}", response_model=CaseDetail)
def delete_document(
    case_id: uuid.UUID, document_id: uuid.UUID,
    db: Session = Depends(get_db), _: User = Depends(require_role("reviewer")),
):
    """P1「资料导入前支持整理与确认」——删掉误传的单据。只允许在 Agent A
    运行前操作（case_service.delete_document 会拒绝其它情况），删除后剩
    余单据的 seq 会自动重新连续编号。"""
    case = case_service.get_case_or_404(db, case_id)
    case_service.delete_document(db, case, document_id)
    db.refresh(case)
    return _to_detail(case)


@router.get("/{case_id}/documents/{document_id}/image")
def get_document_image(
    case_id: uuid.UUID, document_id: uuid.UUID,
    db: Session = Depends(get_db), _: User = Depends(get_current_user),
):
    """病例工坊「导入」步骤缩略图 + 病历卡片预览的图片来源。MinIO 不直接
    对前端开放（见 app/core/storage.py），所以图片始终经后端转发，鉴权
    和其它接口一致。"""
    case = case_service.get_case_or_404(db, case_id)
    doc = next((d for d in case.documents if d.id == document_id), None)
    if doc is None or not doc.source_file:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到该文档的原始文件")
    data = get_object_bytes(doc.source_file)
    return Response(content=data, media_type=doc.content_type or "application/octet-stream")


async def _enqueue(case_id: uuid.UUID, agent_code: str, db: Session, pool: ArqRedis, input_ref: dict | None = None) -> PipelineRunOut:
    case = case_service.get_case_or_404(db, case_id)
    run, created = case_service.enqueue_pipeline_run(db, case, agent_code, input_ref)
    if created:
        await pool.enqueue_job("run_pipeline_step", str(run.id), agent_code)
    return PipelineRunOut.model_validate(run)


@router.post("/{case_id}/pipeline/run-a", response_model=PipelineRunOut, status_code=status.HTTP_202_ACCEPTED)
async def run_agent_a_endpoint(case_id: uuid.UUID, db: Session = Depends(get_db), pool: ArqRedis = Depends(get_arq_pool), _: User = Depends(require_role("reviewer"))):
    return await _enqueue(case_id, "A", db, pool)


@router.post("/{case_id}/pipeline/run-b", response_model=PipelineRunOut, status_code=status.HTTP_202_ACCEPTED)
async def run_agent_b_endpoint(case_id: uuid.UUID, db: Session = Depends(get_db), pool: ArqRedis = Depends(get_arq_pool), _: User = Depends(require_role("reviewer"))):
    return await _enqueue(case_id, "B", db, pool)


@router.post("/{case_id}/pipeline/run-c", response_model=PipelineRunOut, status_code=status.HTTP_202_ACCEPTED)
async def run_agent_c_endpoint(case_id: uuid.UUID, db: Session = Depends(get_db), pool: ArqRedis = Depends(get_arq_pool), _: User = Depends(require_role("reviewer"))):
    return await _enqueue(case_id, "C", db, pool)


@router.post("/{case_id}/pipeline/run-d", response_model=PipelineRunOut, status_code=status.HTTP_202_ACCEPTED)
async def run_agent_d_endpoint(case_id: uuid.UUID, db: Session = Depends(get_db), pool: ArqRedis = Depends(get_arq_pool), _: User = Depends(require_role("reviewer"))):
    return await _enqueue(case_id, "D", db, pool)


@router.post("/{case_id}/pipeline/run-f", response_model=PipelineRunOut, status_code=status.HTTP_202_ACCEPTED)
async def run_agent_f_endpoint(
    case_id: uuid.UUID, body: RunAgentFIn | None = None,
    db: Session = Depends(get_db), pool: ArqRedis = Depends(get_arq_pool), _: User = Depends(require_role("reviewer")),
):
    input_ref = {}
    if body and body.persona_codes:
        input_ref["persona_codes"] = body.persona_codes
    if body and body.scenario_codes:
        input_ref["scenario_codes"] = body.scenario_codes
    return await _enqueue(case_id, "F", db, pool, input_ref or None)


@router.get("/{case_id}/pipeline/runs", response_model=list[PipelineRunOut])
def list_pipeline_runs(case_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Trace view data source — every agent invocation for this case, in
    order, with status/timing/error. Read-only to any logged-in role."""
    case = case_service.get_case_or_404(db, case_id)
    return [PipelineRunOut.model_validate(r) for r in case_service.list_pipeline_runs(db, case)]


@router.patch("/{case_id}/flags/{flag_id}", response_model=ReviewFlagOut)
def decide_flag(
    case_id: uuid.UUID, flag_id: uuid.UUID, body: FlagDecisionIn,
    db: Session = Depends(get_db), user: User = Depends(require_role("reviewer")),
):
    case = case_service.get_case_or_404(db, case_id)
    return case_service.decide_flag(db, case, flag_id, body.decision, user)


@router.patch("/{case_id}/boundary/{decision_id}", response_model=BoundaryDecisionOut)
def resolve_boundary(
    case_id: uuid.UUID, decision_id: uuid.UUID, body: BoundaryResolveIn,
    db: Session = Depends(get_db), user: User = Depends(require_role("reviewer")),
):
    case = case_service.get_case_or_404(db, case_id)
    return case_service.resolve_boundary(db, case, decision_id, body.resolved_stage, user)


@router.patch("/{case_id}/mocks/{mock_id}", response_model=MockEntryOut)
def decide_mock(
    case_id: uuid.UUID, mock_id: uuid.UUID, body: MockDecisionIn,
    db: Session = Depends(get_db), user: User = Depends(require_role("reviewer")),
):
    case = case_service.get_case_or_404(db, case_id)
    return case_service.decide_mock(db, case, mock_id, body.decision, user)


@router.patch("/{case_id}/cutpoints/{cutpoint_id}", response_model=CutpointOut)
def toggle_cutpoint(
    case_id: uuid.UUID, cutpoint_id: uuid.UUID, body: CutpointToggleIn,
    db: Session = Depends(get_db), _: User = Depends(require_role("reviewer")),
):
    case = case_service.get_case_or_404(db, case_id)
    return case_service.toggle_cutpoint(db, case, cutpoint_id, body.enabled)


@router.patch("/{case_id}/queries/{query_id}", response_model=QueryOut)
def decide_query(
    case_id: uuid.UUID, query_id: uuid.UUID, body: QueryDecisionIn,
    db: Session = Depends(get_db), user: User = Depends(require_role("reviewer")),
):
    case = case_service.get_case_or_404(db, case_id)
    return case_service.decide_query(db, case, query_id, body.decision, user, body.reason)


@router.get(
    "/{case_id}/queries/{query_id}/dynamic-conversations",
    response_model=list[DynamicConversationOut],
)
def list_dynamic_conversations(
    case_id: uuid.UUID,
    query_id: uuid.UUID,
    variant_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DynamicConversationOut]:
    """List the current account's prior tests for one query and persona."""

    case = case_service.get_case_or_404(db, case_id)
    _ensure_query_belongs_to_case(case, query_id)
    return list_conversation_history_http(
        db=db,
        user=user,
        query_id=query_id,
        variant_id=variant_id,
    )


@router.post(
    "/{case_id}/queries/{query_id}/dynamic-conversations",
    response_model=DynamicConversationOut,
)
def start_dynamic_conversation(
    case_id: uuid.UUID,
    query_id: uuid.UUID,
    body: StartDynamicConversationIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DynamicConversationOut:
    """Start a distinct test while retaining all earlier test histories."""

    case = case_service.get_case_or_404(db, case_id)
    _ensure_query_belongs_to_case(case, query_id)
    return start_new_conversation_http(
        db=db,
        user=user,
        query_id=query_id,
        variant_id=body.variant_id,
    )


@router.patch(
    "/{case_id}/queries/{query_id}/dynamic-conversations/{conversation_id}",
    response_model=DynamicConversationOut,
)
def rename_dynamic_conversation(
    case_id: uuid.UUID,
    query_id: uuid.UUID,
    conversation_id: uuid.UUID,
    body: RenameDynamicConversationIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DynamicConversationOut:
    """Rename one account-owned dynamic test record."""

    case = case_service.get_case_or_404(db, case_id)
    _ensure_query_belongs_to_case(case, query_id)
    return rename_conversation_http(
        db=db,
        user=user,
        query_id=query_id,
        conversation_id=conversation_id,
        name=body.name,
    )


@router.post("/{case_id}/queries/{query_id}/next-turn", response_model=NextTurnOut)
async def advance_dynamic_query(
    case_id: uuid.UUID,
    query_id: uuid.UUID,
    variant_id: uuid.UUID = Form(...),
    # The web app creates runs through /dynamic-conversations, so every
    # subsequent multipart request must identify the exact selected run.
    conversation_id: uuid.UUID = Form(...),
    latest_response: str | None = Form(default=None, max_length=100_000),
    response_images: list[UploadFile] | None = File(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> NextTurnOut:
    """Validate case ownership before delegating to the shared HTTP adapter."""

    case = case_service.get_case_or_404(db, case_id)
    _ensure_query_belongs_to_case(case, query_id)
    return await advance_next_turn_http(
        db=db,
        user=user,
        query_id=query_id,
        variant_id=variant_id,
        latest_response=latest_response,
        response_images=response_images,
        conversation_id=conversation_id,
    )


@router.patch("/{case_id}/variants/{variant_id}", response_model=QueryVariantOut)
def select_variant(
    case_id: uuid.UUID, variant_id: uuid.UUID, body: VariantSelectIn,
    db: Session = Depends(get_db), _: User = Depends(require_role("reviewer")),
):
    case = case_service.get_case_or_404(db, case_id)
    return case_service.select_variant(db, case, variant_id, body.selected)


@router.get("/{case_id}/export")
def export_case(
    case_id: uuid.UUID, format: str = "json",
    db: Session = Depends(get_db), _: User = Depends(get_current_user),
):
    case = case_service.get_case_or_404(db, case_id)

    if format == "zip":
        rows = [(q, cp, case) for cp in case.cutpoints if cp.enabled for q in cp.queries if q.decision == "accept"]
        data = build_test_case_zip(db, rows)
        filename = f"{case.case_no}-测试用例.zip"
        return Response(
            content=data,
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
        )

    test_cases = case_service.export_accepted_queries(db, case)
    if format == "xlsx":
        data = build_test_case_workbook(test_cases)
        filename = f"{case.case_no}-测试用例.xlsx"
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
        )
    return {"case_no": case.case_no, "test_cases": test_cases}


@router.post("/{case_id}/advance", response_model=CaseDetail)
def advance_step(
    case_id: uuid.UUID, body: AdvanceStepIn,
    db: Session = Depends(get_db), user: User = Depends(require_role("reviewer")),
):
    case = case_service.get_case_or_404(db, case_id)
    case_service.advance_step(db, case, body.target_step, user)
    return _to_detail(case)

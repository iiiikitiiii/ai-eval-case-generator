from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_role
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.audit import AuditLogOut
from app.schemas.settings import LlmProviderIn, LlmProviderOut
from app.services import audit_service, settings_service

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/llm-provider", response_model=LlmProviderOut)
def get_llm_provider(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return LlmProviderOut(
        provider=settings_service.get_llm_provider(db),
        options=list(settings_service.SELECTABLE_LLM_PROVIDERS),
    )


@router.put("/llm-provider", response_model=LlmProviderOut)
def set_llm_provider(
    body: LlmProviderIn,
    db: Session = Depends(get_db), user: User = Depends(require_role("engineer")),
):
    provider = settings_service.set_llm_provider(db, body.provider, actor=user)
    return LlmProviderOut(provider=provider, options=list(settings_service.SELECTABLE_LLM_PROVIDERS))


@router.get("/audit-log", response_model=list[AuditLogOut])
def get_audit_log(
    action_prefix: str | None = Query(None),
    entity_type: str | None = Query(None),
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db), _: User = Depends(require_role("engineer")),
):
    return audit_service.list_audit_log(db, action_prefix=action_prefix, entity_type=entity_type, limit=limit)

"""The one runtime-switchable setting today: which LLM backend the pipeline
calls. Selectable from the Prompt 维护后台 page — no restart, no env var
edit. Persisted in Postgres (not an in-memory global) because the actual
LLM calls happen inside the arq worker, a separate OS process from the
FastAPI process that serves the settings page; only a shared DB row is
visible to both.
"""
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.setting import AppSetting
from app.db.models.user import User
from app.services.audit_service import write_audit

LLM_PROVIDER_KEY = "llm_provider"
# 页面上能选的只有这两个——anthropic 仍是代码里保留的备用后端，但不通过
# 这个开关暴露，跟用户的原话对齐："选项有 kimi 和 minimax 两个"。
SELECTABLE_LLM_PROVIDERS = ("minimax", "kimi")


def get_llm_provider(db: Session) -> str:
    row = db.get(AppSetting, LLM_PROVIDER_KEY)
    if row is not None:
        return row.value
    return get_settings().llm_provider


def set_llm_provider(db: Session, provider: str, actor: User | None = None) -> str:
    if provider not in SELECTABLE_LLM_PROVIDERS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"不支持的模型：{provider}（只能是 {'/'.join(SELECTABLE_LLM_PROVIDERS)}）")
    row = db.get(AppSetting, LLM_PROVIDER_KEY)
    previous = row.value if row is not None else get_settings().llm_provider
    if row is None:
        row = AppSetting(key=LLM_PROVIDER_KEY, value=provider)
        db.add(row)
    else:
        row.value = provider
    db.commit()
    # P2-2《交互体验优化需求》：全局模型切换必须留痕（切换时间/操作人/切换前后模型），
    # 因为这一个开关会影响之后所有病例流水线和沙盒试跑用的是哪个模型。
    if previous != provider:
        write_audit(
            db, actor=actor, action="setting.llm_provider",
            entity_type="app_setting", entity_id=None,
            before={"provider": previous}, after={"provider": provider},
        )
    return provider

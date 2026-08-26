"""Generic key/value runtime settings — small, deliberately not modeled per
concern (no dedicated `llm_config` table etc.). The one row that exists today
is `llm_provider`, read by every pipeline agent run so the model backend can
be switched from the Prompt 后台 page without restarting anything: the API
process writes the row, the arq worker process (a separate OS process —
this is the whole reason it's in Postgres and not an in-memory global) reads
it fresh on every run.
"""
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(String(200))

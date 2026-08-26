"""Generic audit trail. Built at phase 0, deliberately, even though the
medical-data compliance requirements were "to be added later" —
retrofitting an audit log onto an existing schema is the expensive kind of
migration; writing rows into an unused-for-now table is not. Went unused
for a long time (the table existed, nothing ever wrote to it) until
《交互体验优化需求》's publish-gate and model-switch-audit items finally
gave it a real caller — see app/services/audit_service.py.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(60))       # e.g. "flag.decide", "agent_version.publish"
    entity_type: Mapped[str] = mapped_column(String(40))  # table name
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    before: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    actor = relationship("User")

    @property
    def actor_name(self) -> str | None:
        return self.actor.name if self.actor else None

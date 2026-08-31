"""Transport-neutral response contract shared by dynamic Query HTTP routes."""
import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class NextTurnOut(BaseModel):
    """Return the next user messages or the completed conversation state."""

    conversation_id: uuid.UUID
    round: int
    messages: list[str]
    images: list[int]
    done: bool
    stop_reason: str | None = None


class StartDynamicConversationIn(BaseModel):
    """Select the exact persona variant for a distinct new test run."""

    variant_id: uuid.UUID


class RenameDynamicConversationIn(BaseModel):
    """Set a concise display name, or clear it with null/blank text."""

    name: str | None = Field(default=None, max_length=120)


class DynamicConversationTurnOut(BaseModel):
    """Expose browseable turn content without object-storage identifiers."""

    round: int
    messages: list[str]
    images: list[int]
    tested_response: str | None
    tested_response_image_count: int
    tested_response_raw_content: str | None
    created_at: datetime
    answered_at: datetime | None


class DynamicConversationOut(BaseModel):
    """Return one account-owned dynamic test with its persisted turn history."""

    conversation_id: uuid.UUID
    variant_id: uuid.UUID
    name: str | None
    status: str
    current_round: int
    stop_reason: str | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None
    turns: list[DynamicConversationTurnOut]

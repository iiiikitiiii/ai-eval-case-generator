"""Public request and response contracts for authenticated integrations."""
import uuid

from pydantic import BaseModel, Field


class NextTurnIn(BaseModel):
    """Select the persona variant and optionally answer the current turn."""

    variant_id: uuid.UUID
    latest_response: str | None = Field(default=None, max_length=100_000)


class NextTurnOut(BaseModel):
    """Return the next user messages or the completed conversation state."""

    conversation_id: uuid.UUID
    round: int
    messages: list[str]
    images: list[int]
    done: bool
    stop_reason: str | None = None

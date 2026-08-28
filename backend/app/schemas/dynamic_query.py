"""Transport-neutral response contract shared by dynamic Query HTTP routes."""
import uuid

from pydantic import BaseModel


class NextTurnOut(BaseModel):
    """Return the next user messages or the completed conversation state."""

    conversation_id: uuid.UUID
    round: int
    messages: list[str]
    images: list[int]
    done: bool
    stop_reason: str | None = None

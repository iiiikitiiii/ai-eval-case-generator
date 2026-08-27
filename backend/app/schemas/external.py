"""Public request/response contracts for authenticated external integrations."""
import uuid

from pydantic import BaseModel, Field


class NextTurnIn(BaseModel):
    """The caller only sends the tested product's latest answer.

    Omitting ``latest_response`` starts a conversation once the server-side
    conversation service is implemented; later calls must provide the answer
    to the most recently generated user turn.
    """

    latest_response: str | None = Field(default=None, max_length=100_000)


class NextTurnOut(BaseModel):
    """Stable response shape reserved for the dynamic next-turn service."""

    conversation_id: uuid.UUID
    round: int
    messages: list[str]
    images: list[int]
    done: bool
    stop_reason: str | None = None

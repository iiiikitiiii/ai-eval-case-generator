"""JWT-protected API surface used by external test runners.

Authentication deliberately reuses ``POST /auth/login`` and the same active
user checks as the web application, so there is only one account lifecycle and
one token-validation path to maintain.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user
from app.db.models.user import User
from app.schemas.external import NextTurnIn, NextTurnOut

router = APIRouter(prefix="/external", tags=["external"])


@router.post(
    "/queries/{query_id}/next-turn",
    response_model=NextTurnOut,
    responses={
        status.HTTP_501_NOT_IMPLEMENTED: {
            "description": "The authenticated API contract exists, but server-side conversation generation is not implemented yet."
        }
    },
)
def next_turn_entry(
    query_id: uuid.UUID,
    body: NextTurnIn,
    _: User = Depends(get_current_user),
) -> NextTurnOut:
    """Reserve the authenticated integration boundary without faking a turn.

    Keeping the explicit 501 until persistence and generation are connected
    prevents an integration test from mistaking a contract stub for a recorded
    conversation. ``query_id`` and ``body`` are intentionally accepted now so
    OpenAPI already exposes the agreed caller contract.
    """

    del query_id, body
    raise HTTPException(
        status.HTTP_501_NOT_IMPLEMENTED,
        "动态多轮会话服务尚未实现；API 入口和 JWT 鉴权已就绪",
    )

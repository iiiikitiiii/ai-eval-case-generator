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


"""
调用格式：
1. POST /auth/login
   Body: {"email": "runner@example.com", "password": "..."}
   从响应的 access_token 字段取得 JWT。
2. POST /external/queries/{query_id}/next-turn
   Headers: Authorization: Bearer <access_token>
            Content-Type: application/json
   首轮 Body: {"latest_response": null}
   后续 Body: {"latest_response": "被测系统对上一轮的实际回答"}
3. 正式实现后的 200 响应格式：
   {
     "conversation_id": "<uuid>", "round": 1,
     "messages": ["本轮应发送的消息"], "images": [1, 2],
     "done": false, "stop_reason": null
   }
当前仅开放并鉴权该契约，因此合法请求返回 501，避免调用方把占位响应
误认为已经生成并保存了一轮对话。
"""

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

"""JWT-protected HTTP adapter used by external test runners.

Authentication deliberately reuses ``POST /auth/login`` and the same active
user checks as the web application, so there is only one account lifecycle and
one token-validation path to maintain. Conversation behavior remains in the
transport-independent dynamic query service for future web-page reuse.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.external import NextTurnIn, NextTurnOut
from app.services import dynamic_query_service

router = APIRouter(prefix="/external", tags=["external"])


"""
调用格式：
1. POST /auth/login
   Body: {"email": "runner@example.com", "password": "..."}
   从响应的 access_token 字段取得 JWT。
2. POST /external/queries/{query_id}/next-turn
   Headers: Authorization: Bearer <access_token>
            Content-Type: application/json
   首轮 Body: {"variant_id": "<uuid>", "latest_response": null}
   后续 Body: {
     "variant_id": "<同一画像 uuid>",
     "latest_response": "被测系统对上一轮的实际回答"
   }
3. 200 响应格式：
   {
     "conversation_id": "<uuid>", "round": 1,
     "messages": ["本轮应发送的消息"], "images": [1, 2],
     "done": false, "stop_reason": null
   }
会话与轮次由服务端持久化，调用方无需保存或传回 conversation_id；路由只
处理 JWT、请求校验和领域异常到 HTTP 状态码的转换。
"""

@router.post(
    "/queries/{query_id}/next-turn",
    response_model=NextTurnOut,
)
async def next_turn_entry(
    query_id: uuid.UUID,
    body: NextTurnIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> NextTurnOut:
    """Translate the external HTTP contract to the shared domain service."""

    try:
        result = await dynamic_query_service.advance_next_turn(
            db=db,
            actor_id=user.id,
            query_id=query_id,
            variant_id=body.variant_id,
            latest_response=body.latest_response,
        )
    except dynamic_query_service.DynamicQueryNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except dynamic_query_service.DynamicQueryConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except dynamic_query_service.DynamicQueryInvalidInput as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except dynamic_query_service.DynamicQueryGenerationTimeout as exc:
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, str(exc)) from exc
    except dynamic_query_service.DynamicQueryGenerationFailed as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return NextTurnOut(
        conversation_id=result.conversation_id,
        round=result.round,
        messages=result.messages,
        images=result.images,
        done=result.done,
        stop_reason=result.stop_reason,
    )

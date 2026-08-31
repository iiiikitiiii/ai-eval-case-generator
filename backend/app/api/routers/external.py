"""JWT-protected HTTP adapter used by external test runners.

Authentication deliberately reuses ``POST /auth/login`` and the same active
user checks as the web application, so there is only one account lifecycle and
one token-validation path to maintain. Conversation behavior remains in the
transport-independent dynamic query service for future web-page reuse.
"""
import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.api.dynamic_query_adapter import advance_next_turn_http
from app.api.deps import get_current_user
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.dynamic_query import NextTurnOut

router = APIRouter(prefix="/external", tags=["external"])


"""
调用格式：
1. POST /auth/login
   Body: {"email": "runner@example.com", "password": "..."}
   从响应的 access_token 字段取得 JWT。
2. POST /external/queries/{query_id}/next-turn
   Headers: Authorization: Bearer <access_token>
            Content-Type: multipart/form-data
   首轮字段: variant_id=<uuid>
   后续字段: variant_id=<同一画像 uuid>
             conversation_id=<首轮响应中的 uuid>
             latest_response=<可选的被测系统文字答复>
             response_images=@reply-1.png（可重复，最多 10 张）
   此接口不再接受 application/json。
3. 200 响应格式：
   {
     "conversation_id": "<uuid>", "round": 1,
     "messages": ["本轮应发送的消息"], "images": [1, 2],
     "done": false, "stop_reason": null
   }
会话与轮次由服务端持久化。省略 conversation_id 的空答复请求会新建测试；
调用方必须保存响应 ID，并在后续轮次传回。路由只处理 JWT、请求校验和
领域异常到 HTTP 状态码的转换。
"""


@router.post(
    "/queries/{query_id}/next-turn",
    response_model=NextTurnOut,
)
async def next_turn_entry(
    query_id: uuid.UUID,
    variant_id: uuid.UUID = Form(...),
    conversation_id: uuid.UUID | None = Form(default=None),
    latest_response: str | None = Form(default=None, max_length=100_000),
    response_images: list[UploadFile] | None = File(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> NextTurnOut:
    """Translate the external HTTP contract to the shared domain service."""

    return await advance_next_turn_http(
        db=db,
        user=user,
        query_id=query_id,
        variant_id=variant_id,
        latest_response=latest_response,
        response_images=response_images,
        conversation_id=conversation_id,
    )

"""Shared FastAPI adapter for internal and external dynamic Query routes.

The domain service stays independent of HTTP. Both route namespaces delegate
multipart reading, domain-error translation and response conversion here so
their behavior cannot drift as the web workflow evolves.
"""
import uuid
from typing import NoReturn

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.db.models.user import User
from app.schemas.dynamic_query import DynamicConversationOut, NextTurnOut
from app.services import dynamic_query_service


async def _read_response_images(
    uploads: list[UploadFile] | None,
) -> list[dynamic_query_service.ResponseImageInput]:
    """Read bounded multipart files into the transport-neutral service type."""

    files = list(uploads or [])
    try:
        if len(files) > dynamic_query_service.MAX_RESPONSE_IMAGES_PER_TURN:
            raise dynamic_query_service.DynamicQueryInvalidInput(
                f"每轮最多上传 {dynamic_query_service.MAX_RESPONSE_IMAGES_PER_TURN} 张回复图片"
            )

        known_sizes = [upload.size for upload in files if upload.size is not None]
        if any(size > dynamic_query_service.MAX_RESPONSE_IMAGE_BYTES for size in known_sizes):
            raise dynamic_query_service.DynamicQueryInvalidInput("单张回复图片不能超过 5 MiB")
        if (
            len(known_sizes) == len(files)
            and sum(known_sizes) > dynamic_query_service.MAX_RESPONSE_IMAGES_TOTAL_BYTES
        ):
            raise dynamic_query_service.DynamicQueryInvalidInput("每轮回复图片总大小不能超过 20 MiB")

        result: list[dynamic_query_service.ResponseImageInput] = []
        for upload in files:
            # Reading one byte past the limit bounds application memory while
            # still letting the core service produce its authoritative error.
            raw = await upload.read(dynamic_query_service.MAX_RESPONSE_IMAGE_BYTES + 1)
            result.append(
                dynamic_query_service.ResponseImageInput(
                    data=raw,
                    content_type=upload.content_type or "",
                )
            )
        return result
    except dynamic_query_service.DynamicQueryError:
        raise
    except Exception as exc:  # noqa: BLE001 — multipart backends expose implementation-specific errors
        raise dynamic_query_service.DynamicQueryInvalidInput("回复图片读取失败") from exc
    finally:
        for upload in files:
            try:
                await upload.close()
            except Exception:  # noqa: BLE001 — cleanup must not replace the request result
                continue


async def advance_next_turn_http(
    *,
    db: Session,
    user: User,
    query_id: uuid.UUID,
    variant_id: uuid.UUID,
    latest_response: str | None,
    response_images: list[UploadFile] | None,
    conversation_id: uuid.UUID | None = None,
) -> NextTurnOut:
    """Adapt one authenticated multipart request to the shared domain service."""

    try:
        image_inputs = await _read_response_images(response_images)
        result = await dynamic_query_service.advance_next_turn(
            db=db,
            actor_id=user.id,
            query_id=query_id,
            variant_id=variant_id,
            latest_response=latest_response,
            response_images=image_inputs,
            conversation_id=conversation_id,
        )
    except dynamic_query_service.DynamicQueryError as exc:
        _raise_http_error(exc)

    return NextTurnOut(
        conversation_id=result.conversation_id,
        round=result.round,
        messages=result.messages,
        images=result.images,
        done=result.done,
        stop_reason=result.stop_reason,
    )


def _raise_http_error(error: dynamic_query_service.DynamicQueryError) -> NoReturn:
    """Map service-layer failures consistently across all dynamic endpoints."""

    if isinstance(error, dynamic_query_service.DynamicQueryNotFound):
        code = status.HTTP_404_NOT_FOUND
    elif isinstance(error, dynamic_query_service.DynamicQueryConflict):
        code = status.HTTP_409_CONFLICT
    elif isinstance(error, dynamic_query_service.DynamicQueryInvalidInput):
        code = status.HTTP_422_UNPROCESSABLE_ENTITY
    elif isinstance(error, dynamic_query_service.DynamicQueryGenerationTimeout):
        code = status.HTTP_504_GATEWAY_TIMEOUT
    else:
        code = status.HTTP_502_BAD_GATEWAY
    raise HTTPException(code, str(error)) from error


def _conversation_out(
    result: dynamic_query_service.ConversationHistory,
) -> DynamicConversationOut:
    """Convert the transport-neutral history record to its HTTP contract."""

    return DynamicConversationOut(
        conversation_id=result.conversation_id,
        variant_id=result.variant_id,
        name=result.name,
        status=result.status,
        current_round=result.current_round,
        stop_reason=result.stop_reason,
        last_error=result.last_error,
        created_at=result.created_at,
        updated_at=result.updated_at,
        finished_at=result.finished_at,
        turns=[turn.__dict__ for turn in result.turns],
    )


def list_conversation_history_http(
    *,
    db: Session,
    user: User,
    query_id: uuid.UUID,
    variant_id: uuid.UUID,
) -> list[DynamicConversationOut]:
    """Adapt account-scoped history browsing to the shared response Schema."""

    try:
        results = dynamic_query_service.list_conversation_history(
            db,
            actor_id=user.id,
            query_id=query_id,
            variant_id=variant_id,
        )
    except dynamic_query_service.DynamicQueryError as exc:
        _raise_http_error(exc)
    return [_conversation_out(result) for result in results]


def start_new_conversation_http(
    *,
    db: Session,
    user: User,
    query_id: uuid.UUID,
    variant_id: uuid.UUID,
) -> DynamicConversationOut:
    """Create one explicit run while retaining earlier tests for browsing."""

    try:
        result = dynamic_query_service.start_new_conversation(
            db,
            actor_id=user.id,
            query_id=query_id,
            variant_id=variant_id,
        )
    except dynamic_query_service.DynamicQueryError as exc:
        _raise_http_error(exc)
    return _conversation_out(result)


def rename_conversation_http(
    *,
    db: Session,
    user: User,
    query_id: uuid.UUID,
    conversation_id: uuid.UUID,
    name: str | None,
) -> DynamicConversationOut:
    """Rename one account-owned test through the neutral core service."""

    try:
        result = dynamic_query_service.rename_conversation(
            db,
            actor_id=user.id,
            query_id=query_id,
            conversation_id=conversation_id,
            name=name,
        )
    except dynamic_query_service.DynamicQueryError as exc:
        _raise_http_error(exc)
    return _conversation_out(result)

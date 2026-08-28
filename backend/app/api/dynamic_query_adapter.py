"""Shared FastAPI adapter for internal and external dynamic Query routes.

The domain service stays independent of HTTP. Both route namespaces delegate
multipart reading, domain-error translation and response conversion here so
their behavior cannot drift as the web workflow evolves.
"""
import uuid

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.db.models.user import User
from app.schemas.dynamic_query import NextTurnOut
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

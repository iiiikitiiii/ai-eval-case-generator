"""MinIO (S3-compatible) object storage for uploaded case documents.

One client, lazily created bucket. No public URLs anywhere — the frontend
never talks to MinIO directly; it goes through the backend so access stays
gated by the same auth as everything else (matters once the "de-identified
sample data" phase ends and this holds real patient images).
"""
from datetime import timedelta
from io import BytesIO

from minio import Minio

from app.core.config import get_settings

settings = get_settings()

_client = Minio(
    settings.s3_endpoint,
    access_key=settings.s3_access_key,
    secret_key=settings.s3_secret_key,
    secure=settings.s3_secure,
)
_bucket_ready = False


def _ensure_bucket() -> None:
    global _bucket_ready
    if _bucket_ready:
        return
    if not _client.bucket_exists(settings.s3_bucket):
        _client.make_bucket(settings.s3_bucket)
    _bucket_ready = True


def put_object(key: str, data: bytes, content_type: str) -> None:
    _ensure_bucket()
    _client.put_object(settings.s3_bucket, key, BytesIO(data), length=len(data), content_type=content_type)


def delete_object(key: str) -> None:
    """用于导入阶段删除误传单据（见 case_service.delete_document）。MinIO 的
    remove_object 对不存在的 key 不报错，调用方不用先查一次是否存在。"""
    _ensure_bucket()
    _client.remove_object(settings.s3_bucket, key)


def get_object_bytes(key: str) -> bytes:
    resp = _client.get_object(settings.s3_bucket, key)
    try:
        return resp.read()
    finally:
        resp.close()
        resp.release_conn()


def presigned_url(key: str, expires_seconds: int = 3600) -> str:
    _ensure_bucket()
    return _client.presigned_get_object(settings.s3_bucket, key, expires=timedelta(seconds=expires_seconds))

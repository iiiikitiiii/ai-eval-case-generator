"""Call the JWT-protected external dynamic Query API.

Examples (run from the repository root):

    # Start a conversation and receive seed R1.
    python tmp/dynamic_query_api_example.py \
        --email runner@example.com \
        --query-id <query-uuid> \
        --variant-id <variant-uuid>

    # Submit a text and image response to generate the next turn.
    python tmp/dynamic_query_api_example.py \
        --email runner@example.com \
        --query-id <query-uuid> \
        --variant-id <variant-uuid> \
        --response "被测系统的文字答复" \
        --image "tmp/download (1).png"

The server restores the active conversation by account and Query, so callers
do not send ``conversation_id`` back. Omit ``--password`` to enter it without
echoing it in the terminal.
"""

from __future__ import annotations

import argparse
import getpass
import json
import mimetypes
from contextlib import ExitStack
from pathlib import Path
from typing import BinaryIO

import httpx


def parse_args() -> argparse.Namespace:
    """Read connection details and one turn of response content."""

    parser = argparse.ArgumentParser(description="调用动态多轮 Query API")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--email", required=True, help="登录账号邮箱")
    parser.add_argument("--password", help="登录密码；省略时安全输入")
    parser.add_argument("--query-id", required=True, help="种子用例 UUID")
    parser.add_argument("--variant-id", required=True, help="画像变体 UUID")
    parser.add_argument("--response", help="被测系统的文字答复")
    parser.add_argument(
        "--image",
        action="append",
        default=[],
        metavar="PATH",
        help="回复图片路径，可重复传入，最多 10 张",
    )
    return parser.parse_args()


def login(client: httpx.Client, email: str, password: str) -> str:
    """Exchange account credentials for the bearer token used by API calls."""

    response = client.post("/auth/login", json={"email": email, "password": password})
    response.raise_for_status()
    return response.json()["access_token"]


def build_multipart(
    stack: ExitStack,
    variant_id: str,
    latest_response: str | None,
    image_paths: list[str],
) -> list[tuple[str, tuple[str | None, str | BinaryIO, str | None]]]:
    """Build ordered multipart fields and keep image handles open for sending."""

    if len(image_paths) > 10:
        raise ValueError("每轮最多上传 10 张图片")

    fields: list[tuple[str, tuple[str | None, str | BinaryIO, str | None]]] = [
        ("variant_id", (None, variant_id, None)),
    ]
    if latest_response and latest_response.strip():
        fields.append(("latest_response", (None, latest_response.strip(), None)))

    for raw_path in image_paths:
        path = Path(raw_path)
        if not path.is_file():
            raise FileNotFoundError(f"图片不存在：{path}")
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        handle = stack.enter_context(path.open("rb"))
        # Repeating the same field name preserves the caller's image order.
        fields.append(("response_images", (path.name, handle, content_type)))
    return fields


def main() -> None:
    """Authenticate and submit either the initial request or one response turn."""

    args = parse_args()
    password = args.password or getpass.getpass("Password: ")
    base_url = args.base_url.rstrip("/")

    with httpx.Client(base_url=base_url, timeout=120.0) as client:
        token = login(client, args.email, password)
        with ExitStack() as stack:
            multipart = build_multipart(
                stack,
                args.variant_id,
                args.response,
                args.image,
            )
            response = client.post(
                f"/external/queries/{args.query_id}/next-turn",
                headers={"Authorization": f"Bearer {token}"},
                files=multipart,
            )
            response.raise_for_status()
            print(json.dumps(response.json(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

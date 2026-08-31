"""Integration tests for JWT-protected dynamic Query HTTP boundaries."""
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.core.security import hash_password
from app.db.models.user import User
from app.db.session import get_db
from app.main import app
from app.services import dynamic_query_service


def test_login_token_reaches_external_next_turn_contract(monkeypatch):
    """A normal account reaches the thin adapter with its issued JWT."""

    password = "external-test-password"
    user = User(
        id=uuid.uuid4(),
        name="外部接口测试账号",
        email=f"external-{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password(password),
        role="reviewer",
        is_active=True,
    )
    class SingleUserDb:
        """Small service-free stand-in for the two user lookups under test."""

        def query(self, _model):
            return self

        def filter(self, *_criteria):
            return self

        def first(self):
            return user

        def get(self, _model, user_id):
            return user if user_id == user.id else None

    # Both the login router and JWT dependency see the same account without
    # requiring PostgreSQL; this test targets authentication plumbing only.
    def override_get_db():
        yield SingleUserDb()

    conversation_id = uuid.uuid4()
    variant_id = "00000000-0000-0000-0000-000000000002"
    query_path = "/external/queries/00000000-0000-0000-0000-000000000001/next-turn"
    calls: list[dict] = []

    async def fake_advance_next_turn(**kwargs):
        # The adapter must pass authenticated identity and request fields to
        # the reusable service without implementing conversation logic itself.
        assert kwargs["actor_id"] == user.id
        if kwargs["conversation_id"] is None and (
            kwargs["latest_response"] is not None or kwargs["response_images"]
        ):
            raise dynamic_query_service.DynamicQueryInvalidInput(
                "提交答复时必须传 conversation_id"
            )
        calls.append(kwargs)
        return dynamic_query_service.NextTurnResult(
            conversation_id=conversation_id,
            round=1,
            messages=["种子首轮"],
            images=[1],
            done=False,
        )

    monkeypatch.setattr(
        "app.services.dynamic_query_service.advance_next_turn",
        fake_advance_next_turn,
    )
    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        login = client.post(
            "/auth/login",
            json={"email": user.email, "password": password},
        )
        assert login.status_code == 200
        token = login.json()["access_token"]

        # Form fields passed through the files collection force multipart even
        # when the first turn has no actual file attachment.
        response = client.post(
            query_path,
            headers={"Authorization": f"Bearer {token}"},
            files=[("variant_id", (None, variant_id))],
        )
        assert response.status_code == 200, response.text
        assert response.json() == {
            "conversation_id": str(conversation_id),
            "round": 1,
            "messages": ["种子首轮"],
            "images": [1],
            "done": False,
            "stop_reason": None,
        }
        assert "raw_content" not in response.json()
        assert calls[-1]["latest_response"] is None
        assert calls[-1]["response_images"] == []
        assert calls[-1]["conversation_id"] is None

        missing_conversation_id = client.post(
            query_path,
            headers={"Authorization": f"Bearer {token}"},
            files=[
                ("variant_id", (None, variant_id)),
                ("latest_response", (None, "遗漏会话 ID 的答复")),
            ],
        )
        assert missing_conversation_id.status_code == 422

        text_only = client.post(
            query_path,
            headers={"Authorization": f"Bearer {token}"},
            files=[
                ("variant_id", (None, variant_id)),
                ("conversation_id", (None, str(conversation_id))),
                ("latest_response", (None, "纯文字答复")),
            ],
        )
        assert text_only.status_code == 200
        assert calls[-1]["latest_response"] == "纯文字答复"
        assert calls[-1]["response_images"] == []
        assert calls[-1]["conversation_id"] == conversation_id

        png_1 = b"\x89PNG\r\n\x1a\nfirst"
        png_2 = b"\x89PNG\r\n\x1a\nsecond"
        image_only = client.post(
            query_path,
            headers={"Authorization": f"Bearer {token}"},
            files=[
                ("variant_id", (None, variant_id)),
                ("conversation_id", (None, str(conversation_id))),
                ("response_images", ("first.png", png_1, "image/png")),
                ("response_images", ("second.png", png_2, "image/png")),
            ],
        )
        assert image_only.status_code == 200
        assert calls[-1]["latest_response"] is None
        assert [image.data for image in calls[-1]["response_images"]] == [png_1, png_2]
        assert [image.content_type for image in calls[-1]["response_images"]] == [
            "image/png",
            "image/png",
        ]

        combined = client.post(
            query_path,
            headers={"Authorization": f"Bearer {token}"},
            files=[
                ("variant_id", (None, variant_id)),
                ("conversation_id", (None, str(conversation_id))),
                ("latest_response", (None, "文字和截图答复")),
                ("response_images", ("reply.png", png_1, "image/png")),
            ],
        )
        assert combined.status_code == 200
        assert calls[-1]["latest_response"] == "文字和截图答复"
        assert calls[-1]["response_images"][0].data == png_1

        # The endpoint intentionally no longer accepts the former JSON body.
        json_response = client.post(
            query_path,
            headers={"Authorization": f"Bearer {token}"},
            json={"variant_id": variant_id, "latest_response": None},
        )
        assert json_response.status_code == 422

        invalid_variant = client.post(
            query_path,
            headers={"Authorization": f"Bearer {token}"},
            files=[("variant_id", (None, "not-a-uuid"))],
        )
        assert invalid_variant.status_code == 422

        call_count = len(calls)
        too_many_images = client.post(
            query_path,
            headers={"Authorization": f"Bearer {token}"},
            files=[
                ("variant_id", (None, variant_id)),
                *[
                    ("response_images", (f"reply-{index}.png", png_1, "image/png"))
                    for index in range(11)
                ],
            ],
        )
        assert too_many_images.status_code == 422
        assert len(calls) == call_count

        oversized = b"\x89PNG\r\n\x1a\n" + b"x" * dynamic_query_service.MAX_RESPONSE_IMAGE_BYTES
        oversized_image = client.post(
            query_path,
            headers={"Authorization": f"Bearer {token}"},
            files=[
                ("variant_id", (None, variant_id)),
                ("response_images", ("oversized.png", oversized, "image/png")),
            ],
        )
        assert oversized_image.status_code == 422
        assert "5 MiB" in oversized_image.json()["detail"]
        assert len(calls) == call_count

        without_jwt = client.post(
            query_path,
            files=[("variant_id", (None, variant_id))],
        )
        assert without_jwt.status_code == 401

        async def fake_conflict(**kwargs):
            raise dynamic_query_service.DynamicQueryConflict("会话状态冲突")

        monkeypatch.setattr(
            dynamic_query_service,
            "advance_next_turn",
            fake_conflict,
        )
        conflict = client.post(
            query_path,
            headers={"Authorization": f"Bearer {token}"},
            files=[
                ("variant_id", (None, variant_id)),
                ("conversation_id", (None, str(conversation_id))),
                ("latest_response", (None, "测试答复")),
            ],
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"] == "会话状态冲突"

        error_cases = [
            (dynamic_query_service.DynamicQueryNotFound("不存在"), 404),
            (dynamic_query_service.DynamicQueryInvalidInput("输入无效"), 422),
            (dynamic_query_service.DynamicQueryGenerationFailed("生成失败"), 502),
            (dynamic_query_service.DynamicQueryGenerationTimeout("生成超时"), 504),
        ]
        for domain_error, expected_status in error_cases:
            async def fake_error(**kwargs):
                raise domain_error

            monkeypatch.setattr(dynamic_query_service, "advance_next_turn", fake_error)
            error_response = client.post(
                query_path,
                headers={"Authorization": f"Bearer {token}"},
                files=[("variant_id", (None, variant_id))],
            )
            assert error_response.status_code == expected_status
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_case_scoped_next_turn_checks_query_and_reuses_multipart_adapter(monkeypatch):
    """The web route adds case ownership without changing multipart behavior."""

    password = "internal-dynamic-test-password"
    user = User(
        id=uuid.uuid4(),
        name="网页动态接口测试账号",
        email=f"internal-{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password(password),
        role="engineer",
        is_active=True,
    )

    class SingleUserDb:
        """Serve authentication lookups while case retrieval is mocked below."""

        def query(self, _model):
            return self

        def filter(self, *_criteria):
            return self

        def first(self):
            return user

        def get(self, _model, user_id):
            return user if user_id == user.id else None

    def override_get_db():
        yield SingleUserDb()

    case_id = uuid.uuid4()
    query_id = uuid.uuid4()
    variant_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    case = SimpleNamespace(
        cutpoints=[SimpleNamespace(queries=[SimpleNamespace(id=query_id)])],
    )
    monkeypatch.setattr("app.services.case_service.get_case_or_404", lambda _db, _id: case)
    calls: list[dict] = []

    async def fake_advance_next_turn(**kwargs):
        calls.append(kwargs)
        return dynamic_query_service.NextTurnResult(
            conversation_id=conversation_id,
            round=2,
            messages=["动态第二轮"],
            images=[],
            done=False,
        )

    monkeypatch.setattr(dynamic_query_service, "advance_next_turn", fake_advance_next_turn)
    now = datetime.now(timezone.utc)
    history = dynamic_query_service.ConversationHistory(
        conversation_id=conversation_id,
        variant_id=variant_id,
        name=None,
        status="awaiting_response",
        current_round=1,
        stop_reason=None,
        last_error=None,
        created_at=now,
        updated_at=now,
        finished_at=None,
        turns=[dynamic_query_service.ConversationTurnHistory(
            round=1,
            messages=["种子第一轮"],
            images=[1],
            tested_response=None,
            tested_response_image_count=1,
            tested_response_raw_content="截图中的被测系统原始回复",
            created_at=now,
            answered_at=None,
        )],
    )
    history_calls: list[tuple[str, dict]] = []

    def fake_list_history(_db, **kwargs):
        history_calls.append(("list", kwargs))
        return [history]

    def fake_start_history(_db, **kwargs):
        history_calls.append(("start", kwargs))
        return history

    def fake_rename_history(_db, **kwargs):
        history_calls.append(("rename", kwargs))
        return replace(history, name=kwargs["name"])

    monkeypatch.setattr(dynamic_query_service, "list_conversation_history", fake_list_history)
    monkeypatch.setattr(dynamic_query_service, "start_new_conversation", fake_start_history)
    monkeypatch.setattr(dynamic_query_service, "rename_conversation", fake_rename_history)
    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        login = client.post("/auth/login", json={"email": user.email, "password": password})
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        png_1 = b"\x89PNG\r\n\x1a\nfirst"
        png_2 = b"\x89PNG\r\n\x1a\nsecond"

        response = client.post(
            f"/cases/{case_id}/queries/{query_id}/next-turn",
            headers=headers,
            files=[
                ("variant_id", (None, str(variant_id))),
                ("conversation_id", (None, str(conversation_id))),
                ("latest_response", (None, "网页端混合答复")),
                ("response_images", ("first.png", png_1, "image/png")),
                ("response_images", ("second.png", png_2, "image/png")),
            ],
        )
        assert response.status_code == 200, response.text
        assert response.json()["messages"] == ["动态第二轮"]
        assert calls[-1]["actor_id"] == user.id
        assert calls[-1]["query_id"] == query_id
        assert calls[-1]["variant_id"] == variant_id
        assert calls[-1]["conversation_id"] == conversation_id
        assert calls[-1]["latest_response"] == "网页端混合答复"
        assert [image.data for image in calls[-1]["response_images"]] == [png_1, png_2]

        history_response = client.get(
            f"/cases/{case_id}/queries/{query_id}/dynamic-conversations",
            headers=headers,
            params={"variant_id": str(variant_id)},
        )
        assert history_response.status_code == 200, history_response.text
        assert history_response.json()[0]["conversation_id"] == str(conversation_id)
        assert history_response.json()[0]["turns"][0]["messages"] == ["种子第一轮"]
        assert history_response.json()[0]["turns"][0]["tested_response_raw_content"] == (
            "截图中的被测系统原始回复"
        )

        start_response = client.post(
            f"/cases/{case_id}/queries/{query_id}/dynamic-conversations",
            headers=headers,
            json={"variant_id": str(variant_id)},
        )
        assert start_response.status_code == 200, start_response.text
        assert start_response.json()["status"] == "awaiting_response"

        rename_response = client.patch(
            f"/cases/{case_id}/queries/{query_id}/dynamic-conversations/{conversation_id}",
            headers=headers,
            json={"name": "首轮截图复测"},
        )
        assert rename_response.status_code == 200, rename_response.text
        assert rename_response.json()["name"] == "首轮截图复测"
        assert [name for name, _ in history_calls] == ["list", "start", "rename"]
        assert all(call["actor_id"] == user.id for _, call in history_calls)

        # A query from another case is rejected before any service call.
        prior_call_count = len(calls)
        mismatch = client.post(
            f"/cases/{case_id}/queries/{uuid.uuid4()}/next-turn",
            headers=headers,
            files=[
                ("variant_id", (None, str(variant_id))),
                ("conversation_id", (None, str(conversation_id))),
            ],
        )
        assert mismatch.status_code == 404
        assert len(calls) == prior_call_count

        missing_internal_conversation_id = client.post(
            f"/cases/{case_id}/queries/{query_id}/next-turn",
            headers=headers,
            files=[("variant_id", (None, str(variant_id)))],
        )
        assert missing_internal_conversation_id.status_code == 422

        without_jwt = client.post(
            f"/cases/{case_id}/queries/{query_id}/next-turn",
            files=[("variant_id", (None, str(variant_id)))],
        )
        assert without_jwt.status_code == 401
    finally:
        app.dependency_overrides.pop(get_db, None)

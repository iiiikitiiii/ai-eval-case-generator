"""Integration tests for the account/password JWT external API boundary."""
import uuid

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

    async def fake_advance_next_turn(**kwargs):
        # The adapter must pass authenticated identity and request fields to
        # the reusable service without implementing conversation logic itself.
        assert kwargs["actor_id"] == user.id
        assert kwargs["latest_response"] is None
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

        response = client.post(
            "/external/queries/00000000-0000-0000-0000-000000000001/next-turn",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "variant_id": "00000000-0000-0000-0000-000000000002",
                "latest_response": None,
            },
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

        async def fake_conflict(**kwargs):
            raise dynamic_query_service.DynamicQueryConflict("会话状态冲突")

        monkeypatch.setattr(
            dynamic_query_service,
            "advance_next_turn",
            fake_conflict,
        )
        conflict = client.post(
            "/external/queries/00000000-0000-0000-0000-000000000001/next-turn",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "variant_id": "00000000-0000-0000-0000-000000000002",
                "latest_response": "测试答复",
            },
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"] == "会话状态冲突"
    finally:
        app.dependency_overrides.pop(get_db, None)

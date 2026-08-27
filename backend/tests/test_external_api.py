"""Integration tests for the account/password JWT external API boundary."""
import uuid

from fastapi.testclient import TestClient

from app.core.security import hash_password
from app.db.models.user import User
from app.db.session import get_db
from app.main import app


def test_login_token_reaches_external_next_turn_contract():
    """A normal active account can exchange credentials and pass JWT auth."""

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
            json={"latest_response": None},
        )
        # Reaching 501 instead of 401 proves the complete credential-to-JWT
        # authentication path succeeded; turn generation is the next phase.
        assert response.status_code == 501, response.text
        assert response.json()["detail"] == "动态多轮会话服务尚未实现；API 入口和 JWT 鉴权已就绪"
    finally:
        app.dependency_overrides.pop(get_db, None)

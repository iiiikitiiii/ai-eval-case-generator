"""Smoke tests that don't need a live Postgres — CI can run these with zero
services up. Anything hitting the DB (e.g. /health) belongs in an
integration suite that runs against `docker compose up postgres`.
"""
from fastapi.testclient import TestClient

from app.main import app


def test_app_boots():
    assert app.title == "Case Pipeline Hub API"


def test_openapi_schema_builds():
    client = TestClient(app)
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    paths = resp.json()["paths"]
    assert "/auth/login" in paths
    # The external contract must remain discoverable even before its dynamic
    # conversation implementation is connected.
    assert "/external/queries/{query_id}/next-turn" in paths
    assert "/health" in paths


def test_external_next_turn_requires_bearer_token():
    """External callers cannot reach the contract without a valid JWT."""

    client = TestClient(app)
    resp = client.post(
        "/external/queries/00000000-0000-0000-0000-000000000001/next-turn",
        json={"latest_response": None},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "未登录"

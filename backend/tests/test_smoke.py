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
    assert "/health" in paths

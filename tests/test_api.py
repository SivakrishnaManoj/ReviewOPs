import pytest
from fastapi.testclient import TestClient

from reviewops.api import app
from reviewops.config import get_settings


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DEMO_API_KEY", raising=False)
    monkeypatch.setenv("BUILD_SHA", "test-commit")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_liveness_does_not_claim_database_readiness():
    with TestClient(app) as client:
        response = client.get("/healthz")
        assert response.json() == {"status": "ok", "build_sha": "test-commit"}
        assert response.headers["x-request-id"]
        ready = client.get("/readyz")
        assert ready.status_code == 503
        assert ready.json()["database"] == "not_configured"


def test_database_error_does_not_leak_credentials(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://private:password@secret-host/db")

    def broken(_):
        raise RuntimeError("postgresql://private:password@secret-host/db")

    monkeypatch.setattr("reviewops.api.check_database", broken)
    with TestClient(app) as client:
        response = client.get("/readyz")
        assert response.status_code == 503
        assert "password" not in response.text
        assert "secret-host" not in response.text


def test_database_readiness(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://example/db")
    monkeypatch.setattr("reviewops.api.check_database", lambda _: None)
    with TestClient(app) as client:
        assert client.get("/readyz").json() == {"status": "ready", "database": "connected"}


def test_contract_is_exposed_and_missing_database_is_explicit():
    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()
        assert "/api/v1/investigations" in schema["paths"]
        response = client.post(
            "/api/v1/investigations",
            json={
                "question": "What needs investigation?",
                "product_ids": ["B000000001"],
                "date_from": "2022-01-01",
                "date_to": "2022-12-31",
            },
        )
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "database_not_configured"


def test_api_key_guards_future_workflow_but_not_health(monkeypatch):
    monkeypatch.setenv("DEMO_API_KEY", "test-secret")
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        assert client.post("/api/v1/investigations", json={}).status_code == 401
        assert (
            client.post(
                "/api/v1/investigations", json={}, headers={"X-API-Key": "test-secret"}
            ).status_code
            == 422
        )

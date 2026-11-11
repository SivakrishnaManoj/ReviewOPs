from contextlib import contextmanager
from datetime import date
from unittest.mock import Mock

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from reviewops.analytics import rate_change
from reviewops.analytics_contracts import (
    ComparisonRequest,
    Metrics,
    ReviewSearch,
    Scope,
    Summary,
)
from reviewops.analytics_routes import get_analytics
from reviewops.api import app
from reviewops.config import get_settings


def scope_values(**changes):
    return {
        "product_ids": ["B000000001"],
        "date_from": "2023-01-01",
        "date_to": "2023-01-31",
    } | changes


def metrics(total, negative):
    return Metrics(
        total_reviews=total,
        negative_reviews=negative,
        neutral_reviews=0,
        positive_reviews=total - negative,
        reviews_with_text=total,
        negative_rate_percent=round(100 * negative / total, 2) if total else None,
        average_rating=3 if total else None,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"product_ids": []},
        {"product_ids": ["B000000001"] * 2},
        {"product_ids": ["'; DROP TABLE reviews; --"]},
        {"date_from": "2023-02-01"},
        {"date_to": "2025-01-01"},
        {"date_to": "9999-12-31"},
        {"arbitrary_sql": "SELECT 1"},
    ],
)
def test_scope_rejects_invalid_or_unbounded_input(changes):
    with pytest.raises(ValidationError):
        Scope(**scope_values(**changes))


def test_date_end_is_exclusive_next_day_in_utc():
    params = Scope(**scope_values(date_from="2020-02-29", date_to="2020-02-29")).sql_parameters()
    assert params["start"].isoformat() == "2020-02-29T00:00:00+00:00"
    assert params["end"].isoformat() == "2020-03-01T00:00:00+00:00"


def test_comparison_rejects_overlapping_or_reversed_baseline():
    for start, end in [("2022-12-01", "2023-01-01"), ("2022-12-31", "2022-12-01")]:
        with pytest.raises(ValidationError):
            ComparisonRequest(**scope_values(), baseline_date_from=start, baseline_date_to=end)


@pytest.mark.parametrize("changes", [{"limit": 0}, {"limit": 21}, {"query": " "}])
def test_search_is_bounded(changes):
    with pytest.raises(ValidationError):
        ReviewSearch(**scope_values(), **changes)


def test_percentage_points_use_unrounded_counts_and_preserve_missingness():
    assert rate_change(metrics(3, 1), metrics(6, 1)) == 16.67
    assert rate_change(metrics(10, 0), metrics(10, 0)) == 0
    assert rate_change(metrics(0, 0), metrics(10, 2)) is None


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DEMO_API_KEY", raising=False)
    get_settings.cache_clear()
    with TestClient(app) as current:
        yield current
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_http_summary_uses_typed_service(client):
    service = Mock()
    request = Scope(**scope_values())
    service.summary.return_value = Summary(
        scope=request, metrics=metrics(10, 2), dataset_versions=["test"]
    )
    app.dependency_overrides[get_analytics] = lambda: service
    result = client.post("/api/v1/analytics/summary", json=scope_values())
    assert result.status_code == 200
    assert result.json()["metrics"]["negative_rate_percent"] == 20
    service.summary.assert_called_once_with(request)
    assert (
        client.post(
            "/api/v1/analytics/summary", json=scope_values(date_to="2022-01-01")
        ).status_code
        == 422
    )


def test_unconfigured_database_is_explicit(client):
    result = client.post("/api/v1/analytics/summary", json=scope_values())
    assert result.status_code == 503
    assert result.json()["detail"] == "Analytics database is not configured"


def test_database_failure_does_not_expose_connection_details(client, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://private:SECRET@private-host/private")
    get_settings.cache_clear()

    @contextmanager
    def broken(_):
        raise psycopg.OperationalError("SECRET private-host")
        yield  # pragma: no cover

    monkeypatch.setattr("reviewops.analytics_routes.analytics_session", broken)
    result = client.post("/api/v1/analytics/summary", json=scope_values())
    assert result.status_code == 503
    assert "SECRET" not in result.text
    assert "private-host" not in result.text


def test_existing_api_key_boundary_protects_new_routes(client, monkeypatch):
    monkeypatch.setenv("DEMO_API_KEY", "synthetic-key")
    get_settings.cache_clear()
    result = client.post("/api/v1/reviews/search", json=scope_values())
    assert result.status_code == 401


def test_openapi_contains_all_tool_endpoints(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert {
        "/api/v1/analytics/summary",
        "/api/v1/analytics/compare",
        "/api/v1/analytics/monthly",
        "/api/v1/reviews/search",
    } <= paths.keys()


def test_model_serializes_explicit_scope_dates():
    scope = Scope(**scope_values())
    assert scope.date_to == date(2023, 1, 31)

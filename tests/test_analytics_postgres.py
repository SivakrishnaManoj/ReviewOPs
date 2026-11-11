import os

import psycopg
import pytest
from psycopg.rows import dict_row

from reviewops.analytics import Analytics, analytics_session
from reviewops.analytics_contracts import ComparisonRequest, ReviewSearch, Scope
from scripts.migrate import migrate

PID = "B000000001"


@pytest.fixture
def service():
    dsn = os.environ.get("TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("TEST_DATABASE_URL is not configured")
    migrate(dsn)
    with psycopg.connect(dsn, autocommit=True, row_factory=dict_row) as conn:
        # A connection-local table isolates these fixtures from every other test.
        conn.execute("CREATE TEMP TABLE reviews (LIKE public.reviews INCLUDING DEFAULTS)")
        conn.execute("SET TIME ZONE 'Asia/Kolkata'")
        rows = [
            ("dec", PID, 1, "2022-12-15T12:00:00Z", "leak", True, "amazon_reviews_2023"),
            (
                "jan-start",
                PID,
                1,
                "2023-01-01T00:00:00Z",
                "Bottle leaked",
                True,
                "amazon_reviews_2023",
            ),
            ("rating-only", PID, 2, "2023-01-15T12:00:00Z", "", False, "amazon_reviews_2023"),
            ("jan-end", PID, 5, "2023-01-31T23:59:59.999Z", "Works", True, "amazon_reviews_2023"),
            ("feb-start", PID, 3, "2023-02-01T00:00:00Z", "Average", True, "amazon_reviews_2023"),
            (
                "feb-good",
                PID,
                5,
                "2023-02-15T12:00:00Z",
                "Literal 50%_off",
                True,
                "amazon_reviews_2023",
            ),
            (
                "other-product",
                "B000000099",
                1,
                "2023-01-01T00:00:00Z",
                "leak",
                True,
                "amazon_reviews_2023",
            ),
            ("other-source", PID, 1, "2023-01-01T00:00:00Z", "leak", True, "other"),
        ]
        with conn.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO reviews
                (review_id, product_id, rating, reviewed_at,
                 body, has_text, source, dataset_version)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'synthetic-v1')
            """,
                rows,
            )
        yield Analytics(conn)


def scope(**changes):
    return Scope(
        **({"product_ids": [PID], "date_from": "2023-01-01", "date_to": "2023-01-31"} | changes)
    )


@pytest.mark.integration
def test_summary_has_exact_denominators_and_utc_boundaries(service):
    result = service.summary(scope())
    assert result.metrics.total_reviews == 3
    assert result.metrics.negative_reviews == 2
    assert result.metrics.reviews_with_text == 2
    assert result.metrics.negative_rate_percent == 66.67
    assert result.metrics.average_rating == 2.67
    assert result.dataset_versions == ["synthetic-v1"]
    boundary = service.summary(scope(date_from="2023-01-31", date_to="2023-02-01"))
    assert boundary.metrics.total_reviews == 2
    assert boundary.metrics.negative_reviews == 0
    assert boundary.metrics.negative_rate_percent == 0


@pytest.mark.integration
def test_monthly_fills_missing_month_without_inventing_a_rate(service):
    result = service.monthly(scope(date_to="2023-03-15"))
    assert [row.total_reviews for row in result.months] == [3, 2, 0]
    assert [row.negative_rate_percent for row in result.months] == [66.67, 0, None]
    assert result.months[-1].period_to.isoformat() == "2023-03-15"
    empty = service.summary(scope(product_ids=["B000000098"]))
    assert empty.metrics.total_reviews == 0
    assert empty.metrics.negative_rate_percent is None
    assert empty.dataset_versions == []


@pytest.mark.integration
def test_comparison_reports_points_and_unequal_windows(service):
    result = service.compare(
        ComparisonRequest(
            product_ids=[PID],
            date_from="2023-02-01",
            date_to="2023-02-28",
            baseline_date_from="2023-01-01",
            baseline_date_to="2023-01-31",
        )
    )
    assert result.negative_rate_change_percentage_points == -66.67
    assert result.total_count_change == -1
    assert result.negative_count_change == -2
    assert result.status == "available"
    assert any("different lengths" in text for text in result.limitations)
    empty = service.compare(
        ComparisonRequest(
            product_ids=[PID],
            date_from="2023-03-01",
            date_to="2023-03-31",
            baseline_date_from="2023-02-01",
            baseline_date_to="2023-02-28",
        )
    )
    assert empty.status == "insufficient_data"
    assert empty.negative_rate_change_percentage_points is None


@pytest.mark.integration
def test_evidence_is_scoped_and_search_is_literal(service):
    request = ReviewSearch(**scope().model_dump(), query="LEAK")
    result = service.search(request)
    assert result.matched_reviews == 1
    assert result.reviews[0].review_id == "jan-start"
    assert "leaked" in result.reviews[0].excerpt
    assert (
        service.search(ReviewSearch(**scope().model_dump(), query="%' OR 1=1 --")).matched_reviews
        == 0
    )
    full = service.search(ReviewSearch(**scope().model_dump(), negative_only=False, limit=1))
    assert full.matched_reviews == 2
    assert len(full.reviews) == 1
    assert full.reviews[0].review_id == "jan-end"
    literal = service.search(
        ReviewSearch(
            **scope(date_from="2023-02-01", date_to="2023-02-28").model_dump(),
            query="%_",
            negative_only=False,
        )
    )
    assert literal.matched_reviews == 1


@pytest.mark.integration
def test_long_excerpt_contains_the_match_and_is_flagged(service):
    service.connection.execute(
        "UPDATE reviews SET body = %s WHERE review_id = 'jan-start'",
        ("a" * 1500 + "needle" + "z" * 1500,),
    )
    result = service.search(ReviewSearch(**scope().model_dump(), query="needle"))
    assert "needle" in result.reviews[0].excerpt
    assert len(result.reviews[0].excerpt) == 1000
    assert result.reviews[0].excerpt_truncated


@pytest.mark.integration
def test_tool_session_enforces_read_only_transactions():
    dsn = os.environ.get("TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("TEST_DATABASE_URL is not configured")
    migrate(dsn)
    with analytics_session(dsn) as service:
        assert (
            service.connection.execute("SHOW transaction_read_only").fetchone()[
                "transaction_read_only"
            ]
            == "on"
        )
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            service.connection.execute("DELETE FROM reviews WHERE FALSE")

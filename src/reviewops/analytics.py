"""Read-only SQL tools reusable from HTTP, CLI and a future Kimi adapter."""

from contextlib import contextmanager
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

import psycopg
from psycopg.rows import dict_row

from reviewops.analytics_contracts import (
    Comparison,
    ComparisonRequest,
    EvidenceResults,
    EvidenceReview,
    Metrics,
    MonthlyMetric,
    MonthlyReport,
    ReviewSearch,
    Scope,
    Summary,
)

WHERE_SCOPE = """
    source = %(source)s AND product_id = ANY(%(product_ids)s)
    AND reviewed_at >= %(start)s AND reviewed_at < %(end)s
"""
AGGREGATES = """
    COUNT(*) AS total_reviews,
    COUNT(*) FILTER (WHERE rating <= 2) AS negative_reviews,
    COUNT(*) FILTER (WHERE rating = 3) AS neutral_reviews,
    COUNT(*) FILTER (WHERE rating >= 4) AS positive_reviews,
    COUNT(*) FILTER (WHERE has_text) AS reviews_with_text,
    ROUND(100.0 * COUNT(*) FILTER (WHERE rating <= 2) / NULLIF(COUNT(*), 0), 2)
        AS negative_rate_percent,
    ROUND(AVG(rating), 2) AS average_rating
"""


@contextmanager
def analytics_session(dsn):
    # A consistent snapshot across all tools in one request; writes are prohibited by Postgres.
    with psycopg.connect(
        dsn,
        connect_timeout=5,
        row_factory=dict_row,
        options=(
            "-c default_transaction_read_only=on -c statement_timeout=10000 -c lock_timeout=1000"
        ),
    ) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        yield Analytics(connection)


def rate_change(current, baseline):
    if not current.total_reviews or not baseline.total_reviews:
        return None
    # Derive the difference from raw counts, not previously rounded percentages.
    delta = 100 * (
        Decimal(current.negative_reviews) / current.total_reviews
        - Decimal(baseline.negative_reviews) / baseline.total_reviews
    )
    return float(delta.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


class Analytics:
    def __init__(self, connection):
        self.connection = connection

    def summary(self, scope: Scope) -> Summary:
        row = self.connection.execute(
            f"SELECT {AGGREGATES}, ARRAY_AGG(DISTINCT dataset_version) AS dataset_versions "
            f"FROM reviews WHERE {WHERE_SCOPE}",
            scope.sql_parameters(),
        ).fetchone()
        return Summary(
            scope=scope,
            metrics=Metrics.model_validate(row),
            dataset_versions=row["dataset_versions"] or [],
        )

    def compare(self, request: ComparisonRequest) -> Comparison:
        current = self.summary(request.current())
        baseline = self.summary(request.baseline())
        change = rate_change(current.metrics, baseline.metrics)
        limitations = ["Descriptive comparison only; no statistical significance or causal claim."]
        if (request.date_to - request.date_from) != (
            request.baseline_date_to - request.baseline_date_from
        ):
            limitations.append(
                "Periods have different lengths; raw counts are not duration-adjusted."
            )
        if change is None:
            limitations.append(
                "At least one period has no imported reviews; rate change is undefined."
            )
        if len(request.product_ids) > 1:
            limitations.append("Pooled rates can change when the mix of products reviewed changes.")
        return Comparison(
            current=current,
            baseline=baseline,
            negative_rate_change_percentage_points=change,
            negative_count_change=current.metrics.negative_reviews
            - baseline.metrics.negative_reviews,
            total_count_change=current.metrics.total_reviews - baseline.metrics.total_reviews,
            status="available" if change is not None else "insufficient_data",
            limitations=limitations,
        )

    def monthly(self, scope: Scope) -> MonthlyReport:
        rows = self.connection.execute(
            "SELECT date_trunc('month', reviewed_at AT TIME ZONE 'UTC')::date AS month, "
            f"{AGGREGATES} FROM reviews WHERE {WHERE_SCOPE} GROUP BY month ORDER BY month",
            scope.sql_parameters(),
        ).fetchall()
        by_month = {row["month"]: row for row in rows}
        months = []
        month = scope.date_from.replace(day=1)
        while month <= scope.date_to:
            next_month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
            row = by_month.get(
                month,
                {
                    "total_reviews": 0,
                    "negative_reviews": 0,
                    "neutral_reviews": 0,
                    "positive_reviews": 0,
                    "reviews_with_text": 0,
                    "negative_rate_percent": None,
                    "average_rating": None,
                },
            )
            months.append(
                MonthlyMetric(
                    **Metrics.model_validate(row).model_dump(),
                    month=month,
                    period_from=max(month, scope.date_from),
                    period_to=min(next_month - timedelta(days=1), scope.date_to),
                )
            )
            month = next_month
        return MonthlyReport(scope=scope, months=months)

    def search(self, request: ReviewSearch) -> EvidenceResults:
        parameters = request.sql_parameters() | {
            "query": request.query or "",
            "negative_only": request.negative_only,
            "limit": request.limit,
        }
        rows = self.connection.execute(
            f"""WITH scoped AS (
                SELECT review_id, product_id, rating, reviewed_at, dataset_version,
                       title || E'\\n' || body AS review_text
                FROM reviews WHERE {WHERE_SCOPE} AND has_text
                  AND (NOT %(negative_only)s OR rating <= 2)
            ), matched AS (
                SELECT *, strpos(lower(review_text), lower(%(query)s)) AS position
                FROM scoped
                WHERE %(query)s = '' OR strpos(lower(review_text), lower(%(query)s)) > 0
            )
            SELECT review_id, product_id, rating, reviewed_at, dataset_version,
                   substring(review_text FROM greatest(position - 100, 1) FOR 1000) AS excerpt,
                   length(review_text) > 1000 AS excerpt_truncated,
                   COUNT(*) OVER () AS matched_reviews
            FROM matched ORDER BY reviewed_at DESC, review_id ASC LIMIT %(limit)s""",
            parameters,
        ).fetchall()
        return EvidenceResults(
            scope=request,
            matched_reviews=rows[0]["matched_reviews"] if rows else 0,
            reviews=[EvidenceReview.model_validate(row) for row in rows],
        )

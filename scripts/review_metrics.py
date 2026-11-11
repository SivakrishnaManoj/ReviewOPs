"""Run the review analysis tools directly against DATABASE_URL, without an API server or LLM."""

import argparse
import json

from reviewops.analytics import analytics_session
from reviewops.analytics_contracts import ComparisonRequest, ReviewSearch, Scope
from reviewops.config import get_settings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["summary", "monthly", "compare", "search"])
    parser.add_argument("--product-id", action="append", required=True)
    parser.add_argument("--date-from", required=True)
    parser.add_argument("--date-to", required=True)
    parser.add_argument("--baseline-from")
    parser.add_argument("--baseline-to")
    parser.add_argument("--query")
    parser.add_argument("--all-ratings", action="store_true")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args(argv)
    values = {"product_ids": args.product_id, "date_from": args.date_from, "date_to": args.date_to}
    try:
        if args.mode == "compare":
            request = ComparisonRequest(
                **values,
                baseline_date_from=args.baseline_from,
                baseline_date_to=args.baseline_to,
            )
        elif args.mode == "search":
            request = ReviewSearch(
                **values,
                query=args.query,
                negative_only=not args.all_ratings,
                limit=args.limit,
            )
        else:
            request = Scope(**values)
    except ValueError:
        parser.error(
            "Invalid product IDs, dates or limits. Comparison requires both baseline dates."
        )
    configured = get_settings().database_url
    if not configured or not configured.get_secret_value():
        parser.error("Set DATABASE_URL before running this command")
    try:
        with analytics_session(configured.get_secret_value()) as service:
            result = getattr(service, args.mode)(request)
        print(result.model_dump_json(indent=2))
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "message": "Check database connectivity and migrations.",
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

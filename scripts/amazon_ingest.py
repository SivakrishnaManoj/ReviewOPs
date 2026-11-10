"""Inspect, profile, or import Amazon JSONL/gzip streams. See pipelines/README.md."""

import argparse
import json
import re
from contextlib import nullcontext

from reviewops.ingestion.amazon import SOURCE, open_source
from reviewops.ingestion.pipeline import PostgresSink, process, save_report


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["inspect", "profile", "ingest"])
    parser.add_argument("--category", default="All_Beauty")
    parser.add_argument("--input", help="Optional local JSONL or JSONL.gz; otherwise stream HTTPS")
    parser.add_argument(
        "--limit", type=int, default=200, help="Source lines to scan; 0 = full input"
    )
    parser.add_argument("--product-id", action="append", default=[])
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--dataset-version", help="Required explicit provenance for local imports")
    parser.add_argument("--report", help="Write a JSON audit/coverage report")
    args = parser.parse_args(argv)
    if args.limit < 0 or not 1 <= args.batch_size <= 5000:
        parser.error("--limit must be nonnegative; --batch-size must be between 1 and 5000")
    if not re.fullmatch(r"[A-Za-z][A-Za-z_]{0,79}", args.category):
        parser.error("Invalid category")
    if any(not re.fullmatch(r"[A-Z0-9]{10}", item) for item in args.product_id):
        parser.error("Product IDs must be ten uppercase letters/digits")
    if args.mode == "ingest" and args.input and not args.dataset_version:
        parser.error("Local imports require --dataset-version so subsets are not mislabelled")
    if args.dataset_version is not None and not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}", args.dataset_version
    ):
        parser.error("Invalid dataset version")
    return args


def main(argv=None):
    args = arguments(argv)
    dataset_version = args.dataset_version or f"{SOURCE}/{args.category}"
    selection = {"product_ids": args.product_id, "line_limit": args.limit}
    connection_context = nullcontext(None)
    sink = None
    try:
        if args.mode == "ingest":
            import psycopg

            from reviewops.config import get_settings

            dsn = get_settings().database_url
            if not dsn or not dsn.get_secret_value():
                raise ValueError("Database configuration missing")
            connection_context = psycopg.connect(
                dsn.get_secret_value(),
                autocommit=True,
                connect_timeout=10,
                options="-c statement_timeout=60000 -c lock_timeout=10000",
            )
        with connection_context as connection:
            if connection is not None:
                sink = PostgresSink(connection, args.category, dataset_version, selection)
            try:
                with open_source(args.category, args.input) as stream:
                    report = process(
                        stream,
                        limit=args.limit,
                        product_ids=args.product_id,
                        batch_size=args.batch_size,
                        sink=sink,
                        inspect=args.mode != "ingest",
                    )
                report.update(
                    {
                        "source": SOURCE,
                        "category": args.category,
                        "dataset_version": dataset_version,
                        "input_kind": "local" if args.input else "publisher_https_stream",
                        "mode": args.mode,
                    }
                )
                if sink is not None:
                    report["run_id"] = str(sink.run_id)
                    sink.finish(report)
            except BaseException:
                if sink is not None:
                    sink.finish()
                raise
        contents = save_report(report, args.report)
        if args.report:
            # Aggregate status only. Full inspection output is in the explicitly requested report.
            keys = (
                "rows_seen",
                "valid_unique",
                "rejected",
                "duplicates",
                "identity_conflicts",
                "inserted",
                "already_present",
                "database_conflicts",
                "input_exhausted",
            )
            print(json.dumps({key: report[key] for key in keys}))
        else:
            print(contents, end="")
        return 0
    except Exception as exc:
        # Never echo exception messages: DSNs, raw review text and URLs may be included.
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "run_id": str(sink.run_id) if sink is not None else None,
                    "message": "Check input/network and database migrations/configuration. "
                    "Committed batches are retained; rerun to safely skip existing rows.",
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

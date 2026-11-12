"""Preview SQL evidence, or request one model investigation."""

import argparse
import json

from pydantic import ValidationError

from reviewops.ai.investigate import investigate, prepare
from reviewops.ai.kimi import InvestigationError
from reviewops.config import get_settings
from reviewops.contracts import InvestigationRequest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product-id", action="append", required=True)
    parser.add_argument("--date-from", required=True)
    parser.add_argument("--date-to", required=True)
    parser.add_argument(
        "--question", default="What complaints were reported, and what should we investigate first?"
    )
    parser.add_argument(
        "--preview", action="store_true", help="Show evidence without calling the model"
    )
    args = parser.parse_args(argv)
    try:
        request = InvestigationRequest(
            question=args.question,
            product_ids=args.product_id,
            date_from=args.date_from,
            date_to=args.date_to,
        )
    except ValidationError:
        parser.error("Choose valid parent ASINs and an ordered date range of at most 366 days.")
    try:
        settings = get_settings()
        result = prepare(request, settings) if args.preview else investigate(request, settings)
        print(result.model_dump_json(indent=2))
    except InvestigationError as exc:
        print(json.dumps({"status": "failed", "code": exc.code, "message": str(exc)}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

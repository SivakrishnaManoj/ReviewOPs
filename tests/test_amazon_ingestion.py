import gzip
import io
import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from reviewops.ingestion.amazon import InvalidRecord, normalize, open_source, records
from reviewops.ingestion.pipeline import process
from scripts.amazon_ingest import arguments, main


def example(**changes):
    record = {
        "parent_asin": "B000000001", "asin": "B000000002", "user_id": "synthetic-user-1",
        "timestamp": 1672531200000, "rating": 2.0, "title": "Damaged",
        "text": "The cap was broken.<br />It leaked &amp; made a mess.",
        "verified_purchase": True,
    }
    return record | changes


def stream(*rows):
    return io.BytesIO(b"".join(json.dumps(row).encode() + b"\n" for row in rows))


class NormalizationTests(unittest.TestCase):
    def test_normalizes_without_erasing_complaint(self):
        review = normalize(example())
        self.assertEqual(review.body, "The cap was broken. It leaked & made a mess.")
        self.assertEqual(review.rating, 2)
        self.assertEqual(review.reviewed_at, datetime(2023, 1, 1, tzinfo=UTC))
        self.assertNotIn("synthetic-user", repr(review))

    def test_same_identity_different_text_is_conflict_not_new_review(self):
        original = normalize(example())
        edited = normalize(example(text="Changed review"))
        self.assertEqual(original.review_id, edited.review_id)
        self.assertNotEqual(original.content_hash, edited.content_hash)

    def test_identical_text_from_different_people_is_not_duplicate(self):
        self.assertNotEqual(
            normalize(example()).review_id,
            normalize(example(user_id="synthetic-user-2")).review_id,
        )

    def test_rating_only_and_title_only_are_preserved(self):
        self.assertFalse(normalize(example(text=None, title=None)).has_text)
        self.assertTrue(normalize(example(text="", title="Broken")).has_text)

    def test_publisher_timestamp_alias(self):
        row = example()
        row["sort_timestamp"] = row.pop("timestamp")
        self.assertEqual(normalize(row), normalize(example()))

    def test_invalid_records_have_reason_codes(self):
        cases = [
            (example(rating=True), "invalid_rating"),
            (example(rating=3.5), "invalid_rating"),
            (example(rating=float("nan")), "invalid_rating"),
            (example(rating="2"), "invalid_rating"),
            (example(rating=0), "invalid_rating"),
            (example(rating=10**1000), "invalid_rating"),
            (example(parent_asin=""), "invalid_parent_asin"),
            (example(user_id=""), "invalid_user_id"),
            (example(timestamp=1672531200), "timestamp_outside_dataset"),
            (example(timestamp=1696118400000), "timestamp_outside_dataset"),
            (example(timestamp=True), "invalid_timestamp"),
            (example(sort_timestamp=1), "conflicting_timestamps"),
            (example(text="bad\x00text"), "invalid_text_characters"),
            (example(text=123), "invalid_text"),
            (example(verified_purchase="false"), "invalid_verified_purchase"),
            ([], "not_an_object"),
        ]
        for raw, reason in cases:
            with self.subTest(reason=reason, raw_type=type(raw).__name__):
                with self.assertRaisesRegex(InvalidRecord, f"^{reason}$"):
                    normalize(raw)


class StreamTests(unittest.TestCase):
    def test_malformed_lines_do_not_hide_later_valid_rows(self):
        data = io.BytesIO(b"not json\n\xff\n" + stream(example()).getvalue())
        report = process(data)
        self.assertEqual(report["rows_seen"], 3)
        self.assertEqual(report["rejected"], 2)
        self.assertEqual(report["valid_unique"], 1)

    def test_oversized_line_is_drained_with_bounded_reads(self):
        with patch("reviewops.ingestion.amazon.MAX_LINE_BYTES", 16):
            result = list(records(io.BytesIO(b"x" * 100 + b"\n{}\n")))
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0][3], "oversized_record")
        self.assertEqual(result[1][2], {})

    def test_local_gzip_and_https_use_same_reader(self):
        encoded = gzip.compress(stream(example()).getvalue())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.jsonl.gz"
            path.write_bytes(encoded)
            with open_source("All_Beauty", path) as incoming:
                local = process(incoming)
        with patch("urllib.request.urlopen", return_value=io.BytesIO(encoded)):
            with open_source("All_Beauty") as incoming:
                remote = process(incoming)
        self.assertEqual(local, remote)

    def test_category_cannot_inject_a_url(self):
        with self.assertRaises(ValueError):
            with open_source("../../anything"):
                pass


class PipelineTests(unittest.TestCase):
    def test_dedup_conflict_filters_and_coverage(self):
        report = process(stream(
            example(), example(), example(text="A conflicting edit"),
            example(user_id="different person"),
            example(user_id="rating-only", text="", title=""),
            example(parent_asin="B000000099"), example(rating=6),
        ), product_ids=["B000000001"], inspect=True, batch_size=1)
        self.assertEqual(report["rows_seen"], 7)
        self.assertEqual(report["duplicates"], 1)
        self.assertEqual(report["identity_conflicts"], 1)
        self.assertEqual(report["filtered"], 1)
        self.assertEqual(report["rejected"], 1)
        self.assertEqual(report["valid_unique"], 3)
        self.assertEqual(report["rating_only"], 1)
        self.assertTrue(report["input_exhausted"])
        month = report["product_months"][0]
        self.assertEqual(month["reviews"], 3)
        self.assertEqual(month["negative_reviews"], 3)
        self.assertEqual(month["text_reviews"], 2)
        self.assertNotIn("body", report["samples_without_text"][0])

    def test_small_inspection_does_not_claim_full_coverage(self):
        report = process(stream(example(), example(user_id="second")), limit=1)
        self.assertEqual(report["rows_seen"], 1)
        self.assertFalse(report["input_exhausted"])

    def test_zero_rows_is_valid_empty_report(self):
        report = process(io.BytesIO(), inspect=True)
        self.assertTrue(report["input_exhausted"])
        self.assertEqual(report["product_months"], [])

    def test_failed_stream_is_not_reported_complete(self):
        class Broken(io.BytesIO):
            def readline(self, *_):
                raise OSError("private source details")

        with self.assertRaises(OSError):
            process(Broken())

    def test_cli_inspection_needs_no_database_or_model(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.jsonl"
            report = Path(directory) / "report.json"
            path.write_bytes(stream(example()).getvalue())
            with patch("builtins.print"):
                self.assertEqual(main([
                    "inspect", "--input", str(path), "--report", str(report),
                ]), 0)
            self.assertEqual(json.loads(report.read_text())["valid_unique"], 1)

    def test_cli_sanitizes_failures(self):
        with patch("scripts.amazon_ingest.open_source", side_effect=OSError("SECRET")):
            with patch("builtins.print") as output:
                self.assertEqual(main(["inspect"]), 1)
                self.assertNotIn("SECRET", str(output.call_args))

    def test_local_ingestion_requires_provenance(self):
        with self.assertRaises(SystemExit), patch("sys.stderr", new=io.StringIO()):
            arguments(["ingest", "--input", "subset.jsonl"])


if __name__ == "__main__":
    unittest.main()

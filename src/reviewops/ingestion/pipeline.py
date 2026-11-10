"""Inspection and batch imports share the same validation and deduplication rules."""

import json
import sqlite3
import tempfile
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

from reviewops.ingestion.amazon import InvalidRecord, normalize, records


class SeenReviews:
    """Disk-backed identity index: bounded RAM and no raw review text on disk."""

    def __enter__(self):
        self.directory = tempfile.TemporaryDirectory(prefix="reviewops-seen-")
        self.connection = sqlite3.connect(Path(self.directory.name) / "seen.sqlite")
        self.connection.execute("CREATE TABLE seen (id TEXT PRIMARY KEY, hash TEXT NOT NULL)")
        return self

    def check(self, review):
        existing = self.connection.execute(
            "SELECT hash FROM seen WHERE id = ?", (review.review_id,)
        ).fetchone()
        if existing:
            return "duplicates" if existing[0] == review.content_hash else "identity_conflicts"
        self.connection.execute("INSERT INTO seen VALUES (?, ?)", (
            review.review_id, review.content_hash,
        ))
        return None

    def __exit__(self, *_):
        self.connection.close()
        self.directory.cleanup()


class Inspector:
    def __init__(self):
        self.products = defaultdict(lambda: Counter())
        self.fields = Counter()
        self.samples = []

    def observe(self, review):
        month = review.reviewed_at.strftime("%Y-%m")
        counts = self.products[(review.product_id, month)]
        counts["reviews"] += 1
        counts["negative_reviews"] += review.rating <= 2
        counts["text_reviews"] += review.has_text
        if len(self.samples) < 5:
            sample = asdict(review)
            # Reports contain schema/coverage, not raw text or reviewer IDs.
            sample.pop("title")
            sample.pop("body")
            sample.pop("content_hash")
            sample["reviewed_at"] = review.reviewed_at.isoformat()
            sample["has_text"] = review.has_text
            self.samples.append(sample)

    def report(self):
        return {
            "fields_seen": dict(sorted(self.fields.items())),
            "samples_without_text": self.samples,
            "product_months": [
                {"product_id": product, "month": month, **dict(counts)}
                for (product, month), counts in sorted(self.products.items())
            ],
        }


def process(stream, *, limit=200, product_ids=(), batch_size=500, sink=None, inspect=False):
    if limit < 0 or not 1 <= batch_size <= 5000:
        raise ValueError("Invalid limit or batch size")
    selected = set(product_ids)
    counts = Counter({
        "rows_seen": 0, "rejected": 0, "filtered": 0, "duplicates": 0,
        "identity_conflicts": 0, "valid_unique": 0, "rating_only": 0,
        "inserted": 0, "already_present": 0, "database_conflicts": 0,
    })
    reasons = Counter()
    inspector = Inspector() if inspect else None
    batch, rejections = [], []

    def flush():
        if sink is not None:
            counts.update(sink.write(batch, rejections))
        batch.clear()
        rejections.clear()

    with SeenReviews() as seen:
        for line_number, digest, raw, error in records(stream, limit):
            counts["rows_seen"] += 1
            if inspector is not None and isinstance(raw, dict):
                inspector.fields.update(raw.keys())
            if not error:
                try:
                    review = normalize(raw)
                except InvalidRecord as exc:
                    error = str(exc)
            if error:
                counts["rejected"] += 1
                reasons[error] += 1
                rejections.append((line_number, error, digest))
            elif selected and review.product_id not in selected:
                counts["filtered"] += 1
            else:
                duplicate = seen.check(review)
                if duplicate:
                    counts[duplicate] += 1
                    if duplicate == "identity_conflicts":
                        reasons[duplicate] += 1
                        rejections.append((line_number, duplicate, digest))
                else:
                    counts["valid_unique"] += 1
                    counts["rating_only"] += not review.has_text
                    batch.append((line_number, digest, review))
                    if inspector is not None:
                        inspector.observe(review)
            if len(batch) + len(rejections) >= batch_size:
                flush()
        flush()
    # Conservatively mark a scan that hits its cap as partial, even at an exact EOF boundary.
    exhausted = limit == 0 or counts["rows_seen"] < limit
    result = {
        **dict(counts), "rejection_reasons": dict(reasons),
        "input_exhausted": exhausted, "scan_limit": limit,
        "product_filter": sorted(selected), "negative_rating_definition": [1, 2],
        "coverage": "selected products in this input; not all Amazon reviews",
    }
    if inspector is not None:
        result.update(inspector.report())
    return result


class PostgresSink:
    """Commit each batch atomically; reruns skip existing identical records."""

    def __init__(self, connection, category, dataset_version, selection):
        import uuid

        from psycopg.types.json import Jsonb

        self.connection = connection
        self.dataset_version = dataset_version
        self.run_id = uuid.uuid4()
        self.totals = Counter()
        with connection.transaction():
            connection.execute(
                """INSERT INTO ingestion_runs
                (run_id, source, dataset_version, category, status, selection)
                VALUES (%s, 'amazon_reviews_2023', %s, %s, 'running', %s)""",
                (self.run_id, dataset_version, category, Jsonb(selection)),
            )
            connection.execute("""CREATE TEMP TABLE ingestion_stage (
                review_id TEXT PRIMARY KEY, product_id TEXT, title TEXT, body TEXT,
                rating SMALLINT, reviewed_at TIMESTAMPTZ, dataset_version TEXT,
                source TEXT, source_asin TEXT, content_hash TEXT, has_text BOOLEAN,
                verified_purchase BOOLEAN, source_line BIGINT, ingestion_run_id UUID,
                record_hash TEXT
            ) ON COMMIT PRESERVE ROWS""")

    def write(self, batch, rejections):
        from psycopg.types.json import Jsonb

        delta = Counter()
        rejected = list(rejections)
        with self.connection.transaction():
            self.connection.execute("TRUNCATE ingestion_stage")
            if batch:
                with self.connection.cursor() as cursor:
                    with cursor.copy("COPY ingestion_stage FROM STDIN") as copy:
                        for line, digest, review in batch:
                            copy.write_row((
                                review.review_id, review.product_id, review.title, review.body,
                                review.rating, review.reviewed_at, self.dataset_version,
                                "amazon_reviews_2023", review.asin, review.content_hash,
                                review.has_text, review.verified_purchase, line,
                                self.run_id, digest,
                            ))
                added = self.connection.execute("""
                    INSERT INTO reviews
                    (review_id, product_id, title, body, rating, reviewed_at, dataset_version,
                     source, source_asin, content_hash, has_text, verified_purchase,
                     source_line, ingestion_run_id)
                    SELECT review_id, product_id, title, body, rating, reviewed_at, dataset_version,
                           source, source_asin, content_hash, has_text, verified_purchase,
                           source_line, ingestion_run_id
                    FROM ingestion_stage ORDER BY review_id
                    ON CONFLICT (review_id) DO NOTHING RETURNING review_id
                """).fetchall()
                # Check after INSERT so a concurrent import cannot hide conflicting content.
                conflicts = self.connection.execute("""
                    SELECT s.source_line, s.record_hash
                    FROM ingestion_stage s JOIN reviews r USING (review_id)
                    WHERE r.content_hash IS DISTINCT FROM s.content_hash
                       OR r.source IS DISTINCT FROM s.source
                """).fetchall()
                delta["inserted"] = len(added)
                delta["database_conflicts"] = len(conflicts)
                delta["already_present"] = len(batch) - len(added) - len(conflicts)
                rejected.extend((line, "database_identity_conflict", digest)
                                for line, digest in conflicts)
            if rejected:
                with self.connection.cursor() as cursor:
                    cursor.executemany(
                        "INSERT INTO ingestion_rejections VALUES (%s, %s, %s, %s)",
                        [(self.run_id, *row) for row in rejected],
                    )
            next_totals = self.totals + delta
            self.connection.execute(
                "UPDATE ingestion_runs SET summary = %s WHERE run_id = %s",
                (Jsonb(dict(next_totals)), self.run_id),
            )
        self.totals = next_totals
        return delta

    def finish(self, summary=None):
        from psycopg.types.json import Jsonb

        status = "failed" if summary is None else (
            "complete" if summary["input_exhausted"] else "partial"
        )
        with self.connection.transaction():
            self.connection.execute(
                """UPDATE ingestion_runs SET status = %s, summary = %s,
                finished_at = CURRENT_TIMESTAMP WHERE run_id = %s""",
                (status, Jsonb(summary if summary is not None else dict(self.totals)), self.run_id),
            )
            self.connection.execute("DROP TABLE ingestion_stage")


def save_report(report, path):
    contents = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if path is not None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(str(path) + ".tmp")
        temporary.write_text(contents, encoding="utf-8")
        temporary.replace(path)
    return contents

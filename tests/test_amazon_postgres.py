import io
import json
import os
import uuid
from dataclasses import replace

import psycopg
import pytest

from reviewops.ingestion.amazon import normalize
from reviewops.ingestion.pipeline import PostgresSink, process
from scripts.migrate import migrate


@pytest.mark.integration
def test_import_is_repeatable_and_conflicts_are_audited():
    dsn = os.environ.get("TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("TEST_DATABASE_URL is not configured")
    migrate(dsn)
    user = "test-" + uuid.uuid4().hex
    record = {
        "parent_asin": "B000000001",
        "asin": "B000000002",
        "user_id": user,
        "timestamp": 1672531200000,
        "rating": 1,
        "title": "",
        "text": "Synthetic broken cap",
    }
    versions = "synthetic-test/" + uuid.uuid4().hex
    run_ids = []
    with psycopg.connect(dsn, autocommit=True) as connection:

        def run(rows):
            sink = PostgresSink(connection, "All_Beauty", versions, {})
            run_ids.append(sink.run_id)
            data = io.BytesIO(b"".join(json.dumps(row).encode() + b"\n" for row in rows))
            report = process(data, limit=0, batch_size=1, sink=sink)
            sink.finish(report)
            return report

        try:
            initial = run(
                [
                    record,
                    record,
                    record | {"rating": 7},
                    record | {"user_id": user + "-2", "text": ""},
                ]
            )
            assert initial["inserted"] == 2
            assert initial["duplicates"] == 1
            assert initial["rejected"] == 1
            again = run([record])
            assert again["inserted"] == 0
            assert again["already_present"] == 1
            changed = run([record | {"text": "Conflicting edit"}])
            assert changed["database_conflicts"] == 1
            assert changed["inserted"] == 0
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM reviews WHERE dataset_version = %s",
                    (versions,),
                ).fetchone()[0]
                == 2
            )
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM reviews WHERE dataset_version = %s AND NOT has_text",
                    (versions,),
                ).fetchone()[0]
                == 1
            )
            reasons = connection.execute(
                "SELECT reason FROM ingestion_rejections WHERE run_id = ANY(%s)",
                (run_ids,),
            ).fetchall()
            assert sorted(row[0] for row in reasons) == [
                "database_identity_conflict",
                "invalid_rating",
            ]
            assert connection.execute(
                "SELECT DISTINCT status FROM ingestion_runs WHERE run_id = ANY(%s)",
                (run_ids,),
            ).fetchall() == [("complete",)]

            # A failed batch must roll back both its inserted reviews and rejection audit.
            failed_sink = PostgresSink(connection, "All_Beauty", versions, {})
            run_ids.append(failed_sink.run_id)
            good = normalize(record | {"user_id": user + "-transaction"})
            invalid = replace(good, review_id=good.review_id + "-bad", rating=6)
            with pytest.raises(psycopg.errors.CheckViolation):
                failed_sink.write([(1, "hash", good), (2, "hash", invalid)], [])
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM reviews WHERE review_id = %s",
                    (good.review_id,),
                ).fetchone()[0]
                == 0
            )
            failed_sink.finish()
            assert (
                connection.execute(
                    "SELECT status FROM ingestion_runs WHERE run_id = %s",
                    (failed_sink.run_id,),
                ).fetchone()[0]
                == "failed"
            )

            # A broken source after a committed batch retains that batch for safe replay.
            partial_sink = PostgresSink(connection, "All_Beauty", versions, {})
            run_ids.append(partial_sink.run_id)

            class BrokenStream(io.BytesIO):
                def readline(self, size=-1):
                    line = super().readline(size)
                    if not line:
                        raise OSError("synthetic interruption")
                    return line

            interrupted = record | {"user_id": user + "-interrupted"}
            with pytest.raises(OSError):
                process(
                    BrokenStream(json.dumps(interrupted).encode() + b"\n"),
                    limit=0,
                    batch_size=1,
                    sink=partial_sink,
                )
            partial_sink.finish()
            replay = run([interrupted])
            assert replay["already_present"] == 1
            assert replay["inserted"] == 0
        finally:
            connection.execute("DELETE FROM reviews WHERE dataset_version = %s", (versions,))
            connection.execute(
                "DELETE FROM ingestion_rejections WHERE run_id = ANY(%s)",
                (run_ids,),
            )
            connection.execute("DELETE FROM ingestion_runs WHERE run_id = ANY(%s)", (run_ids,))

import os

import psycopg
import pytest

from scripts.migrate import migrate


@pytest.mark.integration
def test_real_migration_is_repeatable_and_pgvector_is_available():
    # CI uses a fresh throwaway database. Never point TEST_DATABASE_URL at production.
    dsn = os.environ.get("TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("TEST_DATABASE_URL is not configured")
    migrate(dsn)
    assert migrate(dsn) == []
    with psycopg.connect(dsn) as connection:
        assert connection.execute("SELECT '[1,2,3]'::vector <-> '[1,2,4]'::vector").fetchone() == (
            1.0,
        )
        assert connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] >= 1
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute("""
                INSERT INTO reviews
                (review_id, product_id, body, rating, reviewed_at, dataset_version)
                VALUES ('invalid', 'p', 'synthetic test', 6, NOW(), 'test')
            """)

"""Apply ordered SQL migrations once, under an advisory lock and one transaction."""

import hashlib
from pathlib import Path

import psycopg

from reviewops.config import get_settings

MIGRATIONS = Path(__file__).resolve().parents[1] / "db" / "migrations"


def migrate(dsn: str, directory: Path = MIGRATIONS) -> list[str]:
    applied = []
    with psycopg.connect(dsn, connect_timeout=10) as connection:
        connection.execute("SELECT pg_advisory_xact_lock(726384920)")
        connection.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                name TEXT PRIMARY KEY,
                checksum TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        for path in sorted(directory.glob("*.sql")):
            contents = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(contents.encode()).hexdigest()
            existing = connection.execute(
                "SELECT checksum FROM schema_migrations WHERE name = %s", (path.name,)
            ).fetchone()
            if existing:
                if existing[0] != checksum:
                    raise RuntimeError(f"Applied migration changed: {path.name}")
                continue
            connection.execute(contents)
            connection.execute(
                "INSERT INTO schema_migrations (name, checksum) VALUES (%s, %s)",
                (path.name, checksum),
            )
            applied.append(path.name)
    return applied


if __name__ == "__main__":
    configured = get_settings().database_url
    if not configured or not configured.get_secret_value():
        raise SystemExit("DATABASE_URL must be configured")
    for migration in migrate(configured.get_secret_value()):
        print(f"Applied {migration}")

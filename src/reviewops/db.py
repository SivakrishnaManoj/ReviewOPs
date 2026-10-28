import psycopg


def check_database(dsn: str) -> None:
    """Connectivity probe. Never put the DSN or exception text in public responses."""
    with psycopg.connect(dsn, connect_timeout=3, options="-c statement_timeout=3000") as connection:
        connection.execute("SELECT 1").fetchone()

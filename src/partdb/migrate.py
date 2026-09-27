from importlib import resources

import psycopg


def apply_migrations(conn: psycopg.Connection) -> list[str]:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )"""
    )
    applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    completed: list[str] = []
    root = resources.files("partdb.migrations")
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        if not path.name.endswith(".sql"):
            continue
        version = path.name.removesuffix(".sql")
        if version in applied:
            continue
        with conn.transaction():
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT INTO schema_migrations(version) VALUES (%s)", (version,)
            )
        completed.append(version)
    return completed

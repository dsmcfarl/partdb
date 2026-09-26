import psycopg
import pytest

from partdb.migrate import apply_migrations

pytestmark = pytest.mark.integration


def column_names(conn: psycopg.Connection, table: str) -> set[str]:
    rows = conn.execute(
        """SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s""",
        (table,),
    )
    return {row[0] for row in rows}


def extension_names(conn: psycopg.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT extname FROM pg_extension")}


def test_migrate_fresh_database(database_dsn: str) -> None:
    with psycopg.connect(database_dsn) as conn:
        assert apply_migrations(conn) == ["001_initial", "002_location_verification"]
        assert column_names(conn, "locations") == {"name", "verified_at"}
        assert extension_names(conn) >= {"plpgsql", "vector"}


def test_migrate_legacy_database_preserves_rows(database_dsn: str) -> None:
    with psycopg.connect(database_dsn) as conn:
        conn.execute("CREATE EXTENSION vector")
        conn.execute("CREATE TABLE locations (name varchar(255) PRIMARY KEY)")
        conn.execute(
            """CREATE TABLE parts (
                id serial PRIMARY KEY,
                location varchar(255) REFERENCES locations(name),
                description text,
                embedding vector(1536))"""
        )
        conn.execute("INSERT INTO locations(name) VALUES ('5A1')")
        conn.execute(
            "INSERT INTO parts(location, description) VALUES ('5A1', 'M3 bolts')"
        )
        apply_migrations(conn)
        assert conn.execute("SELECT count(*) FROM locations").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM parts").fetchone()[0] == 1
        assert conn.execute(
            "SELECT verified_at IS NULL FROM locations WHERE name='5A1'"
        ).fetchone()[0]


def test_second_migration_run_is_a_noop(database_dsn: str) -> None:
    with psycopg.connect(database_dsn) as conn:
        apply_migrations(conn)
        assert apply_migrations(conn) == []

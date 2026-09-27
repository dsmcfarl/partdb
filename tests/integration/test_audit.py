from pathlib import Path

import psycopg
import pytest
from click.testing import CliRunner

from partdb.audit import run_audit
from partdb.cli import cli

pytestmark = pytest.mark.integration


def seed_findings(conn: psycopg.Connection) -> None:
    with conn.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO locations(name) VALUES (%s)",
            [("5A1",), ("5a1",), ("5A2",), ("BAD LOCATION",)],
        )
        cursor.executemany(
            "INSERT INTO parts(location, description) VALUES (%s, %s)",
            [
                ("5A1", ""),
                ("5A1", "M3 Bolt"),
                ("5A1", "M3 Bolt"),
                ("5a1", " m3  bolt "),
                ("5A2", "washer"),
            ],
        )
    conn.execute("ALTER TABLE parts DROP CONSTRAINT parts_location_fkey")
    conn.execute("INSERT INTO parts(location, description) VALUES ('GHOST', 'orphan')")


def table_snapshot(conn: psycopg.Connection) -> tuple[list[tuple], list[tuple]]:
    locations = list(
        conn.execute("SELECT name, verified_at FROM locations ORDER BY name")
    )
    parts = list(
        conn.execute(
            "SELECT id, location, description, embedding::text FROM parts ORDER BY id"
        )
    )
    return locations, parts


def test_audit_reports_all_finding_classes_without_writes(
    conn: psycopg.Connection,
) -> None:
    seed_findings(conn)
    before = table_snapshot(conn)

    report = run_audit(conn)

    assert table_snapshot(conn) == before
    assert report.summary == {
        "locations": 4,
        "parts": 6,
        "verified": 0,
        "unverified": 4,
    }
    codes = {finding.code for finding in report.findings}
    assert codes == {
        "empty_location",
        "blank_description",
        "exact_duplicate",
        "normalized_duplicate",
        "noncanonical_location_name",
        "case_colliding_location",
        "missing_embedding",
        "orphan_part",
    }

    conn.execute("DELETE FROM parts WHERE location = 'GHOST'")
    conn.execute(
        """ALTER TABLE parts ADD CONSTRAINT parts_location_fkey
        FOREIGN KEY (location) REFERENCES locations(name)"""
    )


def test_cli_writes_report_and_findings_exit_zero(
    database_dsn: str,
    conn: psycopg.Connection,
    tmp_path: Path,
    monkeypatch,
) -> None:
    seed_findings(conn)
    conn.commit()
    monkeypatch.setenv("PARTDB_DSN", database_dsn)
    output = tmp_path / "private" / "report.md"

    result = CliRunner().invoke(cli, ["audit", "--output", str(output)])

    assert result.exit_code == 0
    assert "wrote audit report" in result.output
    assert "blank_description" in output.read_text(encoding="utf-8")


def test_bad_database_does_not_create_output(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(
        "PARTDB_DSN", "postgresql://partdb@127.0.0.1:1/partdb?connect_timeout=1"
    )
    output = tmp_path / "report.md"

    result = CliRunner().invoke(cli, ["audit", "--output", str(output)])

    assert result.exit_code != 0
    assert not output.exists()
    assert "Error:" in result.output

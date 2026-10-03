import json
from pathlib import Path

import psycopg
import pytest
from click.testing import CliRunner

from partdb.cli import cli
from partdb.errors import PartNotFound
from partdb.inventory import InventoryService

pytestmark = pytest.mark.integration


@pytest.fixture
def seeded(database_dsn: str, conn: psycopg.Connection, monkeypatch) -> dict[str, int]:
    service = InventoryService(conn)
    for name in ("4A3", "1D1"):
        service.add_location(name)
    washers = service.add_part("4A3", "washers")
    junk = service.add_part("4A3", "junk")
    conn.commit()
    monkeypatch.setenv("PARTDB_DSN", database_dsn)
    return {"washers": washers.id, "junk": junk.id}


def plan_json(ids: dict[str, int]) -> str:
    return json.dumps(
        {
            "verify": True,
            "bins": {
                "4A3": {
                    "parts": [
                        {"id": ids["washers"], "description": "M3 washers"},
                        {"description": "M3 standoffs"},
                    ],
                    "remove": {str(ids["junk"]): "delete"},
                }
            },
        }
    )


def descriptions(conn: psycopg.Connection) -> list[str]:
    return sorted(row[0] for row in conn.execute("SELECT description FROM parts"))


def verified_count(conn: psycopg.Connection) -> int:
    return conn.execute(
        "SELECT count(*) FROM locations WHERE verified_at IS NOT NULL"
    ).fetchone()[0]


def write_plan(tmp_path: Path, ids: dict[str, int]) -> Path:
    path = tmp_path / "plan.json"
    path.write_text(plan_json(ids), encoding="utf-8")
    return path


def test_apply_from_stdin_prints_assigned_ids(
    seeded: dict[str, int], conn: psycopg.Connection
) -> None:
    result = CliRunner().invoke(cli, ["apply", "-", "--yes"], input=plan_json(seeded))

    assert result.exit_code == 0, result.output
    new_id = conn.execute(
        "SELECT id FROM parts WHERE description = 'M3 standoffs'"
    ).fetchone()[0]
    assert f'  + {new_id} "M3 standoffs"' in result.output
    assert f'  ~ {seeded["washers"]} "washers" -> "M3 washers"' in result.output
    assert f'  - {seeded["junk"]} "junk"' in result.output
    assert "  verified" in result.output
    assert descriptions(conn) == ["M3 standoffs", "M3 washers"]
    assert verified_count(conn) == 1


def test_apply_reads_a_plan_file(
    seeded: dict[str, int], conn: psycopg.Connection, tmp_path: Path
) -> None:
    path = write_plan(tmp_path, seeded)

    result = CliRunner().invoke(cli, ["apply", str(path), "--yes"])

    assert result.exit_code == 0, result.output
    assert descriptions(conn) == ["M3 standoffs", "M3 washers"]


def test_dry_run_shows_changes_and_writes_nothing(
    seeded: dict[str, int], conn: psycopg.Connection
) -> None:
    result = CliRunner().invoke(
        cli, ["apply", "-", "--dry-run"], input=plan_json(seeded)
    )

    assert result.exit_code == 0, result.output
    assert '  + new "M3 standoffs"' in result.output
    assert result.output.rstrip().endswith("dry run: no changes made")
    assert descriptions(conn) == ["junk", "washers"]
    assert verified_count(conn) == 0


def test_declined_confirmation_writes_nothing(
    seeded: dict[str, int], conn: psycopg.Connection, tmp_path: Path
) -> None:
    path = write_plan(tmp_path, seeded)

    result = CliRunner().invoke(cli, ["apply", str(path)], input="n\n")

    assert result.exit_code != 0
    assert "Apply these changes?" in result.output
    assert descriptions(conn) == ["junk", "washers"]
    assert verified_count(conn) == 0


def test_accepted_confirmation_applies(
    seeded: dict[str, int], conn: psycopg.Connection, tmp_path: Path
) -> None:
    path = write_plan(tmp_path, seeded)

    result = CliRunner().invoke(cli, ["apply", str(path)], input="y\n")

    assert result.exit_code == 0, result.output
    assert descriptions(conn) == ["M3 standoffs", "M3 washers"]


def test_invalid_plan_lists_problems_and_writes_nothing(
    seeded: dict[str, int], conn: psycopg.Connection
) -> None:
    bad = json.dumps({"bins": {"4A3": {"parts": [{"id": seeded["washers"]}]}}})

    result = CliRunner().invoke(cli, ["apply", "-", "--yes"], input=bad)

    assert result.exit_code != 0
    assert "invalid plan:" in result.output
    assert f'4A3: part {seeded["junk"]} "junk" is not accounted for' in result.output
    assert "Traceback" not in result.output
    assert descriptions(conn) == ["junk", "washers"]


def test_database_failure_rolls_back_whole_plan(
    seeded: dict[str, int], conn: psycopg.Connection, monkeypatch
) -> None:
    def fail(self: InventoryService, part_id: int) -> None:
        raise PartNotFound("simulated failure")

    monkeypatch.setattr(InventoryService, "delete_part", fail)

    result = CliRunner().invoke(cli, ["apply", "-", "--yes"], input=plan_json(seeded))

    assert result.exit_code != 0
    assert "simulated failure" in result.output
    assert descriptions(conn) == ["junk", "washers"]
    assert verified_count(conn) == 0

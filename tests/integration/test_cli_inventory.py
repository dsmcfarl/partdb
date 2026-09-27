import psycopg
import pytest
from click.testing import CliRunner

from partdb.cli import cli

pytestmark = pytest.mark.integration


@pytest.fixture
def runner(database_dsn: str, conn: psycopg.Connection, monkeypatch) -> CliRunner:
    monkeypatch.setenv("PARTDB_DSN", database_dsn)
    return CliRunner()


def test_existing_add_list_update_and_move_syntax(runner: CliRunner) -> None:
    assert runner.invoke(cli, ["add", "5A1"]).exit_code == 0
    assert runner.invoke(cli, ["add", "5A2"]).exit_code == 0
    added = runner.invoke(cli, ["add", "5A1", "M3 bolt"])
    assert added.exit_code == 0
    part_id = int(added.output.strip().split("id=")[1].rstrip(")"))

    listed = runner.invoke(cli, ["list", "5A1"])
    assert listed.exit_code == 0
    assert f"5A1: M3 bolt (id={part_id})" in listed.output

    assert runner.invoke(cli, ["update", str(part_id), "M3 screw"]).exit_code == 0
    assert runner.invoke(cli, ["move", str(part_id), "5A2"]).exit_code == 0
    assert "5A2: M3 screw" in runner.invoke(cli, ["list", "5A2"]).output
    assert "5A1\n5A2\n" == runner.invoke(cli, ["list", "--locations"]).output


def test_part_id_requires_an_integer(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["update", "abc", "description"])
    assert result.exit_code == 2
    assert "not a valid integer" in result.output


def test_aborted_delete_does_not_change_data(
    runner: CliRunner, conn: psycopg.Connection
) -> None:
    runner.invoke(cli, ["add", "5A1"])
    added = runner.invoke(cli, ["add", "5A1", "washer"])
    part_id = int(added.output.strip().split("id=")[1].rstrip(")"))

    result = runner.invoke(cli, ["delete", "--id", str(part_id)], input="n\n")

    assert result.exit_code == 1
    assert conn.execute("SELECT count(*) FROM parts").fetchone()[0] == 1


def test_unknown_delete_is_nonzero_and_keeps_rows(
    runner: CliRunner, conn: psycopg.Connection
) -> None:
    runner.invoke(cli, ["add", "5A1"])
    runner.invoke(cli, ["add", "5A1", "washer"])
    before = conn.execute("SELECT count(*) FROM parts").fetchone()[0]

    result = runner.invoke(cli, ["delete", "--id", "999", "--yes"])

    assert result.exit_code != 0
    assert "part 999 not found" in result.output
    assert conn.execute("SELECT count(*) FROM parts").fetchone()[0] == before


def test_delete_rejects_both_or_neither_target(runner: CliRunner) -> None:
    neither = runner.invoke(cli, ["delete", "--yes"])
    both = runner.invoke(cli, ["delete", "--id", "1", "--location", "5A1", "--yes"])
    assert neither.exit_code != 0
    assert "specify exactly one" in neither.output
    assert both.exit_code != 0
    assert "specify exactly one" in both.output


def test_populated_location_delete_does_not_cascade(
    runner: CliRunner, conn: psycopg.Connection
) -> None:
    runner.invoke(cli, ["add", "5A1"])
    runner.invoke(cli, ["add", "5A1", "washer"])

    result = runner.invoke(cli, ["delete", "--location", "5A1", "--yes"])

    assert result.exit_code != 0
    assert "location 5A1 is not empty" in result.output
    assert conn.execute("SELECT count(*) FROM parts").fetchone()[0] == 1

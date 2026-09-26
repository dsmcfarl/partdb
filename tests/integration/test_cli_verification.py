import psycopg
import pytest
from click.testing import CliRunner

from partdb.cli import cli
from partdb.inventory import InventoryService

pytestmark = pytest.mark.integration


@pytest.fixture
def runner(database_dsn: str, conn: psycopg.Connection, monkeypatch) -> CliRunner:
    service = InventoryService(conn)
    for name in ("5A1", "5A2", "5A3", "5A8"):
        service.add_location(name)
    service.add_part("5A1", "washer")
    service.add_part("5A3", "resistor")
    conn.commit()
    monkeypatch.setenv("PARTDB_DSN", database_dsn)
    return CliRunner()


def verified_count(conn: psycopg.Connection) -> int:
    return conn.execute(
        "SELECT count(*) FROM locations WHERE verified_at IS NOT NULL"
    ).fetchone()[0]


def test_inventory_command_shows_empty_bins_and_parts(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["inventory", "--from", "5A1", "--through", "5A3"])
    assert result.exit_code == 0
    assert result.output.index("5A1 [unverified]") < result.output.index(
        "5A2 [unverified]"
    )
    assert "  washer (id=" in result.output
    assert "5A2 [unverified]\n  (empty)" in result.output


def test_mark_range_displays_then_confirms(
    runner: CliRunner, conn: psycopg.Connection
) -> None:
    result = runner.invoke(
        cli,
        ["verify", "mark", "--from", "5A1", "--through", "5A3"],
        input="y\n",
    )
    assert result.exit_code == 0
    assert "5A2 [unverified]\n  (empty)" in result.output
    assert "marked 3 locations verified" in result.output
    assert verified_count(conn) == 3


def test_declined_range_confirmation_writes_nothing(
    runner: CliRunner, conn: psycopg.Connection
) -> None:
    result = runner.invoke(
        cli,
        ["verify", "mark", "--from", "5A1", "--through", "5A3"],
        input="n\n",
    )
    assert result.exit_code == 1
    assert verified_count(conn) == 0


def test_yes_marks_range_without_prompt(
    runner: CliRunner, conn: psycopg.Connection
) -> None:
    result = runner.invoke(
        cli,
        [
            "verify",
            "mark",
            "--from",
            "5A1",
            "--through",
            "5A3",
            "--yes",
        ],
    )
    assert result.exit_code == 0
    assert "Proceed?" not in result.output
    assert verified_count(conn) == 3


@pytest.mark.parametrize(
    "arguments,message",
    [
        (["5A1", "--from", "5A1", "--through", "5A3"], "cannot combine"),
        (["--from", "5A1"], "both --from and --through"),
        (["--from", "5A9", "--through", "5A10"], "unknown range endpoint"),
        (["--from", "5A3", "--through", "5A1"], "range is reversed"),
    ],
)
def test_invalid_mark_forms_write_nothing(
    runner: CliRunner,
    conn: psycopg.Connection,
    arguments: list[str],
    message: str,
) -> None:
    result = runner.invoke(cli, ["verify", "mark", *arguments, "--yes"])
    assert result.exit_code != 0
    assert message in result.output
    assert verified_count(conn) == 0


def test_ambiguous_range_writes_nothing(
    runner: CliRunner, conn: psycopg.Connection
) -> None:
    conn.execute("INSERT INTO locations(name) VALUES ('5a1')")
    conn.commit()
    result = runner.invoke(
        cli,
        [
            "verify",
            "mark",
            "--from",
            "5A1",
            "--through",
            "5A3",
            "--yes",
        ],
    )
    assert result.exit_code != 0
    assert "ambiguous range endpoint" in result.output
    assert verified_count(conn) == 0


def test_clear_and_unverified_status(
    runner: CliRunner, conn: psycopg.Connection
) -> None:
    assert runner.invoke(cli, ["verify", "mark", "5A1", "5A2", "--yes"]).exit_code == 0
    clear = runner.invoke(cli, ["verify", "clear", "5A2", "--yes"])
    assert clear.exit_code == 0

    result = runner.invoke(cli, ["verify", "status", "--unverified"])

    assert result.exit_code == 0
    assert "verified 1/4; unverified 3" in result.output
    assert result.output.index("5A2") < result.output.index("5A3")
    assert result.output.index("5A3") < result.output.index("5A8")
    assert "5A1" not in result.output.splitlines()[1:]

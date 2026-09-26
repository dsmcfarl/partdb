from click.testing import CliRunner

from partdb.cli import cli


def test_help_lists_top_level_commands() -> None:
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Manage workshop parts and locations" in result.output


def test_version_is_installed() -> None:
    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "partdb, version 0.2.0" in result.output

from importlib.metadata import version

import click
import psycopg

from partdb.database import connect
from partdb.migrate import apply_migrations


@click.group(name="partdb")
@click.version_option(version("partdb"))
def cli() -> None:
    """Manage workshop parts and locations."""


@cli.group()
def db() -> None:
    """Manage the PartDB database."""


@db.command("migrate")
def migrate_database() -> None:
    """Apply all pending database migrations."""
    try:
        with connect() as conn:
            completed = apply_migrations(conn)
    except psycopg.Error as exc:
        raise click.ClickException(str(exc)) from exc
    if completed:
        click.echo("applied migrations: " + ", ".join(completed))
    else:
        click.echo("database already current")

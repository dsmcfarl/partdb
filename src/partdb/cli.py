from collections.abc import Iterator
from contextlib import contextmanager
from importlib.metadata import version
from pathlib import Path

import click
import psycopg

from partdb.database import connect
from partdb.embeddings import OpenAIEmbeddingProvider
from partdb.errors import PartDBError
from partdb.inventory import InventoryService
from partdb.migrate import apply_migrations


@click.group(name="partdb")
@click.version_option(version("partdb"))
def cli() -> None:
    """Manage workshop parts and locations."""


@contextmanager
def inventory_service() -> Iterator[InventoryService]:
    try:
        with connect() as conn:
            yield InventoryService(conn)
    except (PartDBError, ValueError, psycopg.Error) as exc:
        raise click.ClickException(str(exc)) from exc


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


@cli.command()
@click.argument("location")
@click.argument("description", required=False)
def add(location: str, description: str | None) -> None:
    """Add a location, or add a described part to a location."""
    with inventory_service() as service:
        if description is None:
            item = service.add_location(location)
            click.echo(f"added location {item.name}")
        else:
            part = service.add_part(location, description)
            click.echo(f"{part.location}: {part.description} (id={part.id})")


@cli.command("list")
@click.option("--locations", is_flag=True, help="List locations instead of parts")
@click.argument("location", required=False)
def list_inventory(locations: bool, location: str | None) -> None:
    """List parts, optionally restricted to one location."""
    with inventory_service() as service:
        if locations:
            if location is not None:
                raise click.ClickException(
                    "LOCATION cannot be combined with --locations"
                )
            for item in service.list_locations():
                click.echo(item.name)
            return
        for part in service.list_parts(location):
            click.echo(f"{part.location}: {part.description} (id={part.id})")


@cli.command()
@click.argument("part_id", type=int)
@click.argument("description")
def update(part_id: int, description: str) -> None:
    """Update a part description and clear its stale embedding."""
    with inventory_service() as service:
        part = service.update_part(part_id, description)
        click.echo(f"{part.location}: {part.description} (id={part.id})")


@cli.command()
@click.argument("part_id", type=int)
@click.argument("location")
def move(part_id: int, location: str) -> None:
    """Move a part to an existing location."""
    with inventory_service() as service:
        part = service.move_part(part_id, location)
        click.echo(f"{part.location}: {part.description} (id={part.id})")


@cli.command()
@click.option("--location", help="Location to delete")
@click.option("--id", "part_id", type=int, help="Part ID to delete")
@click.option("--yes", is_flag=True, help="Skip confirmation")
def delete(location: str | None, part_id: int | None, yes: bool) -> None:
    """Delete exactly one part or empty location."""
    if (location is None) == (part_id is None):
        raise click.ClickException("specify exactly one of --location or --id")
    target = f"location {location}" if location is not None else f"part {part_id}"
    if not yes:
        click.confirm(f"Delete {target}?", abort=True)
    with inventory_service() as service:
        if location is not None:
            service.delete_location(location)
        else:
            assert part_id is not None
            service.delete_part(part_id)
    click.echo(f"deleted {target}")


@cli.command()
@click.option("--full-text", is_flag=True, help="Use PostgreSQL full-text search")
@click.argument("description")
def search(full_text: bool, description: str) -> None:
    """Search part descriptions."""
    with inventory_service() as service:
        if full_text:
            results = service.search_full_text(description)
        else:
            results = service.search_semantic(OpenAIEmbeddingProvider(), description)
        for result in results:
            details = []
            if result.distance is not None:
                details.append(f"distance={result.distance:.3f}")
            details.append(
                "empty="
                + ",".join(
                    value
                    for value in (result.previous_empty, result.next_empty)
                    if value is not None
                )
            )
            click.echo(
                f"{result.location}: {result.description} "
                f"(id={result.id}, {', '.join(details)})"
            )


@cli.command()
@click.option(
    "--path",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path.cwd,
    show_default="current directory",
)
def dumpdb(path: Path) -> None:
    """Export locations and parts to CSV files."""
    with inventory_service() as service:
        service.dump_csv(path)
    click.echo(f"dumped data to {path}")


@cli.command()
@click.option(
    "--path",
    type=click.Path(path_type=Path, file_okay=False, exists=True),
    default=Path.cwd,
    show_default="current directory",
)
def loaddb(path: Path) -> None:
    """Load locations and parts from CSV files."""
    with inventory_service() as service:
        service.load_csv(path)
    click.echo(f"loaded data from {path}")


@cli.group()
def embeddings() -> None:
    """Manage optional semantic-search embeddings."""


@embeddings.command("refresh")
@click.option("--all", "refresh_all", is_flag=True, help="Refresh every part")
def refresh_embeddings(refresh_all: bool) -> None:
    """Create embeddings for parts that do not have one."""
    with inventory_service() as service:
        count = service.refresh_embeddings(
            OpenAIEmbeddingProvider(), refresh_all=refresh_all
        )
    click.echo(f"updated {count} embeddings")

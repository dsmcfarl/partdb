from typing import Optional, List
import click
import psycopg
from psycopg import sql
import os

from openai import OpenAI


DBNAME = "partdb"
DBUSER = "partdb"


@click.group()
def cli():
    """
    Manage parts and locations.
    """
    pass


@cli.command()
@click.argument("location")
@click.argument("description", required=False)
def add(location: str, description: Optional[str] = None) -> None:
    """
    Add a new location or part.

    LOCATION: name of the location to add
    DESCRIPTION: description of the part to add (optional)
    """
    with psycopg.connect("service=partdb") as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO locations (name) VALUES (%s) ON CONFLICT DO NOTHING",
                (location,),
            )
            if description:
                client = OpenAI()
                embedding = _get_embedding(client, description)
                cur.execute(
                    "INSERT INTO parts (description, location, embedding) VALUES (%s, %s, %s)",
                    (description, location, embedding),
                )


@cli.command()
@click.option("--location", help="Name of the location to delete")
@click.option("--id", help="ID of the part to delete")
def delete(location: Optional[str] = None, id: Optional[int] = None) -> None:
    """
    Delete a location or part.
    """
    if not location and not id:
        raise click.ClickException("must specify either --location or --id")
    if location and id:
        raise click.ClickException("cannot specify both --location and --id")
    with psycopg.connect("service=partdb") as conn:
        with conn.cursor() as cur:
            if location:
                cur.execute("DELETE FROM locations WHERE name = %s", (location,))
            else:
                cur.execute("DELETE FROM parts WHERE id = %s", (id,))


@cli.command()
def dropdb():
    """
    Drop the partdb database.
    """
    click.confirm(f"Do you want to drop database '{DBNAME}'?", abort=True)
    with psycopg.connect("service=partdb-superuser", autocommit=True) as conn:
        dbname = sql.Identifier(DBNAME)
        conn.execute(sql.SQL("DROP DATABASE {}").format(dbname))
    click.echo("database drop complete")


@cli.command()
@click.option(
    "--path",
    help="Path to the directory that will contain the locations.csv and parts.csv files; will be created if it doesn't exist; defaults to the current directory",
)
def dumpdb(path):
    """
    Create two csv files: locations.csv and parts.csv.
    """
    locations_csv, parts_csv = _validate_path(path, mkdir=True)

    import csv

    with psycopg.connect("service=partdb") as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM locations ORDER BY name")
            if not cur.description:
                click.echo("no locations to dump")
                return
            with open(locations_csv, "w") as f:
                writer = csv.writer(f)
                writer.writerow([desc[0] for desc in cur.description])
                writer.writerows(cur.fetchall())

            cur.execute(
                "SELECT location, description FROM parts ORDER BY location, description"
            )
            if not cur.description:
                click.echo("no locations to dump")
                return
            with open(parts_csv, "w") as f:
                writer = csv.writer(f)
                writer.writerow([desc[0] for desc in cur.description])
                writer.writerows(cur.fetchall())
    click.echo(f"dumped data to {locations_csv} and {parts_csv}")


@cli.command()
def initdb():
    """
    Initialize the database.
    """
    # must use the postgres superuser and default postgres database to create the partdb database and role
    with psycopg.connect("service=partdb-superuser", autocommit=True) as conn:
        dbname = sql.Identifier(DBNAME)
        dbuser = sql.Identifier(DBUSER)
        conn.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(dbuser))
        conn.execute(sql.SQL("CREATE ROLE {} WITH LOGIN").format(dbuser))
        conn.execute(
            sql.SQL("ALTER ROLE {} SET client_encoding TO 'utf8'").format(dbuser)
        )
        conn.execute(
            sql.SQL(
                "ALTER ROLE {} SET default_transaction_isolation TO 'read committed'"
            ).format(dbuser)
        )
        conn.execute(sql.SQL("ALTER ROLE {} SET timezone TO 'UTC'").format(dbuser))
        click.echo(f"created user '{DBUSER}'")
        conn.execute(sql.SQL("CREATE DATABASE {} WITH OWNER {}").format(dbname, dbuser))
        click.echo(f"created database '{DBNAME}'")

    # extensions are per database, but must be created by a superuser
    with psycopg.connect(
        f"service=partdb-superuser dbname={DBNAME}", autocommit=True
    ) as conn:
        conn.execute("CREATE EXTENSION vector")
    click.echo("created extension 'vector'")

    # now we can connect as the partdb user and create the tables
    with psycopg.connect("service=partdb") as conn:
        conn.execute("""
            CREATE TABLE locations (name VARCHAR(255) PRIMARY KEY);
            CREATE TABLE parts (
              id SERIAL PRIMARY KEY,
              location VARCHAR(255),
              description TEXT,
              embedding vector(1536),
              FOREIGN KEY (location) REFERENCES locations(name)
            );""")
    click.echo("created tables in 'partdb'")
    click.echo("database initialization complete")


@cli.command()
@click.option("--locations", is_flag=True, help="List locations instead of parts")
@click.argument("location", required=False)
def list(locations: bool = False, location: Optional[str] = None) -> None:
    """
    List locations or parts.

    LOCATION: name of the location to list parts/locations for (optional)
    """
    with psycopg.connect("service=partdb") as conn:
        with conn.cursor() as cur:
            if locations:
                if location:
                    cur.execute(
                        "SELECT name FROM locations WHERE name = %s", (location,)
                    )
                else:
                    cur.execute("SELECT name FROM locations ORDER BY name")
                for row in cur.fetchall():
                    click.echo(row[0])
            else:
                if location:
                    cur.execute(
                        "SELECT id, location, description FROM parts WHERE location = %s ORDER BY description",
                        (location,),
                    )
                else:
                    cur.execute(
                        "SELECT id, location, description FROM parts ORDER BY location, description"
                    )
                for row in cur.fetchall():
                    click.echo(f"{row[1]}: {row[2]} (id={row[0]})")


@cli.command()
@click.option(
    "--path",
    help="Path to the directory containing the locations.csv and parts.csv files; defaults to the current directory",
)
def loaddb(path):
    """
    Load data from locations.csv and parts.csv.
    """
    locations_csv, parts_csv = _validate_path(path)

    import csv

    with psycopg.connect("service=partdb") as conn:
        with conn.cursor() as cur:
            with open(locations_csv, "r") as f:
                reader = csv.reader(f)
                next(reader)  # skip header
                for row in reader:
                    cur.execute("INSERT INTO locations (name) VALUES (%s)", row)
            with open(parts_csv, "r") as f:
                reader = csv.reader(f)
                next(reader)  # skip header
                for row in reader:
                    cur.execute(
                        "INSERT INTO parts (location, description) VALUES (%s, %s)", row
                    )

    click.echo(f"loaded data from {locations_csv} and {parts_csv}")


@cli.command()
@click.argument("id")
@click.argument("location")
def move(id: int, location: str) -> None:
    """
    Move a part to a new location.

    ID: id of the part to move
    LOCATION: new location for the part
    """
    with psycopg.connect("service=partdb") as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE parts SET location = %s WHERE id = %s", (location, id))


@cli.command()
@click.option(
    "--full-text",
    is_flag=True,
    help="Use full text search instead of vector similarity",
)
@click.argument("description")
def search(full_text, description):
    """
    Search for a part by description.

    DESCRIPTION: description of the part to search for
    """
    if full_text:
        with psycopg.connect("service=partdb") as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, description, location,
                    (
                      SELECT name
                      FROM locations
                      WHERE name < p.location
                      AND NOT EXISTS (SELECT 1 FROM parts WHERE location = name)
                      ORDER BY name DESC
                      LIMIT 1
                    ) AS prev_empty,
                    (
                      SELECT name
                      FROM locations
                      WHERE name > p.location
                      AND NOT EXISTS (SELECT 1 FROM parts WHERE location = name)
                      ORDER BY name
                      LIMIT 1
                    ) AS next_empty
                    FROM parts p WHERE to_tsvector(description) @@ websearch_to_tsquery(%s)
                    """,
                    (description,),
                )
                for row in cur.fetchall():
                    click.echo(
                        f"{row[2]}: {row[1]} (id={row[0]}, empty={row[3]},{row[4]})"
                    )
    else:
        from openai import OpenAI

        client = OpenAI()
        response = client.embeddings.create(
            input=description.replace("\n", " ")[:8191], model="text-embedding-3-small"
        )
        embedding = response.data[0].embedding
        with psycopg.connect("service=partdb") as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, description, location, embedding <=> %s AS distance,
                    (
                      SELECT name
                      FROM locations
                      WHERE name < p.location
                      AND NOT EXISTS (SELECT 1 FROM parts WHERE location = name)
                      ORDER BY name DESC
                      LIMIT 1
                    ) AS prev_empty,
                    (
                      SELECT name
                      FROM locations
                      WHERE name > p.location
                      AND NOT EXISTS (SELECT 1 FROM parts WHERE location = name)
                      ORDER BY name
                      LIMIT 1
                    ) AS next_empty
                    FROM parts p ORDER BY distance LIMIT 10
                    """,
                    (str(embedding),),
                )
                for row in cur.fetchall():
                    click.echo(
                        f"{row[2]}: {row[1]} (id={row[0]}, dist={row[3]:.3f}, empty={row[4]},{row[5]})"
                    )


@cli.command()
@click.argument("id")
@click.argument("description")
def update(id: int, description: str) -> None:
    """
    Update the description of a part.

    ID: id of the part to update
    DESCRIPTION: new description for the part
    """
    with psycopg.connect("service=partdb") as conn:
        with conn.cursor() as cur:
            client = OpenAI()
            embedding = _get_embedding(client, description)
            cur.execute(
                "UPDATE parts SET description = %s, embedding = %s WHERE id = %s",
                (description, embedding, id),
            )


@cli.command()
def update_embeddings():
    """
    Update the embeddings for all parts.
    """
    click.echo("updating embeddings")

    client = OpenAI()
    with psycopg.connect("service=partdb") as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, description FROM parts")
            with click.progressbar(cur.fetchall()) as bar:
                for part_row in bar:
                    embedding = _get_embedding(client, part_row[1])
                    cur.execute(
                        "UPDATE parts SET embedding = %s WHERE id = %s",
                        (embedding, part_row[0]),
                    )


def _get_embedding(client: OpenAI, description: str) -> List[float]:
    response = client.embeddings.create(
        input=description.replace("\n", " ")[:8191],
        model="text-embedding-3-small",
    )
    return response.data[0].embedding


def _validate_path(path: Optional[str], mkdir: bool = False) -> tuple[str, str]:
    if path is None:
        path = os.getcwd()
    if not os.path.exists(path):
        if mkdir:
            os.makedirs(path)
        else:
            raise click.ClickException(f"path '{path}' does not exist")
    if not os.path.isdir(path):
        raise click.ClickException(f"path '{path}' is not a directory")
    locations_csv = os.path.join(path, "locations.csv")
    parts_csv = os.path.join(path, "parts.csv")
    if mkdir:
        return locations_csv, parts_csv
    else:
        if not os.path.exists(locations_csv):
            raise click.ClickException(f"locations.csv not found in '{path}'")
        if not os.path.exists(parts_csv):
            raise click.ClickException(f"parts.csv not found in '{path}'")
        return locations_csv, parts_csv


if __name__ == "__main__":
    cli()

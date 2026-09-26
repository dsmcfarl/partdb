import csv
from pathlib import Path

import psycopg
import pytest
from click.testing import CliRunner

from partdb.cli import cli
from partdb.inventory import InventoryService

pytestmark = pytest.mark.integration


class FakeProvider:
    def embed(self, text: str) -> list[float]:
        return [float(len(text))] * 1536


def seeded_service(conn: psycopg.Connection) -> InventoryService:
    service = InventoryService(conn)
    for location in ("5A1", "5A2", "5A3", "5A4"):
        service.add_location(location)
    first = service.add_part("5A1", "10k resistor")
    service.add_part("5A3", "ceramic capacitor")
    service.add_part("5A3", "precision resistor")
    conn.execute(
        """UPDATE parts
        SET embedding = array_fill(0.5::real, ARRAY[1536])::vector
        WHERE id = %s""",
        (first.id,),
    )
    return service


def test_refresh_only_missing_embeddings(conn: psycopg.Connection) -> None:
    service = seeded_service(conn)

    changed = service.refresh_embeddings(FakeProvider(), refresh_all=False)

    assert changed == 2
    assert (
        conn.execute("SELECT count(*) FROM parts WHERE embedding IS NULL").fetchone()[0]
        == 0
    )


def test_full_text_search_supports_web_query_and_nearest_empty_locations(
    conn: psycopg.Connection,
) -> None:
    service = seeded_service(conn)

    results = service.search_full_text("resistor -precision")

    assert [result.description for result in results] == ["10k resistor"]
    assert results[0].next_empty == "5A2"
    assert results[0].previous_empty is None


def test_full_text_search_stems_english_terms(conn: psycopg.Connection) -> None:
    service = InventoryService(conn)
    service.add_location("5A1")
    service.add_part("5A1", "assorted resistors")

    results = service.search_full_text("resistor")

    assert [result.description for result in results] == ["assorted resistors"]


def test_search_uses_natural_order_for_empty_neighbors(
    conn: psycopg.Connection,
) -> None:
    service = InventoryService(conn)
    for name in ("5A1", "5A2", "5A10"):
        service.add_location(name)
    service.add_part("5A1", "resistor")
    service.add_part("5A10", "capacitor")

    resistor = service.search_full_text("resistor")[0]
    capacitor = service.search_full_text("capacitor")[0]

    assert resistor.next_empty == "5A2"
    assert capacitor.previous_empty == "5A2"


def test_semantic_search_excludes_missing_embeddings(
    conn: psycopg.Connection,
) -> None:
    service = seeded_service(conn)

    results = service.search_semantic(FakeProvider(), "resistor", limit=10)

    assert [result.description for result in results] == ["10k resistor"]
    assert results[0].distance is not None


def test_csv_dump_and_load_round_trip(conn: psycopg.Connection, tmp_path: Path) -> None:
    service = seeded_service(conn)
    service.dump_csv(tmp_path)

    assert (tmp_path / "locations.csv").read_text().splitlines()[0] == "name"
    assert (tmp_path / "parts.csv").read_text().splitlines()[0] == (
        "location,description"
    )

    conn.execute("DELETE FROM parts")
    conn.execute("DELETE FROM locations")
    service.load_csv(tmp_path)

    assert len(service.list_locations()) == 4
    assert [part.description for part in service.list_parts()] == [
        "10k resistor",
        "ceramic capacitor",
        "precision resistor",
    ]
    assert all(not part.has_embedding for part in service.list_parts())


def test_malformed_csv_is_rejected_before_any_insert(
    conn: psycopg.Connection, tmp_path: Path
) -> None:
    with (tmp_path / "locations.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["name"])
        writer.writeheader()
        writer.writerow({"name": "5A1"})
    with (tmp_path / "parts.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["location", "description"])
        writer.writeheader()
        writer.writerow({"location": "5A1", "description": " "})

    with pytest.raises(ValueError, match="blank"):
        InventoryService(conn).load_csv(tmp_path)

    assert conn.execute("SELECT count(*) FROM locations").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM parts").fetchone()[0] == 0


def test_case_colliding_csv_locations_are_rejected_before_any_insert(
    conn: psycopg.Connection, tmp_path: Path
) -> None:
    (tmp_path / "locations.csv").write_text("name\n5A1\n5a1\n", encoding="utf-8")
    (tmp_path / "parts.csv").write_text("location,description\n", encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate location 5a1"):
        InventoryService(conn).load_csv(tmp_path)

    assert conn.execute("SELECT count(*) FROM locations").fetchone()[0] == 0


def test_unknown_csv_location_is_rejected_before_any_insert(
    conn: psycopg.Connection, tmp_path: Path
) -> None:
    (tmp_path / "locations.csv").write_text("name\n5A1\n", encoding="utf-8")
    (tmp_path / "parts.csv").write_text(
        "location,description\n5A2,washer\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="unknown location 5A2"):
        InventoryService(conn).load_csv(tmp_path)

    assert conn.execute("SELECT count(*) FROM locations").fetchone()[0] == 0


def test_semantic_cli_without_key_has_clear_error(
    database_dsn: str, conn: psycopg.Connection, monkeypatch
) -> None:
    seeded_service(conn)
    conn.commit()
    monkeypatch.setenv("PARTDB_DSN", database_dsn)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = CliRunner().invoke(cli, ["search", "resistor"])

    assert result.exit_code != 0
    assert "OPENAI_API_KEY is not configured" in result.output
    assert "Traceback" not in result.output

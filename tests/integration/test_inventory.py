import psycopg
import pytest

from partdb.errors import (
    DuplicateLocation,
    LocationNotEmpty,
    LocationNotFound,
    PartNotFound,
)
from partdb.inventory import InventoryService

pytestmark = pytest.mark.integration


def test_crud_lists_parts_and_locations(conn: psycopg.Connection) -> None:
    service = InventoryService(conn)
    location = service.add_location("5A1")
    part = service.add_part("5A1", "M3 bolt")

    assert location.name == "5A1"
    assert location.verified_at is None
    assert service.list_locations() == [location]
    assert service.list_parts("5A1") == [part]

    moved_location = service.add_location("5A2")
    moved = service.move_part(part.id, moved_location.name)
    assert moved.location == "5A2"

    service.delete_part(part.id)
    assert service.part_count() == 0
    service.delete_location("5A1")
    assert [item.name for item in service.list_locations()] == ["5A2"]


def test_locations_are_listed_in_natural_order(conn: psycopg.Connection) -> None:
    service = InventoryService(conn)
    for name in ("5A10", "5A2", "5A1"):
        service.add_location(name)

    assert [location.name for location in service.list_locations()] == [
        "5A1",
        "5A2",
        "5A10",
    ]


def test_update_description_clears_stale_embedding(conn: psycopg.Connection) -> None:
    service = InventoryService(conn)
    service.add_location("5A1")
    part = service.add_part("5A1", "M3 bolt")
    conn.execute(
        """UPDATE parts
        SET embedding = array_fill(0.1::real, ARRAY[1536])::vector
        WHERE id=%s""",
        (part.id,),
    )

    updated = service.update_part(part.id, "M3 socket head bolt")

    assert updated.description == "M3 socket head bolt"
    assert updated.has_embedding is False
    assert conn.execute(
        "SELECT description, embedding IS NULL FROM parts WHERE id=%s", (part.id,)
    ).fetchone() == ("M3 socket head bolt", True)


def test_move_to_unknown_location_does_not_move_part(
    conn: psycopg.Connection,
) -> None:
    service = InventoryService(conn)
    service.add_location("5A1")
    part = service.add_part("5A1", "washer")

    with pytest.raises(LocationNotFound, match="5B1"):
        service.move_part(part.id, "5B1")

    assert service.get_part(part.id).location == "5A1"


def test_unknown_part_delete_does_not_change_rows(conn: psycopg.Connection) -> None:
    service = InventoryService(conn)
    before = service.part_count()

    with pytest.raises(PartNotFound, match="999"):
        service.delete_part(999)

    assert service.part_count() == before


def test_rejects_duplicate_location_and_blank_values(
    conn: psycopg.Connection,
) -> None:
    service = InventoryService(conn)
    service.add_location("5A1")
    with pytest.raises(DuplicateLocation, match="5A1"):
        service.add_location("5A1")
    with pytest.raises(DuplicateLocation, match="5a1"):
        service.add_location("5a1")
    with pytest.raises(ValueError, match="blank"):
        service.add_location(" ")
    with pytest.raises(ValueError, match="blank"):
        service.add_part("5A1", " ")


def test_populated_location_cannot_be_deleted(conn: psycopg.Connection) -> None:
    service = InventoryService(conn)
    service.add_location("5A1")
    service.add_part("5A1", "washer")

    with pytest.raises(LocationNotEmpty, match="5A1"):
        service.delete_location("5A1")

    assert service.part_count() == 1

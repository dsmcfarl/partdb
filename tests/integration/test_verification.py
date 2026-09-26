from datetime import UTC, datetime

import psycopg
import pytest

from partdb.inventory import InventoryService

pytestmark = pytest.mark.integration


def seed(service: InventoryService) -> tuple[int, int]:
    for name in ("5A1", "5A2", "5A3", "5A8"):
        service.add_location(name)
    first = service.add_part("5A1", "washer")
    second = service.add_part("5A3", "resistor")
    return first.id, second.id


def test_inventory_range_includes_empty_locations_and_groups_parts(
    conn: psycopg.Connection,
) -> None:
    service = InventoryService(conn)
    seed(service)

    inventory = service.inventory_range("5a1", "5A3")

    assert [location.name for location in inventory] == ["5A1", "5A2", "5A3"]
    assert [part.description for part in inventory[0].parts] == ["washer"]
    assert inventory[1].parts == ()
    assert [part.description for part in inventory[2].parts] == ["resistor"]


def test_mark_and_clear_verification_update_exact_names(
    conn: psycopg.Connection,
) -> None:
    service = InventoryService(conn)
    seed(service)
    fixed = datetime(2026, 9, 26, 15, 30, tzinfo=UTC)

    assert service.mark_verified(["5A1", "5A3"], verified_at=fixed) == 2
    status = {
        location.name: location.verified_at for location in service.list_locations()
    }
    assert status == {"5A1": fixed, "5A2": None, "5A3": fixed, "5A8": None}

    assert service.clear_verification(["5A3"]) == 1
    assert {
        location.name: location.verified_at for location in service.list_locations()
    }["5A3"] is None


def test_recorded_inventory_changes_do_not_clear_verification(
    conn: psycopg.Connection,
) -> None:
    service = InventoryService(conn)
    first_id, second_id = seed(service)
    fixed = datetime(2026, 9, 26, 15, 30, tzinfo=UTC)
    service.mark_verified(["5A1", "5A2", "5A3"], verified_at=fixed)

    added = service.add_part("5A1", "new item")
    service.update_part(first_id, "updated washer")
    service.move_part(second_id, "5A2")
    service.delete_part(added.id)

    status = {
        location.name: location.verified_at for location in service.list_locations()
    }
    assert status["5A1"] == fixed
    assert status["5A2"] == fixed
    assert status["5A3"] == fixed


def test_verification_status_filters_and_sorts_naturally(
    conn: psycopg.Connection,
) -> None:
    service = InventoryService(conn)
    for name in ("5A10", "5A2", "5A1"):
        service.add_location(name)
    service.mark_verified(["5A2"])

    assert [item.name for item in service.verification_status()] == [
        "5A1",
        "5A2",
        "5A10",
    ]
    assert [item.name for item in service.verification_status(True)] == [
        "5A1",
        "5A10",
    ]

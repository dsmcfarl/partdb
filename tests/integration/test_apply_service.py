import json

import psycopg
import pytest

from partdb.apply import Plan, PlanError, parse_plan
from partdb.errors import PartNotFound
from partdb.inventory import InventoryService

pytestmark = pytest.mark.integration


@pytest.fixture
def service(conn: psycopg.Connection) -> InventoryService:
    service = InventoryService(conn)
    for name in ("4A3", "4A4", "1D1", "5A6"):
        service.add_location(name)
    conn.commit()
    return service


def plan(data: dict) -> Plan:
    return parse_plan(json.dumps(data))


def set_embedding(conn: psycopg.Connection, part_id: int) -> None:
    conn.execute(
        """UPDATE parts
        SET embedding = array_fill(0.1::real, ARRAY[1536])::vector
        WHERE id = %s""",
        (part_id,),
    )


def verified(service: InventoryService) -> set[str]:
    return {
        location.name
        for location in service.list_locations()
        if location.verified_at is not None
    }


def test_applies_every_change_kind_and_verifies_listed_bins(
    service: InventoryService,
) -> None:
    keep = service.add_part("4A3", "washers")
    update = service.add_part("4A3", "tantalum caps")
    delete = service.add_part("4A3", "junk")
    move_out = service.add_part("4A3", "solder")
    move_in = service.add_part("5A6", "regulator")

    diff = service.plan_changes(
        plan(
            {
                "verify": True,
                "bins": {
                    "4A3": {
                        "parts": [
                            {"id": keep.id},
                            {"id": update.id, "description": "film caps"},
                            {"id": move_in.id},
                            {"description": "M3 standoffs"},
                        ],
                        "remove": {
                            str(delete.id): "delete",
                            str(move_out.id): {"move": "1D1"},
                        },
                    }
                },
            }
        )
    )
    assert [change.kind for change in diff.bins[0].changes] == [
        "keep",
        "update",
        "move_in",
        "add",
        "delete",
        "move_out",
    ]

    applied = service.apply_changes(diff)

    added = applied.bins[0].changes[3]
    assert added.part_id is not None
    assert {(part.id, part.description) for part in service.list_parts("4A3")} == {
        (keep.id, "washers"),
        (update.id, "film caps"),
        (move_in.id, "regulator"),
        (added.part_id, "M3 standoffs"),
    }
    assert service.get_part(move_out.id).location == "1D1"
    with pytest.raises(PartNotFound):
        service.get_part(delete.id)
    assert verified(service) == {"4A3"}


def test_unaccounted_part_rejects_plan(service: InventoryService) -> None:
    listed = service.add_part("4A3", "washers")
    forgotten = service.add_part("4A3", "springs")

    with pytest.raises(PlanError) as excinfo:
        service.plan_changes(plan({"bins": {"4A3": {"parts": [{"id": listed.id}]}}}))

    assert (
        f'4A3: part {forgotten.id} "springs" is not accounted for'
        in excinfo.value.problems
    )


def test_missing_location_requires_create(service: InventoryService) -> None:
    with pytest.raises(PlanError) as excinfo:
        service.plan_changes(plan({"bins": {"4A9": {"parts": []}}}))
    assert "4A9: location not found (set create to add it)" in excinfo.value.problems


def test_create_adds_and_verifies_location(service: InventoryService) -> None:
    diff = service.plan_changes(
        plan({"verify": True, "bins": {"4A9": {"create": True, "parts": []}}})
    )

    applied = service.apply_changes(diff)

    assert applied.bins[0].created is True
    assert "4A9" in verified(service)


def test_names_resolve_case_insensitively_without_creating(
    service: InventoryService,
) -> None:
    part = service.add_part("4A3", "washers")

    diff = service.plan_changes(
        plan({"bins": {"4a3": {"create": True, "parts": [{"id": part.id}]}}})
    )
    service.apply_changes(diff)

    assert diff.bins[0].name == "4A3"
    assert diff.bins[0].created is False
    assert [location.name for location in service.list_locations()] == [
        "1D1",
        "4A3",
        "4A4",
        "5A6",
    ]


def test_reports_unknown_parts_foreign_removals_and_missing_targets(
    service: InventoryService,
) -> None:
    here = service.add_part("4A3", "washers")
    other = service.add_part("4A3", "solder")
    elsewhere = service.add_part("4A4", "nuts")

    with pytest.raises(PlanError) as excinfo:
        service.plan_changes(
            plan(
                {
                    "bins": {
                        "4A3": {
                            "parts": [{"id": here.id}, {"id": 999999}],
                            "remove": {
                                str(elsewhere.id): "delete",
                                str(other.id): {"move": "9Z9"},
                            },
                        }
                    }
                }
            )
        )

    assert set(excinfo.value.problems) == {
        "part 999999 not found",
        f"4A3: part {elsewhere.id} is not in 4A3",
        "4A3: move target 9Z9 not found",
    }


def test_part_moved_between_plan_bins_needs_no_removal(
    service: InventoryService,
) -> None:
    part = service.add_part("4A3", "regulator")

    diff = service.plan_changes(
        plan({"bins": {"4A3": {"parts": []}, "4A4": {"parts": [{"id": part.id}]}}})
    )
    service.apply_changes(diff)

    assert service.get_part(part.id).location == "4A4"
    assert diff.bins[0].changes == ()


def test_move_target_may_be_created_by_the_same_plan(
    service: InventoryService,
) -> None:
    part = service.add_part("4A3", "solder")

    diff = service.plan_changes(
        plan(
            {
                "bins": {
                    "4A3": {"parts": [], "remove": {str(part.id): {"move": "4A9"}}},
                    "4A9": {"create": True, "parts": [{"id": part.id}]},
                }
            }
        )
    )
    service.apply_changes(diff)

    assert service.get_part(part.id).location == "4A9"


def test_move_into_unreviewed_bin_does_not_verify_it(
    service: InventoryService,
) -> None:
    part = service.add_part("4A3", "solder")

    diff = service.plan_changes(
        plan(
            {
                "verify": True,
                "bins": {
                    "4A3": {"parts": [], "remove": {str(part.id): {"move": "1D1"}}}
                },
            }
        )
    )
    service.apply_changes(diff)

    assert verified(service) == {"4A3"}


def test_only_changed_descriptions_lose_embeddings(
    conn: psycopg.Connection, service: InventoryService
) -> None:
    kept = service.add_part("4A3", "washers")
    same = service.add_part("4A3", "nuts")
    changed = service.add_part("4A3", "caps")
    moved = service.add_part("5A6", "regulator")
    renamed_move = service.add_part("5A6", "chip")
    for part in (kept, same, changed, moved, renamed_move):
        set_embedding(conn, part.id)

    diff = service.plan_changes(
        plan(
            {
                "bins": {
                    "4A3": {
                        "parts": [
                            {"id": kept.id},
                            {"id": same.id, "description": "nuts"},
                            {"id": changed.id, "description": "film caps"},
                            {"id": moved.id},
                            {"id": renamed_move.id, "description": "MAX232 driver"},
                        ]
                    }
                }
            }
        )
    )
    assert [change.kind for change in diff.bins[0].changes] == [
        "keep",
        "keep",
        "update",
        "move_in",
        "move_in",
    ]
    service.apply_changes(diff)

    assert {part.id: part.has_embedding for part in service.list_parts("4A3")} == {
        kept.id: True,
        same.id: True,
        changed.id: False,
        moved.id: True,
        renamed_move.id: False,
    }


def test_apply_does_not_commit_so_failures_roll_back(
    conn: psycopg.Connection, service: InventoryService, monkeypatch
) -> None:
    first = service.add_part("4A3", "washers")
    doomed = service.add_part("4A3", "junk")
    conn.commit()
    diff = service.plan_changes(
        plan(
            {
                "verify": True,
                "bins": {
                    "4A3": {
                        "parts": [{"id": first.id, "description": "M3 washers"}],
                        "remove": {str(doomed.id): "delete"},
                    }
                },
            }
        )
    )

    def fail(part_id: int) -> None:
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(service, "delete_part", fail)
    with pytest.raises(RuntimeError):
        service.apply_changes(diff)
    conn.rollback()

    assert service.get_part(first.id).description == "washers"
    assert verified(service) == set()

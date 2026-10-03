import json

import pytest

from partdb.apply import (
    BinDiff,
    Change,
    PartEntry,
    PlanDiff,
    PlanError,
    Removal,
    parse_plan,
    render_diff,
)


def test_parses_complete_bin_plan() -> None:
    plan = parse_plan(
        json.dumps(
            {
                "verify": True,
                "bins": {
                    "4A3": {
                        "parts": [
                            {"id": 72, "description": " film caps "},
                            {"id": 80},
                            {"description": "M3 standoffs"},
                        ],
                        "remove": {"73": "delete", "74": {"move": "1D1"}},
                    },
                    "4A7": {"create": True, "parts": []},
                },
            }
        )
    )

    assert plan.verify is True
    first, second = plan.bins
    assert first.name == "4A3"
    assert first.parts == (
        PartEntry(72, "film caps"),
        PartEntry(80, None),
        PartEntry(None, "M3 standoffs"),
    )
    assert first.removals == (Removal(73, None), Removal(74, "1D1"))
    assert first.create is False
    assert (second.name, second.create, second.parts) == ("4A7", True, ())


def test_verify_defaults_to_false() -> None:
    plan = parse_plan(json.dumps({"bins": {"4A3": {"parts": []}}}))
    assert plan.verify is False


@pytest.mark.parametrize(
    ("data", "problem"),
    [
        ([], "plan must be a JSON object"),
        ({}, "bins must be a non-empty object"),
        ({"bins": {}}, "bins must be a non-empty object"),
        (
            {"bins": {"4A3": {"parts": []}}, "verfy": True},
            "plan: unknown key 'verfy'",
        ),
        (
            {"bins": {"4A3": {"parts": []}}, "verify": "yes"},
            "verify must be true or false",
        ),
        ({"bins": {"4A3": []}}, "4A3: bin entry must be an object"),
        ({"bins": {"4A3": {}}}, "4A3: parts must be a list"),
        (
            {"bins": {"4A3": {"parts": [], "remvoe": {}}}},
            "4A3: unknown key 'remvoe'",
        ),
        (
            {"bins": {"4A3": {"parts": [], "create": 1}}},
            "4A3: create must be true or false",
        ),
        (
            {"bins": {"4A3": {"parts": [{"id": "72"}]}}},
            "4A3 part 1: id must be a positive integer",
        ),
        (
            {"bins": {"4A3": {"parts": [{"id": True}]}}},
            "4A3 part 1: id must be a positive integer",
        ),
        (
            {"bins": {"4A3": {"parts": [{"description": "  "}]}}},
            "4A3 part 1: description cannot be blank",
        ),
        (
            {"bins": {"4A3": {"parts": [{}]}}},
            "4A3 part 1: needs an id, a description, or both",
        ),
        (
            {"bins": {"4A3": {"parts": [{"id": 1, "desc": "x"}]}}},
            "4A3 part 1: unknown key 'desc'",
        ),
        (
            {"bins": {"4A3": {"parts": [], "remove": {"x": "delete"}}}},
            "4A3 remove x: key must be a part id",
        ),
        (
            {"bins": {"4A3": {"parts": [], "remove": {"7": "trash"}}}},
            '4A3 remove 7: must be "delete" or {"move": "<location>"}',
        ),
        (
            {"bins": {"4A3": {"parts": [], "remove": {"7": {"move": "4a3"}}}}},
            "4A3 remove 7: cannot move a part to the bin it is removed from",
        ),
        (
            {"bins": {"4A3": {"parts": []}, "4a3": {"parts": []}}},
            "bins 4A3 and 4a3 name the same location",
        ),
        (
            {"bins": {"4A3": {"parts": [{"id": 5}]}, "4A4": {"parts": [{"id": 5}]}}},
            "part 5 is listed in both 4A3 and 4A4",
        ),
        (
            {"bins": {"4A3": {"parts": [{"id": 5}], "remove": {"5": "delete"}}}},
            "part 5 is listed in 4A3 and deleted by 4A3",
        ),
        (
            {
                "bins": {
                    "4A3": {"parts": [], "remove": {"5": "delete"}},
                    "4A4": {"parts": [], "remove": {"5": "delete"}},
                }
            },
            "part 5 is removed by both 4A3 and 4A4",
        ),
        (
            {
                "bins": {
                    "4A3": {"parts": [], "remove": {"5": {"move": "4A5"}}},
                    "4A4": {"parts": [{"id": 5}]},
                }
            },
            "part 5 is moved to 4A5 by 4A3 but listed in 4A4",
        ),
        (
            {
                "bins": {
                    "4A3": {"parts": [], "remove": {"5": {"move": "4A4"}}},
                    "4A4": {"parts": []},
                }
            },
            "part 5 is moved to 4A4 by 4A3 but 4A4 does not list it",
        ),
    ],
)
def test_rejects_invalid_plans(data: object, problem: str) -> None:
    with pytest.raises(PlanError) as excinfo:
        parse_plan(json.dumps(data))
    assert problem in excinfo.value.problems


def test_rejects_malformed_json() -> None:
    with pytest.raises(PlanError, match="malformed JSON"):
        parse_plan("{")


def test_rejects_duplicate_keys() -> None:
    text = '{"bins": {"4A3": {"parts": []}, "4A3": {"parts": [{"id": 1}]}}}'
    with pytest.raises(PlanError) as excinfo:
        parse_plan(text)
    assert "duplicate key '4A3'" in excinfo.value.problems


def test_reports_every_problem_at_once() -> None:
    data = {"verify": "yes", "bins": {"4A3": {"parts": [{}], "create": 1}}}
    with pytest.raises(PlanError) as excinfo:
        parse_plan(json.dumps(data))
    assert len(excinfo.value.problems) == 3
    assert str(excinfo.value).startswith("invalid plan:\n  - ")


def test_preserves_quotes_and_unicode_in_descriptions() -> None:
    description = 'M3 x 8mm "pan head" — 10µF'
    text = json.dumps(
        {"bins": {"4A3": {"parts": [{"description": description}]}}},
        ensure_ascii=False,
    )
    assert parse_plan(text).bins[0].parts[0].description == description


def test_renders_every_change_kind() -> None:
    diff = PlanDiff(
        bins=(
            BinDiff(
                "4A3",
                False,
                (
                    Change("keep", 80, "washers"),
                    Change("update", 72, "film caps", old_description="tantalum caps"),
                    Change("move_in", 211, "regulator", other_location="5A6"),
                    Change(
                        "move_in",
                        212,
                        "MAX232 driver",
                        old_description="chip",
                        other_location="4H5",
                    ),
                    Change("add", 215, "M3 standoffs"),
                    Change("delete", 73, "junk"),
                    Change("move_out", 74, "solder", other_location="1D1"),
                ),
            ),
            BinDiff("4A7", True, ()),
        ),
        verify=True,
    )

    assert render_diff(diff) == [
        "4A3",
        '  = 80 "washers"',
        '  ~ 72 "tantalum caps" -> "film caps"',
        '  < 211 "regulator" <- 5A6',
        '  < 212 "chip" -> "MAX232 driver" <- 4H5',
        '  + 215 "M3 standoffs"',
        '  - 73 "junk"',
        '  > 74 "solder" -> 1D1',
        "  verified",
        "4A7 (created)",
        "  (empty)",
        "  verified",
    ]


def test_unsaved_additions_render_as_new_with_escaped_quotes() -> None:
    diff = PlanDiff(
        bins=(BinDiff("4A3", False, (Change("add", None, 'M3 "pan head"'),)),),
        verify=False,
    )
    assert render_diff(diff) == ["4A3", '  + new "M3 \\"pan head\\""']


def test_renders_unicode_descriptions_verbatim() -> None:
    diff = PlanDiff(
        bins=(BinDiff("4A3", False, (Change("keep", 1, "10µF — X7R"),)),),
        verify=False,
    )
    assert render_diff(diff) == ["4A3", '  = 1 "10µF — X7R"']

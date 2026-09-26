import pytest

from partdb.errors import InvalidLocationRange
from partdb.location_order import inclusive_location_range, natural_location_key


def test_natural_order_matches_physical_labels() -> None:
    names = ["5A10", "PO2", "5A2", "1B1", "PO1", "5A1"]
    assert sorted(names, key=natural_location_key) == [
        "1B1",
        "5A1",
        "5A2",
        "5A10",
        "PO1",
        "PO2",
    ]


def test_range_is_inclusive_and_case_insensitive() -> None:
    names = ["5A1", "5A2", "5A3", "5A8"]
    assert inclusive_location_range(names, "5a1", "5a3") == [
        "5A1",
        "5A2",
        "5A3",
    ]


@pytest.mark.parametrize(
    "names,start,end,message",
    [
        (["5A1"], "5A1", "5A9", "unknown range endpoint"),
        (["5A1", "5A2"], "5A2", "5A1", "range is reversed"),
        (["5A1", "5a1"], "5A1", "5A1", "ambiguous range endpoint"),
    ],
)
def test_invalid_ranges_fail(
    names: list[str], start: str, end: str, message: str
) -> None:
    with pytest.raises(InvalidLocationRange, match=message):
        inclusive_location_range(names, start, end)

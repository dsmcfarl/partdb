from partdb.cli import nearest_empty_label


def test_nearest_empty_label_names_both_sides() -> None:
    assert nearest_empty_label("4F8", "5A4") == "nearest empty: 4F8 ↑ 5A4 ↓"
    assert nearest_empty_label(None, "2B8") == "nearest empty: none ↑ 2B8 ↓"
    assert nearest_empty_label("2B8", None) == "nearest empty: 2B8 ↑ none ↓"

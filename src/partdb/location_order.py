import re

from partdb.errors import InvalidLocationRange


def natural_location_key(name: str) -> tuple[tuple[int, int | str], ...]:
    tokens = re.findall(r"\d+|\D+", name.strip())
    return tuple(
        (0, int(token)) if token.isdigit() else (1, token.upper()) for token in tokens
    ) + ((2, name.upper()),)


def inclusive_location_range(names: list[str], start: str, end: str) -> list[str]:
    by_casefold: dict[str, list[str]] = {}
    for name in names:
        by_casefold.setdefault(name.casefold(), []).append(name)

    def endpoint(value: str) -> str:
        matches = by_casefold.get(value.casefold(), [])
        if not matches:
            raise InvalidLocationRange(f"unknown range endpoint {value}")
        if len(matches) > 1:
            raise InvalidLocationRange(f"ambiguous range endpoint {value}")
        return matches[0]

    start_name = endpoint(start)
    end_name = endpoint(end)
    ordered = sorted(names, key=natural_location_key)
    start_index = ordered.index(start_name)
    end_index = ordered.index(end_name)
    if start_index > end_index:
        raise InvalidLocationRange("range is reversed")
    return ordered[start_index : end_index + 1]

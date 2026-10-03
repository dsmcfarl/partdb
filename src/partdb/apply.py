"""Reviewed bin plans: parse plan JSON, describe changes, and render diffs."""

import json
from dataclasses import dataclass
from typing import Any, Literal

from partdb.errors import PartDBError

ChangeKind = Literal["keep", "update", "add", "move_in", "move_out", "delete"]

PLAN_KEYS = {"bins", "verify"}
BIN_KEYS = {"parts", "remove", "create"}
PART_KEYS = {"id", "description"}
MOVE_KEYS = {"move", "description"}


class PlanError(PartDBError):
    """A plan was rejected. Every problem found is listed."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__(
            "invalid plan:\n" + "\n".join(f"  - {problem}" for problem in problems)
        )


@dataclass(frozen=True)
class PartEntry:
    id: int | None
    description: str | None


@dataclass(frozen=True)
class Removal:
    part_id: int
    move_to: str | None
    description: str | None = None


@dataclass(frozen=True)
class BinPlan:
    name: str
    parts: tuple[PartEntry, ...]
    removals: tuple[Removal, ...]
    create: bool


@dataclass(frozen=True)
class Plan:
    bins: tuple[BinPlan, ...]
    verify: bool


@dataclass(frozen=True)
class Change:
    kind: ChangeKind
    part_id: int | None
    description: str
    old_description: str | None = None
    other_location: str | None = None


@dataclass(frozen=True)
class BinDiff:
    name: str
    created: bool
    changes: tuple[Change, ...]


@dataclass(frozen=True)
class PlanDiff:
    bins: tuple[BinDiff, ...]
    verify: bool


def parse_plan(text: str) -> Plan:
    try:
        data = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise PlanError([f"malformed JSON: {exc}"]) from None
    if not isinstance(data, dict):
        raise PlanError(["plan must be a JSON object"])

    problems: list[str] = []
    _unknown_keys(data, PLAN_KEYS, "plan", problems)
    verify = data.get("verify", False)
    if not isinstance(verify, bool):
        problems.append("verify must be true or false")
        verify = False
    raw_bins = data.get("bins")
    if not isinstance(raw_bins, dict) or not raw_bins:
        problems.append("bins must be a non-empty object")
        raw_bins = {}

    bins: list[BinPlan] = []
    seen: dict[str, str] = {}
    for raw_name, entry in raw_bins.items():
        name = raw_name.strip()
        if not name:
            problems.append("bin names cannot be blank")
            continue
        if name.casefold() in seen:
            problems.append(
                f"bins {seen[name.casefold()]} and {name} name the same location"
            )
            continue
        seen[name.casefold()] = name
        bin_plan = _parse_bin(name, entry, problems)
        if bin_plan is not None:
            bins.append(bin_plan)

    _check_part_claims(bins, problems)
    if problems:
        raise PlanError(problems)
    return Plan(bins=tuple(bins), verify=verify)


def render_diff(diff: PlanDiff) -> list[str]:
    lines: list[str] = []
    for bin_diff in diff.bins:
        lines.append(
            f"{bin_diff.name} (created)" if bin_diff.created else bin_diff.name
        )
        if not bin_diff.changes:
            lines.append("  (empty)")
        lines.extend(f"  {_render_change(change)}" for change in bin_diff.changes)
        if diff.verify:
            lines.append("  verified")
    return lines


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PlanError([f"duplicate key {key!r}"])
        result[key] = value
    return result


def _unknown_keys(
    data: dict[str, Any], allowed: set[str], label: str, problems: list[str]
) -> None:
    problems.extend(
        f"{label}: unknown key {key!r}" for key in data if key not in allowed
    )


def _parse_bin(name: str, entry: Any, problems: list[str]) -> BinPlan | None:
    if not isinstance(entry, dict):
        problems.append(f"{name}: bin entry must be an object")
        return None
    _unknown_keys(entry, BIN_KEYS, name, problems)
    create = entry.get("create", False)
    if not isinstance(create, bool):
        problems.append(f"{name}: create must be true or false")
        create = False
    raw_parts = entry.get("parts")
    if not isinstance(raw_parts, list):
        problems.append(f"{name}: parts must be a list")
        raw_parts = []
    parts = []
    for index, raw_part in enumerate(raw_parts, start=1):
        part = _parse_part(f"{name} part {index}", raw_part, problems)
        if part is not None:
            parts.append(part)
    raw_remove = entry.get("remove", {})
    if not isinstance(raw_remove, dict):
        problems.append(f"{name}: remove must be an object")
        raw_remove = {}
    removals = []
    for key, action in raw_remove.items():
        removal = _parse_removal(name, key, action, problems)
        if removal is not None:
            removals.append(removal)
    return BinPlan(name, tuple(parts), tuple(removals), create)


def _parse_part(label: str, raw: Any, problems: list[str]) -> PartEntry | None:
    if not isinstance(raw, dict):
        problems.append(f"{label}: must be an object")
        return None
    _unknown_keys(raw, PART_KEYS, label, problems)
    part_id = raw.get("id")
    if part_id is not None and not _is_part_id(part_id):
        problems.append(f"{label}: id must be a positive integer")
        return None
    description = raw.get("description")
    if description is not None:
        if not isinstance(description, str) or not description.strip():
            problems.append(f"{label}: description cannot be blank")
            return None
        description = description.strip()
    if part_id is None and description is None:
        problems.append(f"{label}: needs an id, a description, or both")
        return None
    return PartEntry(part_id, description)


def _parse_removal(
    name: str, key: str, action: Any, problems: list[str]
) -> Removal | None:
    label = f"{name} remove {key}"
    if not (key.isascii() and key.isdigit() and int(key) > 0):
        problems.append(f"{label}: key must be a part id")
        return None
    part_id = int(key)
    if action == "delete":
        return Removal(part_id, None)
    if (
        isinstance(action, dict)
        and isinstance(action.get("move"), str)
        and action["move"].strip()
    ):
        unknown = [key for key in action if key not in MOVE_KEYS]
        if unknown:
            problems.extend(f"{label}: unknown key {key!r}" for key in unknown)
            return None
        target = action["move"].strip()
        if target.casefold() == name.casefold():
            problems.append(
                f"{label}: cannot move a part to the bin it is removed from"
            )
            return None
        description = action.get("description")
        if description is not None:
            if not isinstance(description, str) or not description.strip():
                problems.append(f"{label}: description cannot be blank")
                return None
            description = description.strip()
        return Removal(part_id, target, description)
    problems.append(f'{label}: must be "delete" or {{"move": "<location>"}}')
    return None


def _is_part_id(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _check_part_claims(bins: list[BinPlan], problems: list[str]) -> None:
    plan_names = {bin_plan.name.casefold(): bin_plan.name for bin_plan in bins}
    listed: dict[int, str] = {}
    for bin_plan in bins:
        for part in bin_plan.parts:
            if part.id is None:
                continue
            if part.id in listed:
                problems.append(
                    f"part {part.id} is listed in both {listed[part.id]} "
                    f"and {bin_plan.name}"
                )
            else:
                listed[part.id] = bin_plan.name
    removed: dict[int, str] = {}
    for bin_plan in bins:
        for removal in bin_plan.removals:
            part_id = removal.part_id
            if part_id in removed:
                problems.append(
                    f"part {part_id} is removed by both {removed[part_id]} "
                    f"and {bin_plan.name}"
                )
                continue
            removed[part_id] = bin_plan.name
            destination = listed.get(part_id)
            if removal.move_to is None:
                if destination is not None:
                    problems.append(
                        f"part {part_id} is listed in {destination} "
                        f"and deleted by {bin_plan.name}"
                    )
                continue
            if destination is not None:
                if destination.casefold() != removal.move_to.casefold():
                    problems.append(
                        f"part {part_id} is moved to {removal.move_to} by "
                        f"{bin_plan.name} but listed in {destination}"
                    )
                elif removal.description is not None:
                    problems.append(
                        f"part {part_id} is moved to {destination} by "
                        f"{bin_plan.name} with a description; "
                        f"set it in {destination}'s listing instead"
                    )
            elif removal.move_to.casefold() in plan_names:
                target = plan_names[removal.move_to.casefold()]
                problems.append(
                    f"part {part_id} is moved to {target} by {bin_plan.name} "
                    f"but {target} does not list it"
                )


def _render_change(change: Change) -> str:
    ident = "new" if change.part_id is None else str(change.part_id)
    if change.kind == "move_out":
        if change.old_description is None:
            return f"> {ident} {_quote(change.description)} -> {change.other_location}"
        return (
            f"> {ident} {_quote(change.old_description)} -> "
            f"{change.other_location} as {_quote(change.description)}"
        )
    text = _quote(change.description)
    if change.old_description is not None:
        text = f"{_quote(change.old_description)} -> {text}"
    if change.kind == "keep":
        return f"= {ident} {text}"
    if change.kind == "update":
        return f"~ {ident} {text}"
    if change.kind == "add":
        return f"+ {ident} {text}"
    if change.kind == "delete":
        return f"- {ident} {text}"
    return f"< {ident} {text} <- {change.other_location}"


def _quote(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)

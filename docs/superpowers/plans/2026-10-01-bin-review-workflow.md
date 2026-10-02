# PartDB Bin-Review Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an atomic `partdb apply` command for reviewed bin plans, small verification and search refinements, tested photo-filing and photo-watcher scripts, and a repository `bin-review` skill that codifies the attended photo-driven review loop.

**Architecture:** A new pure module `src/partdb/apply.py` parses and structurally validates plan JSON and renders diffs. `InventoryService` gains `plan_changes` (validate against current data, compute a diff) and `apply_changes` (execute a diff inside the caller's transaction), reusing existing CRUD and verification methods. The skill lives in `.claude/skills/bin-review/` with two scripts: a PEP 723 photo filer using Pillow and a portable Bash Downloads watcher.

**Tech Stack:** Python 3.11+, Click, psycopg 3, PostgreSQL 17 + pgvector (Docker Compose), pytest, Ruff, uv, Pillow (dev and script-only), Bash.

**Spec:** `docs/superpowers/specs/2026-10-01-bin-review-workflow-design.md`

## Global Constraints

- Execute in an isolated Git worktree under `.worktrees/` (already gitignored) on branch `feature/bin-review-workflow`, created with `superpowers:using-git-worktrees`.
- Python `>=3.11`; keep psycopg and direct SQL; no ORM or framework.
- partdb gains no runtime dependency. Pillow goes only in the `dev` dependency group and in the photo script's PEP 723 header.
- Start the database with `docker compose up -d --wait` before integration tests. Tests create and drop disposable databases on `127.0.0.1:5435`; they never touch the real `partdb` database.
- Never run a modifying `partdb` command against the real database during implementation. The acceptance smoke test uses `--dry-run` and read-only commands only.
- Never commit inventory data, photos, plans, notes, research queues, or credentials. Documentation and skill examples use invented inventory.
- Never read `PARTDB_OPENAI_API_KEY` or run `PARTDB_OPENAI_API_KEY_CMD`.
- Run `uv run ruff format .` and `uv run ruff check .` before every commit.
- End every commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- The photo archive root is `~/Documents/Archive/Interests/Workshop/PartDB/photos/`, overridable by `PARTDB_PHOTO_ROOT`. Manifest header, verbatim: `file,original_name,taken_at,bin,part_ids,reviewed_on,note`. Manifest uses LF line endings.
- Photo copies are named `<LOCATION>/<YYYY-MM-DD>_<original filename>`; `taken_at` is naive local ISO 8601 such as `2026-09-28T18:05:12`; `part_ids` is semicolon-separated.

## Review Focus

- Duplicated JSON keys in a plan (an agent emits the same bin twice): the plan is rejected instead of the last copy silently winning. Pinned in Task 1.
- Plan bin names typed in a different case from the database (`4a3` for `4A3`), including with `create: true`: they resolve to the canonical existing location and nothing is created. Pinned in Task 2.
- A part moved between two bins in the same multi-bin plan without a `remove` entry in its source bin: accepted, the part moves, and the source bin does not report it unaccounted. Pinned in Task 2.
- Descriptions containing quotes, em dashes, or micro signs: parsed intact and rendered unambiguously in the diff. Pinned in Task 1.
- A manifest whose last row lacks a trailing newline, or with unexpected columns: appended rows stay separate and intact, and a bad header fails before any copy is made. Pinned in Task 5.

## Planned File Structure

- Create `src/partdb/apply.py`: plan and diff data types, `parse_plan`, `render_diff`, `PlanError`.
- Modify `src/partdb/inventory.py`: `plan_changes`, `apply_changes`, `_entry_change`, `_parts_by_id`.
- Modify `src/partdb/cli.py`: `apply` command, `verify mark --expect-empty`, `verify status --all` and summary default, `nearest_empty_label`.
- Create `.claude/skills/bin-review/SKILL.md`: the attended review runbook.
- Create `.claude/skills/bin-review/scripts/file_photo.py`: photo filer.
- Create `.claude/skills/bin-review/scripts/watch_downloads.sh`: new-photo watcher.
- Modify `README.md`, `pyproject.toml`, `uv.lock`.
- Tests: `tests/unit/test_apply_plan.py`, `tests/unit/test_cli_format.py`, `tests/unit/test_file_photo.py`, `tests/unit/test_watch_downloads.py`, `tests/integration/test_apply_service.py`, `tests/integration/test_cli_apply.py`; modify `tests/integration/test_cli_verification.py`, `tests/integration/test_search_and_csv.py`, `tests/unit/test_documented_commands.py`.

---

### Task 1: Plan Parsing and Diff Rendering

**Files:**
- Create: `src/partdb/apply.py`
- Test: `tests/unit/test_apply_plan.py`

**Interfaces:**
- Consumes: `partdb.errors.PartDBError`.
- Produces:
  - `class PlanError(PartDBError)` with attribute `problems: list[str]`; `str(error)` is `"invalid plan:\n  - <problem>\n  - <problem>"`.
  - Frozen dataclasses: `PartEntry(id: int | None, description: str | None)`, `Removal(part_id: int, move_to: str | None)` (`None` means delete), `BinPlan(name: str, parts: tuple[PartEntry, ...], removals: tuple[Removal, ...], create: bool)`, `Plan(bins: tuple[BinPlan, ...], verify: bool)`.
  - `ChangeKind = Literal["keep", "update", "add", "move_in", "move_out", "delete"]`.
  - Frozen dataclasses: `Change(kind: ChangeKind, part_id: int | None, description: str, old_description: str | None = None, other_location: str | None = None)`, `BinDiff(name: str, created: bool, changes: tuple[Change, ...])`, `PlanDiff(bins: tuple[BinDiff, ...], verify: bool)`.
  - `parse_plan(text: str) -> Plan`: raises `PlanError`.
  - `render_diff(diff: PlanDiff) -> list[str]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_apply_plan.py`:

```python
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
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `uv run pytest tests/unit/test_apply_plan.py -v`
Expected: collection error, `ModuleNotFoundError: No module named 'partdb.apply'`.

- [ ] **Step 3: Implement `src/partdb/apply.py`**

```python
"""Reviewed bin plans: parse plan JSON, describe changes, and render diffs."""

import json
from dataclasses import dataclass
from typing import Any, Literal

from partdb.errors import PartDBError

ChangeKind = Literal["keep", "update", "add", "move_in", "move_out", "delete"]

PLAN_KEYS = {"bins", "verify"}
BIN_KEYS = {"parts", "remove", "create"}
PART_KEYS = {"id", "description"}


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
        lines.append(f"{bin_diff.name} (created)" if bin_diff.created else bin_diff.name)
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
        and set(action) == {"move"}
        and isinstance(action["move"], str)
        and action["move"].strip()
    ):
        target = action["move"].strip()
        if target.casefold() == name.casefold():
            problems.append(
                f"{label}: cannot move a part to the bin it is removed from"
            )
            return None
        return Removal(part_id, target)
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
            elif removal.move_to.casefold() in plan_names:
                target = plan_names[removal.move_to.casefold()]
                problems.append(
                    f"part {part_id} is moved to {target} by {bin_plan.name} "
                    f"but {target} does not list it"
                )


def _render_change(change: Change) -> str:
    ident = "new" if change.part_id is None else str(change.part_id)
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
    if change.kind == "move_in":
        return f"< {ident} {text} <- {change.other_location}"
    return f"> {ident} {text} -> {change.other_location}"


def _quote(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `uv run pytest tests/unit/test_apply_plan.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Format, lint, and commit**

```bash
uv run ruff format . && uv run ruff check .
git add src/partdb/apply.py tests/unit/test_apply_plan.py
git commit -m "feat: parse and render reviewed bin plans

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Validate and Apply Plans in the Inventory Service

**Files:**
- Modify: `src/partdb/inventory.py` (imports at lines 1-17; add methods after `verification_status`, around line 177; add private helpers before `_canonical_location_names`, around line 318)
- Test: `tests/integration/test_apply_service.py`

**Interfaces:**
- Consumes: from Task 1, `Plan`, `PartEntry`, `Change`, `BinDiff`, `PlanDiff`, `PlanError`, `parse_plan`. Existing `InventoryService.list_locations`, `list_parts`, `add_location`, `add_part`, `update_part`, `move_part`, `delete_part`, `mark_verified`, `_part`.
- Produces:
  - `InventoryService.plan_changes(plan: Plan) -> PlanDiff`: raises `PlanError` listing every data problem; resolved bin names are canonical.
  - `InventoryService.apply_changes(diff: PlanDiff) -> PlanDiff`: executes within the caller's transaction (never commits); returned diff has `part_id` set on `add` changes.

- [ ] **Step 1: Write the failing integration tests**

Create `tests/integration/test_apply_service.py`:

```python
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
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `docker compose up -d --wait && uv run pytest tests/integration/test_apply_service.py -v`
Expected: FAIL with `AttributeError: 'InventoryService' object has no attribute 'plan_changes'`.

- [ ] **Step 3: Add imports to `src/partdb/inventory.py`**

Add `from dataclasses import replace` with the standard-library imports, and after `from partdb.embeddings import EmbeddingProvider` add:

```python
from partdb.apply import BinDiff, Change, PartEntry, Plan, PlanDiff, PlanError
```

- [ ] **Step 4: Add the public methods after `verification_status`**

```python
    def plan_changes(self, plan: Plan) -> PlanDiff:
        """Validate a reviewed plan against current data and describe its changes."""
        problems: list[str] = []
        by_casefold: dict[str, list[str]] = {}
        for location in self.list_locations():
            by_casefold.setdefault(location.name.casefold(), []).append(location.name)

        def existing(name: str) -> str | None:
            matches = by_casefold.get(name.casefold(), [])
            if name in matches:
                return name
            if len(matches) > 1:
                raise PlanError([f"location {name} is ambiguous"])
            return matches[0] if matches else None

        canonical: dict[str, str] = {}
        created: dict[str, str] = {}
        for bin_plan in plan.bins:
            name = existing(bin_plan.name)
            if name is None:
                if not bin_plan.create:
                    problems.append(
                        f"{bin_plan.name}: location not found "
                        "(set create to add it)"
                    )
                    continue
                name = bin_plan.name
                created[name.casefold()] = name
            canonical[bin_plan.name] = name

        listed_anywhere = {
            entry.id
            for bin_plan in plan.bins
            for entry in bin_plan.parts
            if entry.id is not None
        }
        referenced = listed_anywhere | {
            removal.part_id
            for bin_plan in plan.bins
            for removal in bin_plan.removals
        }
        current = self._parts_by_id(referenced)
        problems.extend(
            f"part {part_id} not found"
            for part_id in sorted(referenced - current.keys())
        )

        bins: list[BinDiff] = []
        for bin_plan in plan.bins:
            name = canonical.get(bin_plan.name)
            if name is None:
                continue
            changes = [
                change
                for entry in bin_plan.parts
                if (change := self._entry_change(name, entry, current)) is not None
            ]
            removed: set[int] = set()
            for removal in bin_plan.removals:
                part = current.get(removal.part_id)
                if part is None:
                    continue
                if part.location != name:
                    problems.append(f"{name}: part {part.id} is not in {name}")
                    continue
                removed.add(part.id)
                if removal.move_to is None:
                    changes.append(Change("delete", part.id, part.description))
                    continue
                target = existing(removal.move_to) or created.get(
                    removal.move_to.casefold()
                )
                if target is None:
                    problems.append(f"{name}: move target {removal.move_to} not found")
                    continue
                changes.append(
                    Change(
                        "move_out", part.id, part.description, other_location=target
                    )
                )
            is_created = name.casefold() in created
            if not is_created:
                for part in self.list_parts(name):
                    if part.id not in removed and part.id not in listed_anywhere:
                        problems.append(
                            f'{name}: part {part.id} "{part.description}" '
                            "is not accounted for"
                        )
            bins.append(BinDiff(name, is_created, tuple(changes)))

        if problems:
            raise PlanError(problems)
        return PlanDiff(bins=tuple(bins), verify=plan.verify)

    def apply_changes(self, diff: PlanDiff) -> PlanDiff:
        """Apply a computed diff in the caller's transaction; return it with new IDs."""
        for bin_diff in diff.bins:
            if bin_diff.created:
                self.add_location(bin_diff.name)
        applied: list[BinDiff] = []
        for bin_diff in diff.bins:
            changes: list[Change] = []
            for change in bin_diff.changes:
                if change.kind == "add":
                    part = self.add_part(bin_diff.name, change.description)
                    change = replace(change, part_id=part.id)
                elif change.kind == "update":
                    self.update_part(change.part_id, change.description)
                elif change.kind == "move_in":
                    self.move_part(change.part_id, bin_diff.name)
                    if change.old_description is not None:
                        self.update_part(change.part_id, change.description)
                elif change.kind == "move_out":
                    self.move_part(change.part_id, change.other_location)
                elif change.kind == "delete":
                    self.delete_part(change.part_id)
                changes.append(change)
            applied.append(replace(bin_diff, changes=tuple(changes)))
        if diff.verify:
            self.mark_verified([bin_diff.name for bin_diff in diff.bins])
        return replace(diff, bins=tuple(applied))
```

- [ ] **Step 5: Add the private helpers before `_canonical_location_names`**

```python
    def _parts_by_id(self, ids: set[int]) -> dict[int, Part]:
        if not ids:
            return {}
        rows = self.conn.execute(
            """SELECT id, location, description, embedding IS NOT NULL
            FROM parts WHERE id = ANY(%s)""",
            (sorted(ids),),
        )
        return {row[0]: self._part(row) for row in rows}

    @staticmethod
    def _entry_change(
        name: str, entry: PartEntry, current: dict[int, Part]
    ) -> Change | None:
        if entry.id is None:
            return Change("add", None, entry.description or "")
        part = current.get(entry.id)
        if part is None:
            return None
        renamed = entry.description is not None and (
            entry.description != part.description
        )
        if part.location == name:
            if renamed:
                return Change(
                    "update",
                    part.id,
                    entry.description or "",
                    old_description=part.description,
                )
            return Change("keep", part.id, part.description)
        return Change(
            "move_in",
            part.id,
            (entry.description or "") if renamed else part.description,
            old_description=part.description if renamed else None,
            other_location=part.location,
        )
```

- [ ] **Step 6: Run the tests and verify they pass**

Run: `uv run pytest tests/integration/test_apply_service.py tests/unit/test_apply_plan.py -v`
Expected: all tests PASS.

- [ ] **Step 7: Format, lint, run the full suite, and commit**

```bash
uv run ruff format . && uv run ruff check . && uv run pytest
git add src/partdb/inventory.py tests/integration/test_apply_service.py
git commit -m "feat: validate and apply reviewed bin plans atomically

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The `partdb apply` Command

**Files:**
- Modify: `src/partdb/cli.py` (imports at lines 1-14; add the command after `show_inventory`, around line 141)
- Test: `tests/integration/test_cli_apply.py`

**Interfaces:**
- Consumes: Task 1 `parse_plan`, `render_diff`; Task 2 `InventoryService.plan_changes`, `apply_changes`; existing `inventory_service()` context manager, which converts `PartDBError` to `click.ClickException` and commits on success or rolls back on any exception.
- Produces: CLI `partdb apply PLAN [--dry-run] [--yes]`, where `PLAN` is a file path or `-` for stdin. Prints the applied diff (with real IDs) after commit. Prompts `Apply these changes?` unless `--yes`. Dry run prints the diff then `dry run: no changes made`.

- [ ] **Step 1: Write the failing CLI tests**

Create `tests/integration/test_cli_apply.py`:

```python
import json
from pathlib import Path

import psycopg
import pytest
from click.testing import CliRunner

from partdb.cli import cli
from partdb.errors import PartNotFound
from partdb.inventory import InventoryService

pytestmark = pytest.mark.integration


@pytest.fixture
def seeded(database_dsn: str, conn: psycopg.Connection, monkeypatch) -> dict[str, int]:
    service = InventoryService(conn)
    for name in ("4A3", "1D1"):
        service.add_location(name)
    washers = service.add_part("4A3", "washers")
    junk = service.add_part("4A3", "junk")
    conn.commit()
    monkeypatch.setenv("PARTDB_DSN", database_dsn)
    return {"washers": washers.id, "junk": junk.id}


def plan_json(ids: dict[str, int]) -> str:
    return json.dumps(
        {
            "verify": True,
            "bins": {
                "4A3": {
                    "parts": [
                        {"id": ids["washers"], "description": "M3 washers"},
                        {"description": "M3 standoffs"},
                    ],
                    "remove": {str(ids["junk"]): "delete"},
                }
            },
        }
    )


def descriptions(conn: psycopg.Connection) -> list[str]:
    return sorted(row[0] for row in conn.execute("SELECT description FROM parts"))


def verified_count(conn: psycopg.Connection) -> int:
    return conn.execute(
        "SELECT count(*) FROM locations WHERE verified_at IS NOT NULL"
    ).fetchone()[0]


def write_plan(tmp_path: Path, ids: dict[str, int]) -> Path:
    path = tmp_path / "plan.json"
    path.write_text(plan_json(ids), encoding="utf-8")
    return path


def test_apply_from_stdin_prints_assigned_ids(
    seeded: dict[str, int], conn: psycopg.Connection
) -> None:
    result = CliRunner().invoke(cli, ["apply", "-", "--yes"], input=plan_json(seeded))

    assert result.exit_code == 0, result.output
    new_id = conn.execute(
        "SELECT id FROM parts WHERE description = 'M3 standoffs'"
    ).fetchone()[0]
    assert f'  + {new_id} "M3 standoffs"' in result.output
    assert f'  ~ {seeded["washers"]} "washers" -> "M3 washers"' in result.output
    assert f'  - {seeded["junk"]} "junk"' in result.output
    assert "  verified" in result.output
    assert descriptions(conn) == ["M3 standoffs", "M3 washers"]
    assert verified_count(conn) == 1


def test_apply_reads_a_plan_file(
    seeded: dict[str, int], conn: psycopg.Connection, tmp_path: Path
) -> None:
    path = write_plan(tmp_path, seeded)

    result = CliRunner().invoke(cli, ["apply", str(path), "--yes"])

    assert result.exit_code == 0, result.output
    assert descriptions(conn) == ["M3 standoffs", "M3 washers"]


def test_dry_run_shows_changes_and_writes_nothing(
    seeded: dict[str, int], conn: psycopg.Connection
) -> None:
    result = CliRunner().invoke(
        cli, ["apply", "-", "--dry-run"], input=plan_json(seeded)
    )

    assert result.exit_code == 0, result.output
    assert '  + new "M3 standoffs"' in result.output
    assert result.output.rstrip().endswith("dry run: no changes made")
    assert descriptions(conn) == ["junk", "washers"]
    assert verified_count(conn) == 0


def test_declined_confirmation_writes_nothing(
    seeded: dict[str, int], conn: psycopg.Connection, tmp_path: Path
) -> None:
    path = write_plan(tmp_path, seeded)

    result = CliRunner().invoke(cli, ["apply", str(path)], input="n\n")

    assert result.exit_code != 0
    assert "Apply these changes?" in result.output
    assert descriptions(conn) == ["junk", "washers"]
    assert verified_count(conn) == 0


def test_accepted_confirmation_applies(
    seeded: dict[str, int], conn: psycopg.Connection, tmp_path: Path
) -> None:
    path = write_plan(tmp_path, seeded)

    result = CliRunner().invoke(cli, ["apply", str(path)], input="y\n")

    assert result.exit_code == 0, result.output
    assert descriptions(conn) == ["M3 standoffs", "M3 washers"]


def test_invalid_plan_lists_problems_and_writes_nothing(
    seeded: dict[str, int], conn: psycopg.Connection
) -> None:
    bad = json.dumps({"bins": {"4A3": {"parts": [{"id": seeded["washers"]}]}}})

    result = CliRunner().invoke(cli, ["apply", "-", "--yes"], input=bad)

    assert result.exit_code != 0
    assert "invalid plan:" in result.output
    assert f'4A3: part {seeded["junk"]} "junk" is not accounted for' in result.output
    assert "Traceback" not in result.output
    assert descriptions(conn) == ["junk", "washers"]


def test_database_failure_rolls_back_whole_plan(
    seeded: dict[str, int], conn: psycopg.Connection, monkeypatch
) -> None:
    def fail(self: InventoryService, part_id: int) -> None:
        raise PartNotFound("simulated failure")

    monkeypatch.setattr(InventoryService, "delete_part", fail)

    result = CliRunner().invoke(cli, ["apply", "-", "--yes"], input=plan_json(seeded))

    assert result.exit_code != 0
    assert "simulated failure" in result.output
    assert descriptions(conn) == ["junk", "washers"]
    assert verified_count(conn) == 0
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `uv run pytest tests/integration/test_cli_apply.py -v`
Expected: FAIL; output contains `No such command 'apply'`.

- [ ] **Step 3: Add the command to `src/partdb/cli.py`**

Add the import after `from partdb.audit import ...`:

```python
from partdb.apply import parse_plan, render_diff
```

Add after `show_inventory`:

```python
@cli.command("apply")
@click.argument("plan_file", type=click.File("r", encoding="utf-8"))
@click.option("--dry-run", is_flag=True, help="Show the changes without applying")
@click.option("--yes", is_flag=True, help="Skip confirmation")
def apply_plan(plan_file, dry_run: bool, yes: bool) -> None:
    """Apply a reviewed bin plan (JSON file, or - for stdin) atomically."""
    text = plan_file.read()
    with inventory_service() as service:
        diff = service.plan_changes(parse_plan(text))
        if dry_run:
            for line in render_diff(diff):
                click.echo(line)
            click.echo("dry run: no changes made")
            return
        if not yes:
            for line in render_diff(diff):
                click.echo(line)
            click.confirm("Apply these changes?", abort=True)
        applied = service.apply_changes(diff)
    for line in render_diff(applied):
        click.echo(line)
```

The applied diff prints after the `with` block exits, so it appears only after the transaction commits.

- [ ] **Step 4: Run the tests and verify they pass**

Run: `uv run pytest tests/integration/test_cli_apply.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Format, lint, run the full suite, and commit**

```bash
uv run ruff format . && uv run ruff check . && uv run pytest
git add src/partdb/cli.py tests/integration/test_cli_apply.py
git commit -m "feat: add partdb apply for reviewed bin plans

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Declared-Empty Verification, Status Summary, and Search Labels

**Files:**
- Modify: `src/partdb/cli.py` (`mark_verified` around lines 148-172, `verification_status` around lines 187-201, `search` around lines 204-222)
- Modify: `tests/integration/test_cli_verification.py`, `tests/integration/test_search_and_csv.py:163-179`
- Test: `tests/unit/test_cli_format.py`

**Interfaces:**
- Consumes: existing `InventoryService.inventory_range`, `inventory_locations`, `verification_status`, `display_inventory`.
- Produces:
  - `nearest_empty_label(previous: str | None, following: str | None) -> str` in `partdb.cli`, returning e.g. `"nearest empty: 4F8 ↑ 5A4 ↓"` with `none` for a missing side.
  - `partdb verify mark ... --expect-empty`: fails with `locations are not empty:` followed by `  <location>: <description> (id=<id>)` lines, marking nothing.
  - `partdb verify status`: summary line only; `--unverified` lists unverified; `--all` lists every location; both flags together fail.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_cli_format.py`:

```python
from partdb.cli import nearest_empty_label


def test_nearest_empty_label_names_both_sides() -> None:
    assert nearest_empty_label("4F8", "5A4") == "nearest empty: 4F8 ↑ 5A4 ↓"
    assert nearest_empty_label(None, "2B8") == "nearest empty: none ↑ 2B8 ↓"
    assert nearest_empty_label("2B8", None) == "nearest empty: 2B8 ↑ none ↓"
```

Append to `tests/integration/test_cli_verification.py` (its `runner` fixture creates `5A1` with "washer", empty `5A2`, `5A3` with "resistor", and empty `5A8`):

```python
def test_expect_empty_marks_empty_bins(
    runner: CliRunner, conn: psycopg.Connection
) -> None:
    result = runner.invoke(
        cli, ["verify", "mark", "5A2", "5A8", "--expect-empty", "--yes"]
    )
    assert result.exit_code == 0, result.output
    assert verified_count(conn) == 2


def test_expect_empty_rejects_occupied_bins(
    runner: CliRunner, conn: psycopg.Connection
) -> None:
    result = runner.invoke(
        cli,
        [
            "verify",
            "mark",
            "--from",
            "5A1",
            "--through",
            "5A3",
            "--expect-empty",
            "--yes",
        ],
    )
    assert result.exit_code != 0
    assert "locations are not empty:" in result.output
    assert "  5A1: washer (id=" in result.output
    assert "  5A3: resistor (id=" in result.output
    assert verified_count(conn) == 0


def test_status_defaults_to_summary(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["verify", "status"])
    assert result.exit_code == 0
    assert result.output == "verified 0/4; unverified 4\n"


def test_status_all_lists_every_location(runner: CliRunner) -> None:
    assert runner.invoke(cli, ["verify", "mark", "5A1", "--yes"]).exit_code == 0

    result = runner.invoke(cli, ["verify", "status", "--all"])

    lines = result.output.splitlines()
    assert result.exit_code == 0
    assert lines[0] == "verified 1/4; unverified 3"
    assert lines[1].startswith("5A1: 20")
    assert lines[2:] == ["5A2: unverified", "5A3: unverified", "5A8: unverified"]


def test_status_rejects_conflicting_flags(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["verify", "status", "--all", "--unverified"])
    assert result.exit_code != 0
    assert "--unverified and --all cannot be combined" in result.output
```

In `tests/integration/test_search_and_csv.py`, inside `test_search_cli_shows_which_side_each_empty_location_is_on`, replace:

```python
    assert "empty=5A2,5A4)" in result.output
```

with:

```python
    assert "nearest empty: 5A2 ↑ 5A4 ↓)" in result.output
```

and replace:

```python
    assert "empty=None,5A2)" in result.output
```

with:

```python
    assert "nearest empty: none ↑ 5A2 ↓)" in result.output
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `uv run pytest tests/unit/test_cli_format.py tests/integration/test_cli_verification.py tests/integration/test_search_and_csv.py -v`
Expected: FAIL: `ImportError: cannot import name 'nearest_empty_label'`; with that file excluded, the new verification tests and the search label test fail.

- [ ] **Step 3: Implement `--expect-empty`**

Replace `mark_verified` in `src/partdb/cli.py` with:

```python
@verify.command("mark")
@click.argument("names", nargs=-1)
@click.option("--from", "start", help="First location")
@click.option("--through", "end", help="Last location")
@click.option(
    "--expect-empty", is_flag=True, help="Fail if any location has recorded parts"
)
@click.option("--yes", is_flag=True, help="Skip confirmation")
def mark_verified(
    names: tuple[str, ...],
    start: str | None,
    end: str | None,
    expect_empty: bool,
    yes: bool,
) -> None:
    """Mark explicit locations or an inclusive range verified."""
    if names and (start or end):
        raise click.ClickException("cannot combine names with --from/--through")
    if (start is None) != (end is None):
        raise click.ClickException("both --from and --through are required")
    if not names and start is None:
        raise click.ClickException("supply locations or --from/--through")
    with inventory_service() as service:
        if start is not None and end is not None:
            items = service.inventory_range(start, end)
        else:
            items = service.inventory_locations(names)
        if expect_empty:
            occupied = [
                f"  {item.name}: {part.description} (id={part.id})"
                for item in items
                for part in item.parts
            ]
            if occupied:
                raise click.ClickException(
                    "locations are not empty:\n" + "\n".join(occupied)
                )
        display_inventory(items)
        if not yes:
            click.confirm("Proceed?", abort=True)
        count = service.mark_verified([item.name for item in items])
    click.echo(f"marked {count} locations verified")
```

- [ ] **Step 4: Implement the status summary default**

Replace `verification_status` in `src/partdb/cli.py` with:

```python
@verify.command("status")
@click.option("--unverified", is_flag=True, help="List only unverified locations")
@click.option("--all", "show_all", is_flag=True, help="List every location")
def verification_status(unverified: bool, show_all: bool) -> None:
    """Show physical verification progress."""
    if unverified and show_all:
        raise click.ClickException("--unverified and --all cannot be combined")
    with inventory_service() as service:
        all_locations = service.verification_status()
        verified = sum(item.verified_at is not None for item in all_locations)
        click.echo(
            f"verified {verified}/{len(all_locations)}; "
            f"unverified {len(all_locations) - verified}"
        )
        if not (unverified or show_all):
            return
        items = service.verification_status(unverified_only=unverified)
        for item in items:
            status = item.verified_at.isoformat() if item.verified_at else "unverified"
            click.echo(f"{item.name}: {status}")
```

- [ ] **Step 5: Implement the search label**

Add above the `search` command:

```python
def nearest_empty_label(previous: str | None, following: str | None) -> str:
    return f"nearest empty: {previous or 'none'} ↑ {following or 'none'} ↓"
```

In `search`, replace:

```python
            details.append(f"empty={result.previous_empty},{result.next_empty}")
```

with:

```python
            details.append(
                nearest_empty_label(result.previous_empty, result.next_empty)
            )
```

- [ ] **Step 6: Run the tests and verify they pass**

Run: `uv run pytest tests/unit/test_cli_format.py tests/integration/test_cli_verification.py tests/integration/test_search_and_csv.py -v`
Expected: all tests PASS.

- [ ] **Step 7: Format, lint, run the full suite, and commit**

```bash
uv run ruff format . && uv run ruff check . && uv run pytest
git add src/partdb/cli.py tests/unit/test_cli_format.py \
  tests/integration/test_cli_verification.py tests/integration/test_search_and_csv.py
git commit -m "feat: add declared-empty verification and clearer status and search output

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Photo Filing and Downloads Watcher Scripts

**Files:**
- Create: `.claude/skills/bin-review/scripts/file_photo.py`
- Create: `.claude/skills/bin-review/scripts/watch_downloads.sh`
- Modify: `pyproject.toml` (`[dependency-groups] dev`), `uv.lock`
- Test: `tests/unit/test_file_photo.py`, `tests/unit/test_watch_downloads.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `uv run --script .claude/skills/bin-review/scripts/file_photo.py PHOTO --bin LOCATION=IDS [--bin ...] [--note TEXT] [--keep-original]`: prints each destination path; exit 0 on success, 1 on filing failure, 2 on bad arguments.
  - Python API used by tests: `main(argv: list[str] | None) -> int`, `file_photo(source: Path, bins: list[BinTarget], note: str, root: Path, keep_original: bool) -> list[Path]`, `BinTarget(location: str, part_ids: tuple[int, ...])`, `FilingError`.
  - `bash .claude/skills/bin-review/scripts/watch_downloads.sh [DIR] [STATE_FILE]`: prints `NEW PHOTO: <path>` once per new settled image; reusing `STATE_FILE` across restarts reports photos that arrived while stopped and never repeats one.

- [ ] **Step 1: Add Pillow to the dev group**

Run: `uv add --dev "pillow>=12,<13"`
Expected: `pyproject.toml` dev group gains `"pillow>=12,<13"` and `uv.lock` updates.

- [ ] **Step 2: Write the failing photo-filing tests**

Create `tests/unit/test_file_photo.py`:

```python
import csv
import importlib.util
import os
import sys
from datetime import date, datetime
from pathlib import Path

import pytest
from PIL import Image

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / ".claude/skills/bin-review/scripts/file_photo.py"
HEADER = "file,original_name,taken_at,bin,part_ids,reviewed_on,note"


def load_script():
    spec = importlib.util.spec_from_file_location("file_photo", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["file_photo"] = module
    spec.loader.exec_module(module)
    return module


file_photo = load_script()


def make_jpeg(
    path: Path, when: str | None = "2026:09:28 18:05:12", color=(200, 0, 0)
) -> Path:
    image = Image.new("RGB", (8, 8), color)
    exif = Image.Exif()
    if when is not None:
        exif.get_ifd(0x8769)[36867] = when
    image.save(path, "JPEG", exif=exif)
    return path


def read_manifest(root: Path) -> list[dict[str, str]]:
    with (root / "manifest.csv").open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture
def downloads(tmp_path: Path) -> Path:
    path = tmp_path / "Downloads"
    path.mkdir()
    return path


@pytest.fixture
def root(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "photos"
    monkeypatch.setenv("PARTDB_PHOTO_ROOT", str(path))
    return path


def test_files_multi_bin_photo_and_removes_original(
    downloads: Path, root: Path, capsys
) -> None:
    photo = make_jpeg(downloads / "IMG_6501.JPG")
    original = photo.read_bytes()

    code = file_photo.main(
        [str(photo), "--bin", "4A3=72,80", "--bin", "4A4=", "--note", "4A3 and 4A4"]
    )

    assert code == 0
    assert not photo.exists()
    for location in ("4A3", "4A4"):
        assert (root / location / "2026-09-28_IMG_6501.JPG").read_bytes() == original
    today = date.today().isoformat()
    assert read_manifest(root) == [
        {
            "file": "4A3/2026-09-28_IMG_6501.JPG",
            "original_name": "IMG_6501.JPG",
            "taken_at": "2026-09-28T18:05:12",
            "bin": "4A3",
            "part_ids": "72;80",
            "reviewed_on": today,
            "note": "4A3 and 4A4",
        },
        {
            "file": "4A4/2026-09-28_IMG_6501.JPG",
            "original_name": "IMG_6501.JPG",
            "taken_at": "2026-09-28T18:05:12",
            "bin": "4A4",
            "part_ids": "",
            "reviewed_on": today,
            "note": "4A3 and 4A4",
        },
    ]
    assert (root / "manifest.csv").read_bytes().count(b"\r") == 0
    assert str(root / "4A3" / "2026-09-28_IMG_6501.JPG") in capsys.readouterr().out


def test_falls_back_to_mtime_without_exif(downloads: Path, root: Path) -> None:
    photo = make_jpeg(downloads / "IMG_1.JPG", when=None)
    stamp = datetime(2026, 9, 27, 17, 42, 27).timestamp()
    os.utime(photo, (stamp, stamp))

    assert file_photo.main([str(photo), "--bin", "5A1=174", "--keep-original"]) == 0

    assert read_manifest(root)[0]["taken_at"] == "2026-09-27T17:42:27"
    assert (root / "5A1" / "2026-09-27_IMG_1.JPG").exists()
    assert photo.exists()


def test_rerun_is_idempotent(downloads: Path, root: Path) -> None:
    photo = make_jpeg(downloads / "IMG_6501.JPG")
    args = [str(photo), "--bin", "4A3=72", "--keep-original"]

    assert file_photo.main(args) == 0
    assert file_photo.main(args) == 0

    assert len(read_manifest(root)) == 1


def test_different_file_with_same_name_fails_without_changes(
    downloads: Path, root: Path, capsys
) -> None:
    existing = root / "4A3" / "2026-09-28_IMG_6501.JPG"
    existing.parent.mkdir(parents=True)
    make_jpeg(existing, color=(0, 0, 255))
    photo = make_jpeg(downloads / "IMG_6501.JPG")

    code = file_photo.main([str(photo), "--bin", "4A4=", "--bin", "4A3=72"])

    assert code == 1
    assert photo.exists()
    assert not (root / "4A4").exists()
    assert not (root / "manifest.csv").exists()
    assert "already exists with different content" in capsys.readouterr().err


def test_appends_after_manifest_without_trailing_newline(
    downloads: Path, root: Path
) -> None:
    root.mkdir()
    (root / "manifest.csv").write_text(
        f"{HEADER}\n5A1/x.JPG,x.JPG,2026-09-27T17:42:27,5A1,174,2026-09-27,old",
        encoding="utf-8",
    )
    photo = make_jpeg(downloads / "IMG_6501.JPG")

    assert file_photo.main([str(photo), "--bin", "4A3=72"]) == 0

    rows = read_manifest(root)
    assert [row["file"] for row in rows] == [
        "5A1/x.JPG",
        "4A3/2026-09-28_IMG_6501.JPG",
    ]
    assert rows[0]["note"] == "old"


def test_unexpected_manifest_columns_fail_before_copying(
    downloads: Path, root: Path
) -> None:
    root.mkdir()
    (root / "manifest.csv").write_text("file,bin\n", encoding="utf-8")
    photo = make_jpeg(downloads / "IMG_6501.JPG")

    assert file_photo.main([str(photo), "--bin", "4A3=72"]) == 1

    assert photo.exists()
    assert not (root / "4A3").exists()


@pytest.mark.parametrize(
    "bins",
    [
        ["--bin", "4A3"],
        ["--bin", "4A3=x"],
        ["--bin", "=1"],
        ["--bin", "../4A3=1"],
        ["--bin", "4A3=1", "--bin", "4a3=2"],
    ],
)
def test_rejects_bad_bin_arguments(downloads: Path, root: Path, bins) -> None:
    photo = make_jpeg(downloads / "IMG_6501.JPG")

    with pytest.raises(SystemExit) as excinfo:
        file_photo.main([str(photo), *bins])

    assert excinfo.value.code == 2
    assert photo.exists()
    assert not root.exists()
```

- [ ] **Step 3: Write the failing watcher test**

Create `tests/unit/test_watch_downloads.py`:

```python
import select
import subprocess
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WATCHER = REPO / ".claude/skills/bin-review/scripts/watch_downloads.sh"


def read_line(process: subprocess.Popen, timeout: float) -> str | None:
    ready, _, _ = select.select([process.stdout], [], [], timeout)
    if not ready:
        return None
    return process.stdout.readline().strip()


def start(watched: Path, state: Path) -> subprocess.Popen:
    process = subprocess.Popen(
        ["bash", str(WATCHER), str(watched), str(state)],
        stdout=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 5
    while not state.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    return process


def test_reports_each_new_photo_once_across_restarts(tmp_path: Path) -> None:
    watched = tmp_path / "Downloads"
    watched.mkdir()
    (watched / "old.JPG").write_bytes(b"existing")
    state = tmp_path / "seen.txt"

    process = start(watched, state)
    try:
        (watched / "notes.txt").write_text("not a photo")
        (watched / "IMG_1.JPG").write_bytes(b"photo")
        assert read_line(process, 6) == f"NEW PHOTO: {watched / 'IMG_1.JPG'}"
    finally:
        process.terminate()
        process.wait()

    (watched / "IMG_2.heic").write_bytes(b"arrived while stopped")
    process = start(watched, state)
    try:
        assert read_line(process, 6) == f"NEW PHOTO: {watched / 'IMG_2.heic'}"
        assert read_line(process, 3) is None
    finally:
        process.terminate()
        process.wait()
```

- [ ] **Step 4: Run the tests and verify failure**

Run: `uv run pytest tests/unit/test_file_photo.py tests/unit/test_watch_downloads.py -v`
Expected: FAIL: `file_photo.py` not found (`FileNotFoundError` during collection), and the watcher test fails because the script does not exist.

- [ ] **Step 5: Implement `.claude/skills/bin-review/scripts/file_photo.py`**

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow>=11"]
# ///
"""File a bin-review photo into the PartDB photo archive with manifest rows."""

import argparse
import csv
import hashlib
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from PIL import Image

DEFAULT_ROOT = Path.home() / "Documents/Archive/Interests/Workshop/PartDB/photos"
FIELDS = ["file", "original_name", "taken_at", "bin", "part_ids", "reviewed_on", "note"]
EXIF_IFD = 0x8769
DATE_TIME_ORIGINAL = 36867


class FilingError(Exception):
    """The photo could not be filed. The original is left in place."""


@dataclass(frozen=True)
class BinTarget:
    location: str
    part_ids: tuple[int, ...]


def parse_bin(value: str) -> BinTarget:
    location, separator, ids = value.partition("=")
    location = location.strip()
    if not separator or not location:
        raise argparse.ArgumentTypeError(f"expected LOCATION=IDS, got {value!r}")
    if "/" in location or "\\" in location or location in {".", ".."}:
        raise argparse.ArgumentTypeError(f"invalid location {location!r}")
    try:
        part_ids = tuple(int(item) for item in ids.split(",") if item.strip())
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"part ids must be integers, got {ids!r}"
        ) from None
    return BinTarget(location, part_ids)


def taken_at(path: Path) -> datetime:
    try:
        with Image.open(path) as image:
            raw = image.getexif().get_ifd(EXIF_IFD).get(DATE_TIME_ORIGINAL)
    except OSError:
        raw = None
    if raw:
        try:
            return datetime.strptime(str(raw).strip(), "%Y:%m:%d %H:%M:%S")
        except ValueError:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime).replace(microsecond=0)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def existing_rows(manifest: Path) -> set[tuple[str, ...]]:
    if not manifest.exists():
        return set()
    with manifest.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != FIELDS:
            raise FilingError(
                f"{manifest} has columns {reader.fieldnames}, expected {FIELDS}"
            )
        return {tuple(row[field] for field in FIELDS) for row in reader}


def append_rows(manifest: Path, rows: list[dict[str, str]], seen) -> None:
    new_file = not manifest.exists()
    needs_newline = (
        not new_file
        and manifest.stat().st_size > 0
        and not manifest.read_bytes().endswith(b"\n")
    )
    with manifest.open("a", newline="", encoding="utf-8") as handle:
        if needs_newline:
            handle.write("\n")
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        if new_file:
            writer.writeheader()
        for row in rows:
            if tuple(row[field] for field in FIELDS) not in seen:
                writer.writerow(row)


def file_photo(
    source: Path,
    bins: list[BinTarget],
    note: str,
    root: Path,
    keep_original: bool,
) -> list[Path]:
    if not source.is_file():
        raise FilingError(f"{source} is not a file")
    manifest = root / "manifest.csv"
    seen = existing_rows(manifest)
    when = taken_at(source)
    digest = sha256(source)
    name = f"{when.date().isoformat()}_{source.name}"
    destinations = [root / target.location / name for target in bins]
    for destination in destinations:
        if destination.exists() and sha256(destination) != digest:
            raise FilingError(f"{destination} already exists with different content")
    for destination in destinations:
        if destination.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_name(destination.name + ".partial")
        shutil.copy2(source, partial)
        if sha256(partial) != digest:
            partial.unlink()
            raise FilingError(f"checksum mismatch copying to {destination}")
        partial.replace(destination)
    reviewed_on = date.today().isoformat()
    rows = [
        {
            "file": f"{target.location}/{name}",
            "original_name": source.name,
            "taken_at": when.isoformat(),
            "bin": target.location,
            "part_ids": ";".join(str(part_id) for part_id in target.part_ids),
            "reviewed_on": reviewed_on,
            "note": note,
        }
        for target in bins
    ]
    append_rows(manifest, rows, seen)
    if not keep_original:
        source.unlink()
    return destinations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("photo", type=Path)
    parser.add_argument(
        "--bin",
        dest="bins",
        action="append",
        type=parse_bin,
        required=True,
        metavar="LOCATION=IDS",
        help="bin shown in the photo and the part ids it shows (repeatable)",
    )
    parser.add_argument("--note", default="", help="short description of the shot")
    parser.add_argument(
        "--keep-original", action="store_true", help="do not remove the source file"
    )
    args = parser.parse_args(argv)
    locations = [target.location.casefold() for target in args.bins]
    if len(set(locations)) != len(locations):
        parser.error("each bin may be given only once")
    root = Path(os.environ.get("PARTDB_PHOTO_ROOT", DEFAULT_ROOT)).expanduser()
    try:
        destinations = file_photo(
            args.photo.expanduser(), args.bins, args.note, root, args.keep_original
        )
    except (FilingError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for destination in destinations:
        print(destination)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: Implement `.claude/skills/bin-review/scripts/watch_downloads.sh`**

```bash
#!/usr/bin/env bash
# Print "NEW PHOTO: <path>" once for each new image in DIR after its size settles.
# Usage: watch_downloads.sh [DIR] [STATE_FILE]
# Reuse STATE_FILE when restarting so photos that arrived meanwhile are reported
# and no photo is reported twice.
set -euo pipefail

dir="${1:-$HOME/Downloads}"
if [ -n "${2:-}" ]; then
  state="$2"
else
  state="$(mktemp)"
  rm -f "$state"
fi
if [ ! -e "$state" ]; then
  # Write the snapshot elsewhere first so the state file appears complete.
  find "$dir" -maxdepth 1 -type f > "$state.tmp"
  mv "$state.tmp" "$state"
fi

while true; do
  while IFS= read -r path; do
    if grep -qxF -- "$path" "$state"; then
      continue
    fi
    size="$(wc -c < "$path" 2>/dev/null)" || continue
    sleep 1
    if [ ! -e "$path" ] || [ "$(wc -c < "$path" 2>/dev/null)" != "$size" ]; then
      continue
    fi
    printf '%s\n' "$path" >> "$state"
    printf 'NEW PHOTO: %s\n' "$path"
  done < <(find "$dir" -maxdepth 1 -type f \( -iname '*.jpg' -o -iname '*.jpeg' \
    -o -iname '*.heic' -o -iname '*.png' \) | sort)
  sleep 1
done
```

Make both scripts executable: `chmod +x .claude/skills/bin-review/scripts/file_photo.py .claude/skills/bin-review/scripts/watch_downloads.sh`

- [ ] **Step 7: Run the tests and verify they pass**

Run: `uv run pytest tests/unit/test_file_photo.py tests/unit/test_watch_downloads.py -v`
Expected: all tests PASS.

- [ ] **Step 8: Verify the script runs standalone through uv**

Run: `uv run --script .claude/skills/bin-review/scripts/file_photo.py --help`
Expected: exit 0 and usage text naming `--bin LOCATION=IDS`, `--note`, and `--keep-original`.

- [ ] **Step 9: Format, lint, run the full suite, and commit**

```bash
uv run ruff format . && uv run ruff check . && uv run pytest
git add pyproject.toml uv.lock .claude/skills/bin-review/scripts \
  tests/unit/test_file_photo.py tests/unit/test_watch_downloads.py
git commit -m "feat: add bin-review photo filing and watcher scripts

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: The `bin-review` Skill and README

**Files:**
- Create: `.claude/skills/bin-review/SKILL.md`
- Modify: `README.md` (the "Physical Inventory Verification" section)
- Modify: `tests/unit/test_documented_commands.py`

**Interfaces:**
- Consumes: Task 3 `partdb apply`; Task 4 `--expect-empty`, `verify status --unverified`; Task 5 `file_photo.py`, `watch_downloads.sh`.
- Produces: the runbook a fresh session follows; README documentation of the new commands.

- [ ] **Step 1: Write the failing documentation tests**

Append to `tests/unit/test_documented_commands.py`:

```python
def test_readme_documents_reviewed_batch_workflow() -> None:
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    for required in (
        "## Applying a Reviewed Batch",
        "uv run partdb apply plan.json --dry-run",
        "uv run partdb apply plan.json --yes",
        "--expect-empty",
        "uv run partdb verify status --all",
        ".claude/skills/bin-review/",
    ):
        assert required in readme


def test_bin_review_skill_covers_the_loop() -> None:
    skill = (REPO / ".claude/skills/bin-review/SKILL.md").read_text(encoding="utf-8")
    assert skill.startswith("---\nname: bin-review\ndescription: ")
    for required in (
        "just backup",
        "watch_downloads.sh",
        "partdb apply",
        "--expect-empty",
        "file_photo.py",
        "research-queue.md",
        "partdb embeddings refresh",
        "bin-review-pilot-notes.md",
        "Never ask about quantities",
    ):
        assert required in skill
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `uv run pytest tests/unit/test_documented_commands.py -v`
Expected: the two new tests FAIL (missing README text; `SKILL.md` not found).

- [ ] **Step 3: Create `.claude/skills/bin-review/SKILL.md`**

````markdown
---
name: bin-review
description: Use when Dan is physically reviewing PartDB bins at the shelf: he sends photos or describes bin contents, and you propose corrections, apply approved changes, verify bins, and file the photos.
---

# Attended Bin Review

Dan stands at the shelves and sends photos, or describes what a bin holds. You compare that with the database, propose corrections in one table per photo, and once he approves, apply them, mark the bins verified, and file the photos. Dan does not type `partdb` commands; you run them.

The local database is the real, authoritative inventory. This repository is public: never write real inventory into it. Plans go in your scratchpad; photos, notes, and the research queue live under `~/Documents`.

## Start of Batch

1. Run `just up`, then `just backup`. Tell Dan the backup path.
2. Run `uv run partdb verify status --unverified` to see which bins remain.
3. Start the photo watcher with the Monitor tool, using a state file in your scratchpad:

   ```bash
   bash .claude/skills/bin-review/scripts/watch_downloads.sh ~/Downloads <scratchpad>/seen-photos.txt
   ```

   Each `NEW PHOTO: <path>` line is a photo to process. When the monitor expires, restart it with the same state file; photos that arrived meanwhile are reported then.
4. Tell Dan you are ready. Don't tell him what to photograph; assume he knows which bin is next.

## The Loop

1. **A photo arrives**, usually unannounced. Read the bin labels in the frame, then run `uv run partdb inventory --from <first> --through <last>` (or one bin twice) for those bins. If no label is visible, ask which bin it is.
2. **Look closely.** Downscale a copy for viewing (`sips -Z 2000 <photo> --out <scratchpad>/preview.jpg`; for HEIC add `-s format jpeg`). For colour bands, small markings, and part numbers, crop the full-resolution original with Pillow (`uv run --with pillow python ...`). Never file previews or crops.
3. **Reply with one table per photo**, and nothing after it that repeats or extends the rows:

   | Bin | ID | Action | Description | Confidence | Question |
   |---|---|---|---|---|---|

   One row per record, including `keep` rows, so each bin's full picture is in one place. Actions: `keep`, `update`, `add`, `move in`, `move to <bin>`, `delete`, `create bin`.
4. **Dan replies** `approve`, approves with an amendment ("otherwise approve"), or answers a question.
5. **Apply.** Write the approved plan to `<scratchpad>/plan-<n>.json` and run `uv run partdb apply <scratchpad>/plan-<n>.json --yes`. Set `"verify": true` when every bin in the plan is fully approved; when any bin still has an open question or an amendment you need confirmed, leave that bin out of the plan (or apply with `"verify": false` and verify later).
6. **File the photo** with the part IDs it shows, using IDs from the `apply` output for newly added parts:

   ```bash
   uv run --script .claude/skills/bin-review/scripts/file_photo.py <photo> \
     --bin 4A3=72,80 --bin 4A4= --note "4A3 and 4A4 side by side"
   ```

7. **Confirm** with one line, such as `4A3, 4A4 applied and verified; photo filed.`

### Plan Format

A plan lists each bin's complete intended contents:

```json
{"verify": true,
 "bins": {
   "4A3": {"parts": [
             {"id": 72, "description": "104K100V film capacitors, green"},
             {"id": 80},
             {"description": "M3 nylon standoffs"}],
           "remove": {"73": "delete", "74": {"move": "1D1"}}},
   "4A7": {"create": true, "parts": []}}}
```

- `{"id": N}` keeps a part; adding `description` updates it; no `id` adds a part.
- Listing an `id` that is recorded in another bin moves it into this bin. Listing it in another bin of the same plan is enough to account for it in its source bin.
- `remove` deletes a part or moves it to a bin outside the review.
- `"parts": []` means the bin must be empty.
- `"create": true` creates a missing bin. Use it only after Dan approves creating that bin in the Question column.
- Every recorded part in a listed bin must be accounted for, or `apply` rejects the whole plan and changes nothing. Use `--dry-run` if you want to check a plan first.

### Declared-Empty Ranges

When Dan says a range is empty ("4B1–4B8 empty"), run:

```bash
uv run partdb verify mark --from 4B1 --through 4B8 --expect-empty --yes
```

If it reports recorded parts, show them to Dan; "empty" then means those records need deleting or moving, which needs his approval. If a bin he names is missing from the database, propose creating it.

## Dan's Rules

- Be concise. Put every detail of an item in its table row. Ask questions only in the Question column, and only when uncertainty remains after examining the photo.
- Never ask about quantities (they are not tracked) or whether a bag is empty.
- Give no speculative guidance before a photo arrives.
- Describe the item type, not its packaging state.
- A marking on the part outranks a stale packaging label.
- Write specific, searchable descriptions: type, value or size, part number. Use the ruler in the frame for sizes; omit a size rather than guess.
- Suggesting a better home for a misplaced item is welcome; keep it brief.
- Approving a proposal means apply and verify, with no second confirmation, for exactly what was approved.
- Never verify a bin Dan has not reviewed, and never apply corrections he has not approved.

## Deferred Research

Reading labels and markings from photos is inline work. External lookups (vendor order histories, datasheets, web searches) are not: queue them so Dan never waits at the shelf.

- Append the bin, what is known, the photo filename, and what to look up to `$WORKING_DIR/Interests/Workshop/PartDB/research-queue.md`. Leave that bin unverified and move on.
- At the end of the batch, do one research pass through claude-in-chrome using Dan's logged-in browser. Vendors he orders from include Adafruit, Pololu, 18650batterystore, liionwholesale, Digi-Key, Mouser, McMaster-Carr, and Amazon.
- Present one table of proposed updates with confidence. If research finds several candidates, flag the row for a physical recheck instead of choosing. Approved rows are applied and verified like any other plan; then remove them from the queue.

## End of Batch

1. Do the research pass.
2. Run `uv run partdb embeddings refresh` so edited and added parts are searchable by meaning. It resolves its own OpenAI key through `PARTDB_OPENAI_API_KEY_CMD`; never read the key or run the helper yourself.
3. Run `just backup` and tell Dan the path.
4. Report progress from `uv run partdb verify status`.
5. Append what slowed the batch down, workarounds, and ideas to `$WORKING_DIR/Interests/Workshop/PartDB/bin-review-pilot-notes.md`.
````

- [ ] **Step 4: Update the README**

In `README.md`, replace this block in "Physical Inventory Verification":

````markdown
Undo an accidental mark and inspect progress:

```bash
uv run partdb verify clear 5A2
uv run partdb verify status
uv run partdb verify status --unverified
```
````

with:

````markdown
Mark a range only if nothing is recorded there, for bins confirmed empty:

```bash
uv run partdb verify mark --from 5A1 --through 5A8 --expect-empty
```

Undo an accidental mark and inspect progress:

```bash
uv run partdb verify clear 5A2
uv run partdb verify status              # summary line
uv run partdb verify status --unverified # remaining bins
uv run partdb verify status --all        # every bin with its status
```
````

Immediately before `## Private Data Audit`, insert:

````markdown
## Applying a Reviewed Batch

Attended bin reviews are run by an agent following the `bin-review` skill in `.claude/skills/bin-review/`. The agent applies each table Dan approves with one atomic command:

```bash
uv run partdb apply plan.json --dry-run   # show the diff only
uv run partdb apply plan.json --yes       # apply in one transaction
uv run partdb apply - --yes < plan.json   # read the plan from stdin
```

A plan lists each bin's complete intended contents:

```json
{"verify": true,
 "bins": {
   "5A1": {"parts": [
             {"id": 12, "description": "M3 x 8 mm socket head screws"},
             {"id": 13},
             {"description": "M3 nylon standoffs"}],
           "remove": {"14": "delete", "15": {"move": "5A2"}}}}}
```

Every part recorded in a listed bin must be listed, removed, or listed in another bin of the same plan; otherwise the whole plan is rejected and nothing changes. `"verify": true` marks the listed bins verified in the same transaction, and `"create": true` on a bin creates it if it is missing. Search results label the nearest empty bins before and after each match, for example `nearest empty: 5A2 ↑ 5A4 ↓`.
````

- [ ] **Step 5: Run the documentation tests and verify they pass**

Run: `uv run pytest tests/unit/test_documented_commands.py -v`
Expected: all tests PASS.

- [ ] **Step 6: Format, lint, run the full suite, and commit**

```bash
uv run ruff format . && uv run ruff check . && uv run pytest
git add .claude/skills/bin-review/SKILL.md README.md tests/unit/test_documented_commands.py
git commit -m "docs: add bin-review skill and document reviewed batches

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Acceptance, Review, and Integration

**Files:**
- Modify: `docs/superpowers/specs/2026-10-01-bin-review-workflow-design.md` (status line)
- Modify: this plan (status line and checkboxes)
- Outside the repo: `~/.claude/projects/-Users-danm-Code-gh-dsmcfarl-partdb/memory/`

**Interfaces:**
- Consumes: everything above.
- Produces: a merged, verified branch and consolidated agent memory.

- [ ] **Step 1: Run the full local gate fresh**

```bash
uv sync --locked --all-extras
uv run ruff check .
uv run ruff format --check .
docker compose up -d --wait
uv run pytest -v
```

Expected: install succeeds; lint and format checks exit 0; every test passes.

- [ ] **Step 2: Read-only smoke test against the real database**

Run `uv run partdb verify status` and record only the summary line. Pick one verified, non-empty bin from `uv run partdb verify status --all` and run `uv run partdb inventory --from <bin> --through <bin>`. Write a plan to the scratchpad that lists every one of its part IDs as `{"id": N}` with `"verify": false`, then run:

```bash
uv run partdb apply <scratchpad>/smoke-plan.json --dry-run
```

Expected: only `=` lines, then `dry run: no changes made`. Then remove one ID from the plan and rerun with `--dry-run`. Expected: nonzero exit naming that part as not accounted for. Run `uv run partdb verify status` again; the summary line must be unchanged. Do not record real descriptions in any committed file.

- [ ] **Step 3: Confirm nothing private is staged**

Run: `git status --short`
Expected: no photos, plans, CSVs, notes, or audit reports.

- [ ] **Step 4: Whole-branch review gate**

Invoke `superpowers:requesting-code-review` for a whole-branch review against the spec and this plan. Resolve findings with a failing test first, rerun Step 1, and commit the fixes.

- [ ] **Step 5: Mark the spec and plan complete**

In the spec, change `**Status:** Approved for planning` to `**Status:** Implemented`. In this plan, add `**Status:** Complete.` under the Spec line and tick every checkbox. Commit:

```bash
git add docs/superpowers
git commit -m "docs: mark bin-review workflow complete

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 6: Integrate**

Invoke `superpowers:finishing-a-development-branch` and open a pull request against `main`, as for PR #1. Wait for CI to pass and for Dan to approve the merge.

- [ ] **Step 7: Consolidate agent memory after merge**

In `~/.claude/projects/-Users-danm-Code-gh-dsmcfarl-partdb/memory/`, delete `bin-review-loop-style.md`, `bin-review-approve-implies-verify.md`, `bin-review-defer-research.md`, and `bin-review-photo-filing.md`, and remove their lines from `MEMORY.md`. Update `next-phase-status.md` to say the bin-review workflow shipped and that the next step is reviewing the remaining bins with the `bin-review` skill. Tell any running bin-review session (such as `binpilot`) to reload: rules now live in the skill.

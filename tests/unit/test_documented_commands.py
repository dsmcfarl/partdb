import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_documented_just_recipes_exist() -> None:
    justfile = (REPO / "justfile").read_text(encoding="utf-8")
    recipes = set(re.findall(r"^([a-z][a-z-]*)(?: [^:\n]*)?:$", justfile, re.MULTILINE))
    assert {
        "install",
        "up",
        "down",
        "migrate",
        "test",
        "lint",
        "backup",
        "verify-backup",
    } <= recipes


def test_compose_identity_is_stable_across_worktrees() -> None:
    compose = (REPO / "compose.yaml").read_text(encoding="utf-8")
    assert re.search(r"^name: partdb$", compose, re.MULTILINE)


def test_readme_documents_operating_configuration_and_workflows() -> None:
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    for required in (
        "PARTDB_DSN",
        "PARTDB_OPENAI_API_KEY",
        "~/Documents/Archive/Interests/Workshop/PartDB/",
        "verify-backup",
        "partdb inventory --from 5A1 --through 5A8",
        "partdb verify mark",
        "partdb verify clear",
        "uv run partdb verify status",
        "partdb_partdb-data",
    ):
        assert required in readme


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


def test_put_away_skill_covers_the_flow() -> None:
    skill = (REPO / ".claude/skills/put-away/SKILL.md").read_text(encoding="utf-8")
    assert skill.startswith("---\nname: put-away\ndescription: ")
    for required in (
        "partdb search --full-text",
        "partdb inventory",
        "nearest empty",
        "| # | Bin | Why | Record change |",
        "partdb add",
        "partdb update",
        "partdb embeddings refresh",
        "file_photo.py",
        "watch_downloads.sh",
        "Never ask about quantities",
        "Never verify",
    ):
        assert required in skill


def test_readme_points_to_put_away_skill() -> None:
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert ".claude/skills/put-away/" in readme

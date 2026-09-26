import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_documented_just_recipes_exist() -> None:
    justfile = (REPO / "justfile").read_text(encoding="utf-8")
    recipes = set(re.findall(r"^([a-z][a-z-]*)(?: [^:]*)?:$", justfile, re.MULTILINE))
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


def test_readme_documents_operating_configuration_and_workflows() -> None:
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    for required in (
        "PARTDB_DSN",
        "OPENAI_API_KEY",
        "~/Documents/Archive/Interests/Workshop/PartDB/",
        "verify-backup",
        "partdb inventory --from 5A1 --through 5A8",
        "partdb verify mark",
        "partdb verify clear",
        "partdb verify status",
    ):
        assert required in readme

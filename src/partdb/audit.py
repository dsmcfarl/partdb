import os
import re
import tempfile
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import psycopg


@dataclass(frozen=True)
class AuditFinding:
    severity: Literal["error", "warning", "info"]
    code: str
    message: str
    record_ids: tuple[int | str, ...] = ()


@dataclass(frozen=True)
class AuditReport:
    summary: Mapping[str, int]
    findings: tuple[AuditFinding, ...]


def normalize_description(value: str) -> str:
    return " ".join(value.casefold().split())


def run_audit(conn: psycopg.Connection) -> AuditReport:
    locations = list(
        conn.execute("SELECT name, verified_at FROM locations ORDER BY name")
    )
    parts = list(
        conn.execute(
            """SELECT id, location, description, embedding IS NOT NULL
            FROM parts ORDER BY id"""
        )
    )
    findings: list[AuditFinding] = []
    location_names = {row[0] for row in locations}
    occupied = {row[1] for row in parts if row[1] in location_names}

    for name, _verified_at in locations:
        if name not in occupied:
            findings.append(
                AuditFinding(
                    "info", "empty_location", f"location {name} is empty", (name,)
                )
            )
        if not re.fullmatch(r"(?:[0-9]+[A-Z]+[0-9]+|[A-Z]+[0-9]+)", name):
            findings.append(
                AuditFinding(
                    "warning",
                    "noncanonical_location_name",
                    f"location {name} does not use the canonical naming pattern",
                    (name,),
                )
            )

    locations_by_case: dict[str, list[str]] = defaultdict(list)
    for name, _verified_at in locations:
        locations_by_case[name.casefold()].append(name)
    for names in locations_by_case.values():
        if len(names) > 1:
            findings.append(
                AuditFinding(
                    "warning",
                    "case_colliding_location",
                    "location names differ only by case: " + ", ".join(names),
                    tuple(names),
                )
            )

    exact: dict[str, list[int]] = defaultdict(list)
    normalized: dict[str, list[tuple[int, str]]] = defaultdict(list)
    missing_embeddings: list[int] = []
    for part_id, location, description, has_embedding in parts:
        exact[description].append(part_id)
        normalized[normalize_description(description)].append((part_id, description))
        if not description.strip():
            findings.append(
                AuditFinding(
                    "error",
                    "blank_description",
                    f"part {part_id} has a blank description",
                    (part_id,),
                )
            )
        if location not in location_names:
            findings.append(
                AuditFinding(
                    "error",
                    "orphan_part",
                    f"part {part_id} references missing location {location}",
                    (part_id, location),
                )
            )
        if not has_embedding:
            missing_embeddings.append(part_id)

    for description, ids in exact.items():
        if len(ids) > 1:
            findings.append(
                AuditFinding(
                    "warning",
                    "exact_duplicate",
                    f"{len(ids)} parts have the exact description {description!r}",
                    tuple(ids),
                )
            )
    for description, rows in normalized.items():
        if len(rows) > 1 and len({row[1] for row in rows}) > 1:
            findings.append(
                AuditFinding(
                    "warning",
                    "normalized_duplicate",
                    f"{len(rows)} descriptions normalize to {description!r}",
                    tuple(row[0] for row in rows),
                )
            )
    if missing_embeddings:
        findings.append(
            AuditFinding(
                "warning",
                "missing_embedding",
                f"{len(missing_embeddings)} parts have no embedding",
                tuple(missing_embeddings),
            )
        )

    verified = sum(row[1] is not None for row in locations)
    return AuditReport(
        summary={
            "locations": len(locations),
            "parts": len(parts),
            "verified": verified,
            "unverified": len(locations) - verified,
        },
        findings=tuple(findings),
    )


def render_markdown(report: AuditReport) -> str:
    lines = ["# PartDB Inventory Audit", "", "## Summary", ""]
    for key in ("locations", "parts", "verified", "unverified"):
        lines.append(f"- {key}: {report.summary[key]}")
    lines.extend(["", "## Findings", ""])
    severity_order = {"error": 0, "warning": 1, "info": 2}
    findings = sorted(
        report.findings,
        key=lambda finding: (
            severity_order[finding.severity],
            finding.code,
            finding.message,
        ),
    )
    if not findings:
        lines.append("No findings.")
    current_severity = None
    for finding in findings:
        if finding.severity != current_severity:
            current_severity = finding.severity
            lines.extend([f"### {current_severity.title()}", ""])
        lines.extend([f"#### `{finding.code}`", "", finding.message])
        if finding.record_ids:
            records = ", ".join(str(item) for item in finding.record_ids)
            lines.extend(["", f"Records: {records}"])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_markdown_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as handle:
            handle.write(content)
            temporary = Path(handle.name)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()

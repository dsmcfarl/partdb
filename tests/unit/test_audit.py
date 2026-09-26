from partdb.audit import (
    AuditFinding,
    AuditReport,
    normalize_description,
    render_markdown,
)


def test_normalize_description_collapses_case_and_whitespace() -> None:
    assert normalize_description("  M3   Socket\nHead Bolt ") == "m3 socket head bolt"


def test_render_markdown_orders_severity_and_code() -> None:
    report = AuditReport(
        summary={"locations": 2, "parts": 2, "verified": 0, "unverified": 2},
        findings=(
            AuditFinding("warning", "normalized_duplicate", "two descriptions", (1, 2)),
            AuditFinding("error", "blank_description", "part 2 is blank", (2,)),
        ),
    )

    text = render_markdown(report)

    assert text.index("blank_description") < text.index("normalized_duplicate")
    assert "- locations: 2" in text
    assert "Records: 2" in text

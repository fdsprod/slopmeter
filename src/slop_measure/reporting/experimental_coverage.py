"""Put assessed scope before experimental findings."""

from slop_measure.domain.experimental_coverage import ExperimentalCoverage


def coverage_lines(summary: ExperimentalCoverage) -> list[str]:
    unit = summary.unit.replace("-", " ")
    lines = [
        "Coverage",
        f"  Files analyzed: {summary.files_analyzed}; files failed: {summary.files_failed}",
        f"  Encountered {unit}: {summary.encountered}",
        f"  Assessed: {summary.assessed}; unresolved: {summary.unresolved}",
        f"  Findings: {summary.findings}",
    ]
    if not summary.assessed:
        lines.append("  Nothing assessed within the supported scope; correctness is unknown.")
    elif not summary.findings:
        lines.append("  Assessed subjects produced no findings; this does not prove correctness.")
    if summary.unit == "class-declarations":
        lines.append("  Counts include all class declarations, not identified business models.")
    elif summary.unit == "match-handlers":
        lines.append(
            "  Findings count missing/fallback handlers; exhaustive syntax is not correctness."
        )
    if summary.files_failed:
        lines.append("  Subject counts exclude failed files; their contents are unassessed.")
    if summary.unresolved_reasons:
        lines.append("  Unresolved reasons:")
        lines.extend(f"    {item.count}: {item.reason}" for item in summary.unresolved_reasons)
    return lines

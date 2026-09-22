"""Render observed history counts separately from their interpretation."""

from collections import Counter

from slop_measure.domain.history import HistoryReport, MeasuredHistoryCounts, PartialHistory


def render_history(report: HistoryReport) -> str:
    """Return source churn, line rework, and the limits of the requested history."""
    lines = [
        "Observed source history | first-parent | unscored",
        f"Source: {report.end.root}",
        f"Range: ({report.start.revision}, {report.end.revision}]",
        f"Recent age window: {report.window_days} days | commit limit: {report.max_commits}",
        f"Traversal: {report.traversal.state}",
    ]
    if isinstance(report.traversal, PartialHistory):
        lines.append(
            f"  {report.traversal.reason} at {report.traversal.boundary_commit}; "
            "only observed steps are shown"
        )
    for step in report.steps:
        counts = step.totals
        if isinstance(counts, MeasuredHistoryCounts):
            lines.append(
                f"  {step.commit[:12]} | +{counts.added} -{counts.deleted} source lines | "
                f"churn {counts.churn} | net {counts.net:+d}"
            )
        else:
            lines.append(f"  {step.commit[:12]} | source counts unavailable")
        for cohort in step.cohorts:
            outcomes = Counter(item.state for item in cohort.rework)
            lines.append(
                f"    {cohort.language}/{cohort.cohort.value}: "
                f"{outcomes['recent']} recent, {outcomes['outside-window']} outside window, "
                f"{outcomes['unresolved']} unresolved removed lines"
            )
        for diagnostic in step.diagnostics:
            detail = diagnostic.detail
            lines.append(f"    {detail.severity.value}: {detail.message}")
    lines.extend(
        (
            "",
            "Anchor lines have unknown introduction ages. "
            "An unresolved age is not a negative case.",
            "Exact renames preserve origins. Formatting and block moves can contribute to churn.",
            "These observations do not establish defects or predict future maintenance cost.",
        )
    )
    return "\n".join(lines) + "\n"

"""Concise terminal output for the raw snapshot slice."""

from io import StringIO

from rich.console import Console

from slop_measure.domain.metrics import MeasuredMetric
from slop_measure.domain.reports import AnalysisReport, MeasuredSnapshotScore, SnapshotAnalysis


def render_snapshot(
    report: AnalysisReport, *, scope: str = "production", width: int = 80, color: bool = False
) -> str:
    """Render coverage and selected cohort results without hiding unavailable values."""
    if scope not in {"production", "test", "all"}:
        raise ValueError("scope must be production, test, or all")
    if not isinstance(report.analysis, SnapshotAnalysis):
        raise ValueError("snapshot rendering requires a snapshot report")
    stream = StringIO()
    console = Console(
        file=stream,
        width=width,
        force_terminal=color,
        no_color=not color,
        color_system="standard" if color else None,
        markup=False,
        highlight=False,
    )
    console.print("slop.measure", style="bold" if color else None)
    console.print(str(report.analysis.current.root))
    console.print("snapshot - higher is worse")
    console.print()
    console.print("source coverage")
    for record in report.coverage:
        item = record.detail
        unit = "file" if item.file_count == 1 else "files"
        console.print(
            f"  {item.cohort.value} {item.language}: {item.file_count} {unit}, {item.sloc} SLOC"
        )
        console.print(f"    {item.state.value}" + (f" - {item.reason}" if item.reason else ""))
    for cohort in report.cohorts:
        if scope not in {"all", cohort.cohort.value}:
            continue
        console.print()
        console.print(f"{cohort.cohort.value} {cohort.language}")
        score = cohort.current.score
        if isinstance(score, MeasuredSnapshotScore):
            console.print(f"  snapshot slop {score.points:g}/100")
        else:
            console.print(f"  snapshot slop unavailable: {score.reason.value}")
        for metric in cohort.current.metrics:
            if isinstance(metric, MeasuredMetric):
                console.print(f"  {metric.metric_id}: {metric.raw.value:g} {metric.raw.unit.value}")
            else:
                console.print(f"  {metric.metric_id}: unavailable ({metric.reason.value})")
    if report.diagnostics:
        console.print()
        console.print(f"diagnostics: {len(report.diagnostics)} (see --json for full details)")
    return stream.getvalue()

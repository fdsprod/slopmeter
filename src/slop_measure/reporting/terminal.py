"""Concise terminal output for the raw snapshot slice."""

from io import StringIO

from rich.console import Console

from slop_measure.config import AnalysisConfig
from slop_measure.domain.evidence import DiagnosticSeverity, PatternFinding, pattern_source_lines
from slop_measure.domain.metrics import MeasuredMetric
from slop_measure.domain.reports import (
    AnalysisReport,
    CohortResult,
    MeasuredSnapshotScore,
    SnapshotAnalysis,
)


def _render_erosion(
    console: Console, metric: MeasuredMetric, result: CohortResult, config: AnalysisConfig
) -> None:
    functions = tuple(function for file in result.files for function in file.functions)
    eroded = sorted(
        (
            function
            for function in functions
            if function.cyclomatic_complexity > config.complexity_threshold
        ),
        key=lambda function: (
            -function.mass,
            function.path.root,
            function.span.start_line,
            function.span.end_line,
            function.qualified_name,
        ),
    )
    console.print(f"  mass: {metric.raw.numerator:g} / {metric.raw.denominator:g}")
    console.print(
        f"  callables: {len(functions)}; eroded: {len(eroded)}; "
        f"CC threshold: > {config.complexity_threshold}"
    )
    if eroded:
        console.print("  eroded callables")
    for function in eroded[: config.default_hotspot_count]:
        console.print(
            f"    {function.path.root}:{function.span.start_line}-{function.span.end_line} "
            f"{function.qualified_name}: CC {function.cyclomatic_complexity}, "
            f"SLOC {function.sloc}, mass {function.mass:g}"
        )


def _render_patterns(
    console: Console, metric: MeasuredMetric, result: CohortResult, report: AnalysisReport
) -> None:
    files = {file.evidence.path.root: file.evidence for file in result.files}
    severity_order = {
        DiagnosticSeverity.ERROR: 0,
        DiagnosticSeverity.WARNING: 1,
        DiagnosticSeverity.INFO: 2,
    }

    def key(finding: PatternFinding) -> tuple[int, int, str, int, int, str]:
        return (
            severity_order[finding.severity],
            -len(pattern_source_lines(files[finding.path.root], finding)),
            finding.path.root,
            finding.span.start_line,
            finding.span.end_line,
            finding.rule_id,
        )

    findings = sorted(
        (finding.detail for finding in report.findings if finding.detail.path.root in files),
        key=key,
    )
    console.print(
        f"  pattern SLOC: {metric.raw.numerator:g} / {metric.raw.denominator:g}; "
        f"findings: {len(findings)}"
    )
    if findings:
        console.print("  pattern findings")
    for finding in findings[: report.provenance.config.default_hotspot_count]:
        console.print(
            f"    {finding.path.root}:{finding.span.start_line}-{finding.span.end_line} "
            f"{finding.rule_id}: {finding.message}"
        )


def _render_metrics(console: Console, result: CohortResult, report: AnalysisReport) -> None:
    for metric in result.metrics:
        if isinstance(metric, MeasuredMetric):
            console.print(f"  {metric.metric_id}: {metric.raw.value:g} {metric.raw.unit.value}")
            if metric.metric_id == "m4.erosion":
                _render_erosion(console, metric, result, report.provenance.config)
            elif metric.metric_id == "m2.pattern-verbosity":
                _render_patterns(console, metric, result, report)
        else:
            console.print(f"  {metric.metric_id}: unavailable ({metric.reason.value})")


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
        _render_metrics(console, cohort.current, report)
    if report.diagnostics:
        console.print()
        console.print(f"diagnostics: {len(report.diagnostics)} (see --json for full details)")
    return stream.getvalue()

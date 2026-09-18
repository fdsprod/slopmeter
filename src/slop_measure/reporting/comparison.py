"""Present source growth and quality changes as separate comparison facts."""

from slop_measure.domain.changes import (
    DeletedFile,
    FileChange,
    LineDelta,
    LineTotals,
    MeasuredMetricDelta,
    MetricDelta,
    RenamedFile,
)
from slop_measure.domain.metrics import MeasuredMetric, MetricResult
from slop_measure.domain.reports import AnalysisReport, ComparisonAnalysis, ComparisonCohortReport
from slop_measure.domain.source import GitSourceIdentity, SourceIdentity
from slop_measure.reporting.terminal import (
    _LABELS,
    _REASONS,
    _language,
    _population,
    _provenance,
    _score_row,
    _View,
    _view,
)

_PRIORITIES = (
    ("snapshot.score", "points"),
    ("verbosity.combined", "ratio"),
    ("m4.erosion", "ratio"),
)
_GROUPS = (
    "Score regressions",
    "Combined verbosity regressions",
    "Erosion regressions",
    "Other changes",
)


def _identity(source: SourceIdentity) -> str:
    suffix = f" @ {source.revision}" if isinstance(source, GitSourceIdentity) else ""
    return str(source.root) + suffix


def _line_row(view: _View, lines: LineDelta | LineTotals, label: str) -> None:
    if lines.state == "unavailable":
        view.console.print(f"  {label}: {view.missing}" + view.separator + _REASONS[lines.reason])
        return
    growth = (
        f"growth {lines.growth.value:+.1%}"
        if lines.growth.state == "measured"
        else "growth unavailable: no baseline SLOC"
    )
    view.console.print(
        f"  {label}  +{lines.added} added"
        + view.separator
        + f"-{lines.deleted} deleted"
        + view.separator
        + f"{lines.net:+d} net"
        + view.separator
        + growth
    )


def _raw_value(metrics: tuple[MetricResult, ...], metric_id: str, missing: str) -> str:
    metric = next((item for item in metrics if item.metric_id == metric_id), None)
    if not isinstance(metric, MeasuredMetric):
        return missing
    return (
        f"{metric.raw.value:.1%}" if metric.raw.unit == "ratio" else f"{metric.raw.value:g} lines"
    )


def _delta_text(delta: MetricDelta, missing: str) -> str:
    if delta.state == "unavailable":
        return missing + " | " + delta.reason.replace("-", " ")
    direction = "worse" if delta.value > 0 else "better" if delta.value < 0 else "unchanged"
    if delta.unit == "ratio":
        value = f"{delta.value * 100:+.1f} percentage points"
    else:
        value = f"{delta.value:+.1f} {delta.unit}"
    return value + " | " + direction


def _project_deltas(view: _View, cohort: ComparisonCohortReport) -> None:
    for delta in sorted(cohort.deltas, key=lambda item: item.metric_id):
        label = _LABELS.get(
            delta.metric_id,
            "Score change" if delta.metric_id == "snapshot.score" else delta.metric_id,
        )
        values = ""
        if delta.metric_id != "snapshot.score":
            before = _raw_value(cohort.baseline.metrics, delta.metric_id, view.missing)
            after = _raw_value(cohort.current.metrics, delta.metric_id, view.missing)
            values = before + " -> " + after + view.separator
        view.console.print(f"  {label}  " + values + _delta_text(delta, view.missing))


def _path(change: FileChange) -> str:
    pair = change.pair
    return pair.baseline_path.root if isinstance(pair, DeletedFile) else pair.current_path.root


def _priority(change: FileChange) -> tuple[int, float, str]:
    by_id = {delta.metric_id: delta for delta in change.deltas}
    for rank, (metric_id, unit) in enumerate(_PRIORITIES):
        delta = by_id.get(metric_id)
        if isinstance(delta, MeasuredMetricDelta) and delta.unit == unit and delta.value > 0:
            return rank, -delta.value, _path(change)
    return len(_PRIORITIES), 0, _path(change)


def _change_row(view: _View, change: FileChange) -> None:
    pair = change.pair
    if isinstance(pair, RenamedFile):
        path = pair.baseline_path.root + " -> " + pair.current_path.root
    else:
        path = _path(change)
    view.console.print(f"  {path} | {pair.kind}")
    _line_row(view, change.lines, "  Lines")
    deltas = change.deltas
    if not view.verbose:
        by_id = {delta.metric_id: delta for delta in deltas}
        priority = _priority(change)[0]
        selected = (
            by_id[_PRIORITIES[priority][0]]
            if priority < len(_PRIORITIES)
            else next(
                (
                    by_id[metric_id]
                    for metric_id, _ in _PRIORITIES
                    if isinstance(by_id.get(metric_id), MeasuredMetricDelta)
                ),
                None,
            )
        )
        deltas = (selected,) if selected is not None else deltas[:1]
    for delta in deltas:
        label = _LABELS.get(
            delta.metric_id,
            "Score change" if delta.metric_id == "snapshot.score" else delta.metric_id,
        )
        view.console.print(f"    {label}: " + _delta_text(delta, view.missing))


def _changes(view: _View, cohort: ComparisonCohortReport) -> None:
    changes = tuple(sorted(cohort.changes, key=_priority))
    previous = None
    for change in changes[: view.limit]:
        group = _priority(change)[0]
        if group != previous:
            view.console.print()
            view.console.print(_GROUPS[group])
            previous = group
        _change_row(view, change)
    omitted = len(changes) - view.limit
    if omitted > 0:
        view.console.print(f"  {omitted} file change" + ("s" if omitted != 1 else "") + " omitted")


# Preserve the snapshot renderer's public options without changing comparison evidence.
def render_comparison(  # noqa: PLR0913
    report: AnalysisReport,
    *,
    scope: str = "production",
    width: int = 100,
    color: bool = False,
    ascii: bool = False,
    verbose: bool = False,
    top: int | None = None,
) -> str:
    """Show both source states and changes without treating source growth as quality."""
    if not isinstance(report.analysis, ComparisonAnalysis):
        raise ValueError("Comparison rendering requires a comparison report.")
    if scope not in {"production", "test", "all"}:
        raise ValueError("Scope must be production, test, or all.")
    stream, view = _view(
        width,
        color,
        ascii,
        verbose,
        top if top is not None else report.provenance.config.default_hotspot_count,
    )
    view.console.print("slop.measure  comparison", style="bold")
    view.console.print("Baseline: " + _identity(report.analysis.baseline))
    view.console.print("Current:  " + _identity(report.analysis.current))
    for cohort in report.cohorts:
        if not isinstance(cohort, ComparisonCohortReport) or scope not in {
            "all",
            cohort.cohort.value,
        }:
            continue
        view.console.print()
        view.console.print(_population(cohort.cohort) + view.separator + _language(cohort.language))
        view.console.print("Baseline")
        _score_row(view, cohort.baseline.score, details=verbose)
        view.console.print("Current")
        _score_row(view, cohort.current.score, details=verbose)
        before = sum(file.evidence.sloc for file in cohort.baseline.files)
        after = sum(file.evidence.sloc for file in cohort.current.files)
        view.console.print(f"  Source lines: {before} -> {after} SLOC")
        _line_row(view, cohort.line_delta, "M1 LOC delta")
        _project_deltas(view, cohort)
        _changes(view, cohort)
    if verbose:
        _provenance(view, report)
    return stream.getvalue()

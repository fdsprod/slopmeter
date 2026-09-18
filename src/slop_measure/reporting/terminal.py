"""Concise terminal output for the raw snapshot slice."""

from dataclasses import dataclass
from io import StringIO
from pathlib import PurePosixPath

from rich.console import Console

from slop_measure.config import AnalysisConfig
from slop_measure.domain.evidence import (
    CoverageState,
    DiagnosticSeverity,
    FunctionEvidence,
    PatternFinding,
    pattern_source_lines,
)
from slop_measure.domain.metrics import (
    MeasuredMetric,
    MetricResult,
    MetricUnit,
    UnavailableMetric,
    UnavailableReason,
)
from slop_measure.domain.reports import (
    AnalysisReport,
    CohortResult,
    FileResult,
    MeasuredSnapshotScore,
    ReportCloneGroup,
    SnapshotAnalysis,
    SnapshotCohortReport,
    SnapshotScore,
    SourceSide,
)
from slop_measure.domain.source import Cohort
from slop_measure.errors import SelectionError
from slop_measure.reporting.queries import findings_for_file, select_callable, select_file
from slop_measure.scoring.hotspots import rank_hotspots


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


_LABELS = {
    "m1.loc-delta": "LOC delta",
    "m2.pattern-verbosity": "Pattern verbosity",
    "m3.clone-verbosity": "Clone verbosity",
    "m4.erosion": "Erosion",
    "verbosity.combined": "Combined verbosity",
}
_REASONS = {
    UnavailableReason.NO_BASELINE: "no baseline",
    UnavailableReason.NO_SOURCE_LINES: "no source lines",
    UnavailableReason.NO_FUNCTIONS: "no callables",
    UnavailableReason.UNSUPPORTED_LANGUAGE: "unsupported language",
    UnavailableReason.UNSUPPORTED_CAPABILITY: "not supported yet",
    UnavailableReason.PARSE_FAILED: "source error",
    UnavailableReason.ANALYZER_FAILED: "analysis error",
    UnavailableReason.CALIBRATION_MISSING: "no calibration profile",
    UnavailableReason.CALIBRATION_INCOMPATIBLE: "incompatible calibration profile",
}
_ERROR_REASONS = {UnavailableReason.PARSE_FAILED, UnavailableReason.ANALYZER_FAILED}
_FULL_COLUMNS_WIDTH = 60
_BAR_WIDTH = 20


@dataclass(frozen=True)
class _View:
    console: Console
    ascii: bool
    verbose: bool
    limit: int

    @property
    def separator(self) -> str:
        return " | " if self.ascii else " · "

    @property
    def missing(self) -> str:
        return "-" if self.ascii else "—"

    def bar(self, ratio: float) -> str:
        filled = round(max(0, min(1, ratio)) * _BAR_WIDTH)
        used, empty = ("#", "-") if self.ascii else ("█", "░")
        return f"[{used * filled}{empty * (_BAR_WIDTH - filled)}]"


def _view(
    width: int, color: bool, ascii: bool, verbose: bool, limit: int
) -> tuple[StringIO, _View]:
    if width < 1 or isinstance(limit, bool) or limit < 1:
        raise ValueError("terminal width and top must be positive")
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
    return stream, _View(console, ascii, verbose, limit)


def _cohorts(report: AnalysisReport, scope: str) -> tuple[SnapshotCohortReport, ...]:
    if scope not in {"production", "test", "all"}:
        raise ValueError("scope must be production, test, or all")
    if not isinstance(report.analysis, SnapshotAnalysis):
        raise ValueError("snapshot rendering requires a snapshot report")
    return tuple(
        item
        for item in report.cohorts
        if isinstance(item, SnapshotCohortReport) and scope in {"all", item.cohort.value}
    )


def _population(cohort: Cohort) -> str:
    return "Production" if cohort is Cohort.PRODUCTION else "Tests"


def _language(language: str) -> str:
    return "Python" if language == "python" else language


def _count(count: int, noun: str) -> str:
    return f"{count} {noun}" + ("" if count == 1 else "s")


def _partial(metrics: tuple[MetricResult, ...]) -> bool:
    return any(
        isinstance(item, UnavailableMetric) and item.reason in _ERROR_REASONS for item in metrics
    )


def _header(view: _View, report: AnalysisReport, cohorts: tuple[SnapshotCohortReport, ...]) -> None:
    view.console.print(f"slop.measure  {report.analysis.current.root}", style="bold")
    partial = any(item.detail.severity is DiagnosticSeverity.ERROR for item in report.diagnostics)
    measured = any(isinstance(item.current.score, MeasuredSnapshotScore) for item in cohorts)
    score = "Calibrated scores; lower is better" if measured else "Score unavailable"
    status = "analysis partial" if partial else "raw measurements available"
    view.console.print(score + view.separator + status)


def _coverage(view: _View, report: AnalysisReport) -> None:
    view.console.print()
    view.console.print("Coverage")
    states = {CoverageState.SCORED: 0, CoverageState.EXCLUDED: 1, CoverageState.UNSUPPORTED: 2}
    for record in sorted(
        report.coverage,
        key=lambda item: (
            states[item.detail.state],
            item.detail.cohort.value,
            item.detail.language,
            item.detail.reason or "",
        ),
    ):
        item = record.detail
        population = f"{_population(item.cohort)} {_language(item.language)}"
        if item.state is CoverageState.SCORED:
            partial = any(
                _partial(cohort.current.metrics)
                for cohort in report.cohorts
                if cohort.language == item.language and cohort.cohort is item.cohort
            )
            status = "partial" if partial else "analyzed"
            view.console.print(
                f"  {population}: {_count(item.file_count, 'file')}, {item.sloc} SLOC"
                + view.separator
                + status
            )
        else:
            view.console.print(
                f"  {item.state.value.title()} {population}: {_count(item.file_count, 'file')}"
                + view.separator
                + (item.reason or "not analyzed")
            )


def _metric_row(view: _View, metric: MeasuredMetric) -> None:
    label = _LABELS.get(metric.metric_id, metric.metric_id)
    if metric.raw.unit is MetricUnit.RATIO:
        text = f"  {label}  {metric.raw.value:.1%} {view.bar(metric.raw.value)}"
    else:
        text = f"  {label}  {metric.raw.value:g} source lines"
    if metric.metric_id in {"m2.pattern-verbosity", "m3.clone-verbosity", "verbosity.combined"}:
        text += f"  {metric.raw.numerator:g} / {metric.raw.denominator:g} SLOC"
    if view.verbose and metric.score is not None:
        text += f" | metric {metric.score.points:.1f}/100"
    view.console.print(text, style="cyan")


def _measured(view: _View, result: CohortResult, report: AnalysisReport) -> None:
    for metric in result.metrics:
        if isinstance(metric, MeasuredMetric) and (
            view.verbose or metric.metric_id != "m1.loc-delta"
        ):
            _metric_row(view, metric)
            if view.verbose and metric.metric_id == "m4.erosion":
                _render_erosion(view.console, metric, result, report.provenance.config)
            elif view.verbose and metric.metric_id == "m2.pattern-verbosity":
                _render_patterns(view.console, metric, result, report)


def _unavailable(view: _View, metrics: tuple[MetricResult, ...]) -> None:
    missing = tuple(
        item
        for item in metrics
        if isinstance(item, UnavailableMetric)
        and (view.verbose or item.metric_id != "m1.loc-delta")
    )
    if missing:
        view.console.print()
        view.console.print("Not measured")
    for item in missing:
        view.console.print(
            f"  {_LABELS.get(item.metric_id, item.metric_id)}: {view.missing}"
            + view.separator
            + _REASONS[item.reason]
        )


def _percentage(file: FileResult, metric_id: str, missing: str) -> str:
    metric = next((item for item in file.metrics if item.metric_id == metric_id), None)
    return f"{metric.raw.value:.1%}" if isinstance(metric, MeasuredMetric) else missing


def _file_values(view: _View, file: FileResult, label: str, *, scored: bool = False) -> str:
    text = label
    if scored:
        points = (
            f"{file.score.points:.1f}/100"
            if isinstance(file.score, MeasuredSnapshotScore)
            else view.missing
        )
        text += " | " + points
    text += " | " + _percentage(file, "m2.pattern-verbosity", view.missing)
    if view.console.width >= _FULL_COLUMNS_WIDTH:
        text += " | " + _percentage(file, "m4.erosion", view.missing)
    return text


def _omitted(view: _View, files: tuple[FileResult, ...]) -> None:
    count = len(files) - view.limit
    if count > 0:
        view.console.print(f"  {_count(count, 'file')} omitted")


def _file_table(view: _View, files: tuple[FileResult, ...]) -> None:
    scored = any(isinstance(file.score, MeasuredSnapshotScore) for file in files)
    ordered = (
        (
            *rank_hotspots(files, len(files)),
            *sorted(
                (file for file in files if not isinstance(file.score, MeasuredSnapshotScore)),
                key=lambda file: file.evidence.path.root,
            ),
        )
        if scored
        else tuple(sorted(files, key=lambda file: file.evidence.path.root))
    )
    view.console.print()
    view.console.print("Files (score order)" if scored else "Files (path order)")
    view.console.print(
        "  File"
        + (" | Score" if scored else "")
        + " | Patterns"
        + (" | Erosion" if view.console.width >= _FULL_COLUMNS_WIDTH else "")
    )
    for file in ordered[: view.limit]:
        view.console.print("  " + _file_values(view, file, file.evidence.path.root, scored=scored))
    _omitted(view, files)


def _score_row(view: _View, score: SnapshotScore, *, details: bool = False) -> None:
    if not isinstance(score, MeasuredSnapshotScore):
        view.console.print(
            "  Score unavailable" + view.separator + score.reason.value.replace("-", " ")
        )
        return
    view.console.print(
        f"  Score {score.points:.1f}/100 {view.bar(score.points / 100)}; lower is better"
    )
    view.console.print(f"  {score.band} | profile {score.profile_id} | model {score.model_id}")
    if details:
        view.console.print("  Score contributions")
        for contribution in score.contributions:
            view.console.print(
                f"    {_LABELS.get(contribution.metric_id, contribution.metric_id)}: "
                f"{contribution.points:.1f} points | raw {contribution.raw_value:.1%} | "
                f"percentile {contribution.percentile:.1f} | weight {contribution.weight:g}"
            )


def _heading(view: _View, cohort: SnapshotCohortReport) -> None:
    files = cohort.current.files
    view.console.print()
    view.console.print(
        view.separator.join(
            (
                _population(cohort.cohort),
                _language(cohort.language),
                _count(len(files), "file"),
                f"{sum(file.evidence.sloc for file in files)} SLOC",
            )
        )
    )
    _score_row(view, cohort.current.score, details=view.verbose)


def _footer(view: _View, report: AnalysisReport, cohorts: tuple[SnapshotCohortReport, ...]) -> None:
    paths = {file.evidence.path.root for cohort in cohorts for file in cohort.current.files}
    findings = sum(item.detail.path.root in paths for item in report.findings)
    counts = []
    if findings:
        counts.append(_count(findings, "finding"))
    if report.diagnostics:
        counts.append(_count(len(report.diagnostics), "diagnostic"))
    if counts:
        view.console.print()
        view.console.print(view.separator.join((*counts, "use explain for source evidence")))
    if view.verbose:
        _provenance(view, report)


def _provenance(view: _View, report: AnalysisReport) -> None:
    view.console.print()
    view.console.print("Provenance")
    view.console.print(f"  slop.measure {report.provenance.tool_version}")
    for adapter in report.provenance.analyzers:
        view.console.print(
            f"  {adapter.language}: {adapter.adapter_version}"
            + (f"; {adapter.rule_set_version}" if adapter.rule_set_version else "")
            + (
                f"; {adapter.clone_normalization_version}"
                if adapter.clone_normalization_version
                else ""
            )
        )
    for metric in report.provenance.metrics:
        view.console.print(f"  {metric.metric_id}: {metric.version}")


def _groups_for(
    report: AnalysisReport, paths: set[str], function: FunctionEvidence | None = None
) -> tuple[ReportCloneGroup, ...]:
    return tuple(
        sorted(
            (
                group
                for group in report.clone_groups
                if group.source is SourceSide.CURRENT
                and any(
                    member.path.root in paths
                    and (
                        function is None
                        or (
                            member.span.start_line <= function.span.end_line
                            and member.span.end_line >= function.span.start_line
                        )
                    )
                    for member in group.detail.members
                )
            ),
            key=lambda group: (
                -len(
                    {
                        (member.path.root, line)
                        for member in group.detail.members
                        for line in member.sloc_lines
                    }
                ),
                group.id,
            ),
        )
    )


def _render_clone_groups(
    view: _View, groups: tuple[ReportCloneGroup, ...], limit: int | None = None
) -> None:
    if not groups:
        return
    view.console.print()
    view.console.print("Clone groups")
    for group in groups[:limit]:
        view.console.print(f"  {group.id} | {_count(len(group.detail.members), 'instance')}")
        for member in group.detail.members:
            view.console.print(
                f"    {member.path.root}:{member.span.start_line}-{member.span.end_line}"
                f" | {len(member.sloc_lines)} SLOC"
            )
    if limit is not None and len(groups) > limit:
        view.console.print(f"  {_count(len(groups) - limit, 'clone group')} omitted")


# Public keyword options preserve the renderer API while keeping analysis configuration separate.
def render_snapshot(  # noqa: PLR0913
    report: AnalysisReport,
    *,
    scope: str = "production",
    width: int = 80,
    color: bool = False,
    ascii: bool = False,
    verbose: bool = False,
    top: int | None = None,
) -> str:
    """Show measured percentages first, followed by files and unavailable reasons."""
    cohorts = _cohorts(report, scope)
    stream, view = _view(
        width,
        color,
        ascii,
        verbose,
        top if top is not None else report.provenance.config.default_hotspot_count,
    )
    _header(view, report, cohorts)
    _coverage(view, report)
    for cohort in cohorts:
        _heading(view, cohort)
        _measured(view, cohort.current, report)
        _file_table(view, cohort.current.files)
        _render_clone_groups(
            view,
            _groups_for(report, {file.evidence.path.root for file in cohort.current.files}),
            view.limit,
        )
        _unavailable(view, cohort.current.metrics)
    _footer(view, report, cohorts)
    return stream.getvalue()


def _tree_rows(
    view: _View,
    files: tuple[FileResult, ...],
    prefix: str = "",
    depth: int = 0,
    *,
    scored: bool = False,
) -> None:
    children: dict[str, list[FileResult]] = {}
    for file in files:
        name = PurePosixPath(file.evidence.path.root).parts[depth]
        children.setdefault(name, []).append(file)
    names = sorted(children)
    for index, name in enumerate(names):
        last = index == len(names) - 1
        branch = ("`-- " if last else "|-- ") if view.ascii else ("└── " if last else "├── ")
        members = tuple(children[name])
        directory = len(PurePosixPath(members[0].evidence.path.root).parts) > depth + 1
        label = name + "/" if directory else _file_values(view, members[0], name, scored=scored)
        view.console.print(prefix + branch + label)
        if directory:
            guide = "    " if last else ("|   " if view.ascii else "│   ")
            _tree_rows(view, members, prefix + guide, depth + 1, scored=scored)


# Keep the same public presentation options as the summary renderer.
def render_tree(  # noqa: PLR0913
    report: AnalysisReport,
    *,
    scope: str = "production",
    width: int = 80,
    color: bool = False,
    ascii: bool = False,
    verbose: bool = False,
    top: int | None = None,
) -> str:
    """Show file measurements in directories without inventing directory metrics."""
    cohorts = _cohorts(report, scope)
    stream, view = _view(
        width,
        color,
        ascii,
        verbose,
        top if top is not None else report.provenance.config.default_hotspot_count,
    )
    _header(view, report, cohorts)
    _coverage(view, report)
    for cohort in cohorts:
        _heading(view, cohort)
        scored = any(isinstance(file.score, MeasuredSnapshotScore) for file in cohort.current.files)
        view.console.print(
            "File"
            + (" | Score" if scored else "")
            + " | Patterns"
            + (" | Erosion" if width >= _FULL_COLUMNS_WIDTH else "")
        )
        files = tuple(sorted(cohort.current.files, key=lambda item: item.evidence.path.root))
        _tree_rows(view, files[: view.limit], scored=scored)
        _omitted(view, files)
        _render_clone_groups(
            view, _groups_for(report, {file.evidence.path.root for file in files}), view.limit
        )
        _unavailable(view, cohort.current.metrics)
    _footer(view, report, cohorts)
    return stream.getvalue()


def _callable_row(view: _View, function: FunctionEvidence) -> None:
    view.console.print(
        f"  {function.path.root}:{function.span.start_line}-{function.span.end_line} "
        f"{function.qualified_name}: CC {function.cyclomatic_complexity}, "
        f"SLOC {function.sloc}, mass {function.mass:g}"
    )


def _explain_findings(
    view: _View, report: AnalysisReport, file: FileResult, function: FunctionEvidence | None
) -> None:
    findings = tuple(
        record.detail
        for record in findings_for_file(report, file.evidence.path.root)
        if function is None
        or (
            record.detail.span.start_line <= function.span.end_line
            and record.detail.span.end_line >= function.span.start_line
        )
    )
    view.console.print()
    view.console.print(f"Findings ({len(findings)})")
    for finding in findings:
        view.console.print(
            f"  {finding.path.root}:{finding.span.start_line}-{finding.span.end_line} "
            f"{finding.rule_id}: {finding.message}"
        )
        if finding.remediation:
            view.console.print(f"    {finding.remediation}")


def _explain_file(view: _View, file: FileResult, config: AnalysisConfig) -> None:
    _score_row(view, file.score, details=True)
    for metric in file.metrics:
        if isinstance(metric, MeasuredMetric):
            _metric_row(view, metric)
            if metric.metric_id == "m4.erosion":
                view.console.print(
                    f"  mass: {metric.raw.numerator:g} / {metric.raw.denominator:g}; "
                    f"CC threshold: > {config.complexity_threshold}"
                )
    _unavailable(view, file.metrics)
    view.console.print()
    view.console.print("Callables")
    for function in file.functions:
        _callable_row(view, function)


# Callable selectors and terminal presentation are separate public options.
def render_explanation(  # noqa: PLR0913
    report: AnalysisReport,
    path: str,
    *,
    symbol: str | None = None,
    line: int | None = None,
    width: int = 80,
    color: bool = False,
    ascii: bool = False,
    verbose: bool = False,
) -> str:
    """Explain exact file or callable evidence without fabricating callable scores."""
    if line is not None and symbol is None:
        raise SelectionError("--line requires --symbol.")
    file = select_file(report, path)
    function = select_callable(file, symbol, line=line) if symbol is not None else None
    stream, view = _view(
        width, color, ascii, verbose, report.provenance.config.default_hotspot_count
    )
    view.console.print(f"slop.measure  {file.evidence.path.root}", style="bold")
    view.console.print(
        view.separator.join((_population(file.evidence.cohort), _language(file.evidence.language)))
    )
    if function is not None:
        _callable_row(view, function)
    else:
        _explain_file(view, file, report.provenance.config)
    _explain_findings(view, report, file, function)
    _render_clone_groups(view, _groups_for(report, {file.evidence.path.root}, function))
    for record in report.diagnostics:
        if record.detail.path is None or record.detail.path == file.evidence.path:
            view.console.print(f"  {record.detail.severity.value}: {record.detail.message}")
    if verbose:
        _provenance(view, report)
    return stream.getvalue()

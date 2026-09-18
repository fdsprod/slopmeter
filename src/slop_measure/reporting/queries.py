"""Read file and callable evidence without running an analyzer again."""

from collections.abc import Iterator

from slop_measure.domain.changes import FileChange
from slop_measure.domain.evidence import DiagnosticSeverity, FunctionEvidence
from slop_measure.domain.reports import (
    AnalysisReport,
    CohortResult,
    ComparisonCohortReport,
    FileResult,
    ReportCloneGroup,
    ReportFinding,
    SnapshotAnalysis,
    SourceSide,
)
from slop_measure.domain.source import Cohort, ProjectPath
from slop_measure.errors import SelectionError
from slop_measure.reporting.selections import ErosionFinding, FindingSelection


def _source(report: AnalysisReport, source: SourceSide) -> SourceSide:
    try:
        source = SourceSide(source)
    except ValueError as error:
        raise SelectionError("Source must be baseline or current.") from error
    if source is SourceSide.BASELINE and isinstance(report.analysis, SnapshotAnalysis):
        raise SelectionError("A snapshot has no baseline source.")
    return source


def _path(path: str) -> ProjectPath:
    try:
        return ProjectPath(path)
    except ValueError as error:
        raise SelectionError(f"Invalid project-relative path: {path}") from error


def _results(
    report: AnalysisReport, source: SourceSide
) -> Iterator[tuple[str, Cohort, CohortResult]]:
    for cohort in report.cohorts:
        result = (
            cohort.baseline
            if source is SourceSide.BASELINE and isinstance(cohort, ComparisonCohortReport)
            else cohort.current
        )
        yield cohort.language, cohort.cohort, result


def select_file(
    report: AnalysisReport, path: str, *, source: SourceSide = SourceSide.CURRENT
) -> FileResult:
    """Resolve an exact project-relative file in the selected source state."""
    source = _source(report, source)
    selected = _path(path)
    for _, _, result in _results(report, source):
        for file in result.files:
            if file.evidence.path == selected:
                return file
    raise SelectionError(f"File not found in report: {selected.root}")


def findings_for_file(
    report: AnalysisReport, path: str, *, source: SourceSide = SourceSide.CURRENT
) -> tuple[ReportFinding, ...]:
    """Return the original finding records for the selected file."""
    source = _source(report, source)
    file = select_file(report, path, source=source)
    return tuple(
        finding
        for finding in report.findings
        if finding.source is source and finding.detail.path == file.evidence.path
    )


def clones_for_file(
    report: AnalysisReport, path: str, *, source: SourceSide = SourceSide.CURRENT
) -> tuple[ReportCloneGroup, ...]:
    """Keep complete clone groups when the selected file owns any member."""
    source = _source(report, source)
    file = select_file(report, path, source=source)
    return tuple(
        group
        for group in report.clone_groups
        if group.source is source
        and any(member.path == file.evidence.path for member in group.detail.members)
    )


def change_for_file(
    report: AnalysisReport, path: str, *, source: SourceSide = SourceSide.CURRENT
) -> FileChange:
    """Return the owned change for a path on its explicitly selected side."""
    source = _source(report, source)
    if isinstance(report.analysis, SnapshotAnalysis):
        raise SelectionError("A snapshot has no file changes.")
    file = select_file(report, path, source=source)
    for cohort in report.cohorts:
        if isinstance(cohort, ComparisonCohortReport):
            for change in cohort.changes:
                if getattr(change.pair, f"{source.value}_path", None) == file.evidence.path:
                    return change
    raise SelectionError(f"File change not found: {path}")


def _metric_families(metric: str | None) -> frozenset[str]:
    families = {
        "m2": frozenset({"patterns"}),
        "m3": frozenset({"clones"}),
        "m4": frozenset({"functions"}),
        "combined": frozenset({"patterns", "clones"}),
    }
    aliases = {
        "m2.pattern-verbosity": "m2",
        "m3.clone-verbosity": "m3",
        "m4.erosion": "m4",
        "verbosity.combined": "combined",
    }
    if metric is None:
        return frozenset({"patterns", "clones", "functions"})
    selected = aliases.get(metric, metric)
    if selected not in families:
        raise SelectionError(f"Unknown evidence metric: {metric}")
    return families[selected]


def _eroded(
    report: AnalysisReport, source: SourceSide, path: ProjectPath | None
) -> tuple[ErosionFinding, ...]:
    findings = (
        ErosionFinding(source=source, language=language, cohort=cohort, function=function)
        for language, cohort, result in _results(report, source)
        for file in result.files
        if path is None or file.evidence.path == path
        for function in file.functions
        if function.cyclomatic_complexity > report.provenance.config.complexity_threshold
    )
    return tuple(
        sorted(
            findings,
            key=lambda item: (
                item.function.path.root,
                item.function.span.start_line,
                item.function.span.end_line,
                item.function.qualified_name,
            ),
        )
    )


# These filters apply to independent native evidence fields.
def query_findings(  # noqa: PLR0913
    report: AnalysisReport,
    *,
    path: str | None = None,
    metric: str | None = None,
    rule: str | None = None,
    severity: DiagnosticSeverity | None = None,
    source: SourceSide = SourceSide.CURRENT,
) -> FindingSelection:
    """Filter existing evidence while preserving native fields and clone membership."""
    source = _source(report, source)
    selected = _path(path) if path is not None else None
    families = _metric_families(metric)
    patterns = tuple(
        item
        for item in report.findings
        if "patterns" in families
        and item.source is source
        and (selected is None or item.detail.path == selected)
        and (rule is None or item.detail.rule_id == rule)
        and (severity is None or item.detail.severity == severity)
    )
    groups = tuple(
        item
        for item in report.clone_groups
        if "clones" in families
        and rule is None
        and severity is None
        and item.source is source
        and (selected is None or any(member.path == selected for member in item.detail.members))
    )
    return FindingSelection(
        patterns=tuple(
            sorted(
                patterns,
                key=lambda item: (
                    item.detail.path.root,
                    item.detail.span.start_line,
                    item.detail.span.end_line,
                    item.id,
                ),
            )
        ),
        clone_groups=tuple(
            sorted(
                groups,
                key=lambda item: (
                    min(
                        (member.path.root, member.span.start_line) for member in item.detail.members
                    ),
                    item.id,
                ),
            )
        ),
        functions=(
            _eroded(report, source, selected)
            if "functions" in families and rule is None and severity is None
            else ()
        ),
    )


def select_callable(file: FileResult, name: str, *, line: int | None = None) -> FunctionEvidence:
    """Resolve an exact qualified name, optionally at its definition start line."""
    matches = tuple(
        function
        for function in file.functions
        if function.qualified_name == name and (line is None or function.span.start_line == line)
    )
    if not matches:
        location = f" at line {line}" if line is not None else ""
        raise SelectionError(f"Callable not found: {file.evidence.path.root}:{name}{location}")
    if len(matches) != 1:
        raise SelectionError(f"Ambiguous callable: {name}. Select its start line with --line.")
    return matches[0]

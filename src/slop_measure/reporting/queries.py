"""Read file and callable evidence without running an analyzer again."""

from slop_measure.domain.evidence import FunctionEvidence
from slop_measure.domain.reports import (
    AnalysisReport,
    FileResult,
    ReportFinding,
    SnapshotAnalysis,
    SourceSide,
)
from slop_measure.domain.source import ProjectPath
from slop_measure.errors import SelectionError


def select_file(report: AnalysisReport, path: str) -> FileResult:
    """Resolve an exact project-relative file in a snapshot report."""
    if not isinstance(report.analysis, SnapshotAnalysis):
        raise SelectionError("File selection requires a snapshot report.")
    try:
        selected = ProjectPath(path)
    except ValueError as error:
        raise SelectionError(f"Invalid project-relative path: {path}") from error
    for cohort in report.cohorts:
        for file in cohort.current.files:
            if file.evidence.path == selected:
                return file
    raise SelectionError(f"File not found in report: {selected.root}")


def findings_for_file(report: AnalysisReport, path: str) -> tuple[ReportFinding, ...]:
    """Return the original finding records for the selected file."""
    file = select_file(report, path)
    return tuple(
        finding
        for finding in report.findings
        if finding.source is SourceSide.CURRENT and finding.detail.path == file.evidence.path
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

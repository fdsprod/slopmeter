"""Pattern verbosity from unions of physical source-line identities."""

from slop_measure.domain.evidence import (
    FileEvidence,
    ParseState,
    PatternFinding,
    pattern_source_lines,
)
from slop_measure.domain.metrics import (
    FileMetricScope,
    MeasuredMetric,
    MetricMeasurement,
    MetricResult,
    MetricScope,
    MetricUnit,
    UnavailableMetric,
    UnavailableReason,
)


def _validate_files(files: tuple[FileEvidence, ...], scope: MetricScope) -> None:
    if len({file.path.root for file in files}) != len(files):
        raise ValueError("pattern measurement requires unique file paths")
    for file in files:
        if file.parse_state is not ParseState.PARSED:
            raise ValueError("pattern measurement requires parsed files")
        if file.cohort is not scope.cohort:
            raise ValueError("source cohort must match the metric scope")
        if isinstance(scope, FileMetricScope) and file.path != scope.path:
            raise ValueError("source path must match the file metric scope")


def measure_patterns(
    files: tuple[FileEvidence, ...], findings: tuple[PatternFinding, ...], scope: MetricScope
) -> MetricResult:
    """Count each flagged source line once within its file and population."""
    _validate_files(files, scope)
    by_path = {file.path.root: file for file in files}
    flagged: set[tuple[str, int]] = set()
    for finding in findings:
        file = by_path.get(finding.path.root)
        if file is None:
            raise ValueError("pattern finding refers to a file outside the measured scope")
        flagged.update((file.path.root, line) for line in pattern_source_lines(file, finding))
    total = sum(file.sloc for file in files)
    if total == 0:
        return UnavailableMetric(
            metric_id="m2.pattern-verbosity", scope=scope, reason=UnavailableReason.NO_SOURCE_LINES
        )
    return MeasuredMetric(
        metric_id="m2.pattern-verbosity",
        scope=scope,
        raw=MetricMeasurement(
            numerator=len(flagged),
            denominator=total,
            value=len(flagged) / total,
            unit=MetricUnit.RATIO,
        ),
    )

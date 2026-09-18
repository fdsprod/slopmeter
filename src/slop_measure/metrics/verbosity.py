"""Pattern verbosity from unions of physical source-line identities."""

from slop_measure.domain.evidence import (
    CloneGroup,
    FileEvidence,
    ParseState,
    PatternFinding,
    pattern_source_lines,
    validate_clone_member,
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


def _clone_lines(
    files: tuple[FileEvidence, ...], groups: tuple[CloneGroup, ...], scope: MetricScope
) -> set[tuple[str, int]]:
    by_path = {file.path.root: file for file in files}
    lines: set[tuple[str, int]] = set()
    for group in groups:
        if group.cohort is not scope.cohort:
            raise ValueError("clone cohort must match the measured population")
        for member in group.members:
            file = by_path.get(member.path.root)
            if file is None:
                if isinstance(scope, FileMetricScope) and member.path != scope.path:
                    continue
                raise ValueError("clone member has no file in the measured project")
            if file.language != group.language:
                raise ValueError("clone language must match its owning file")
            validate_clone_member(file, member)
            lines.update((member.path.root, line) for line in member.sloc_lines)
    return lines


def _union_metric(
    metric_id: str,
    files: tuple[FileEvidence, ...],
    lines: set[tuple[str, int]],
    scope: MetricScope,
) -> MetricResult:
    total = sum(file.sloc for file in files)
    if not total:
        return UnavailableMetric(
            metric_id=metric_id, scope=scope, reason=UnavailableReason.NO_SOURCE_LINES
        )
    return MeasuredMetric(
        metric_id=metric_id,
        scope=scope,
        raw=MetricMeasurement(
            numerator=len(lines), denominator=total, value=len(lines) / total, unit=MetricUnit.RATIO
        ),
    )


def measure_clones(
    files: tuple[FileEvidence, ...], groups: tuple[CloneGroup, ...], scope: MetricScope
) -> MetricResult:
    """Count each cloned physical source line once in the selected population."""
    _validate_files(files, scope)
    return _union_metric("m3.clone-verbosity", files, _clone_lines(files, groups, scope), scope)


def measure_combined_verbosity(
    files: tuple[FileEvidence, ...],
    findings: tuple[PatternFinding, ...],
    groups: tuple[CloneGroup, ...],
    scope: MetricScope,
) -> MetricResult:
    """Union pattern and clone evidence without counting an overlapping line twice."""
    _validate_files(files, scope)
    lines = _clone_lines(files, groups, scope)
    by_path = {file.path.root: file for file in files}
    for finding in findings:
        file = by_path.get(finding.path.root)
        if file is None:
            raise ValueError("pattern finding has no file in the measured scope")
        lines.update((file.path.root, line) for line in pattern_source_lines(file, finding))
    return _union_metric("verbosity.combined", files, lines, scope)

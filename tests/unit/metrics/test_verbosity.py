"""M2 counts the union of matched physical source lines across a scope."""

import pytest

from slop_measure.domain.evidence import FileEvidence, PatternFinding
from slop_measure.domain.metrics import (
    FileMetricScope,
    MeasuredMetric,
    ProjectMetricScope,
    UnavailableMetric,
    UnavailableReason,
)
from slop_measure.domain.source import Cohort, ProjectPath
from slop_measure.metrics.verbosity import measure_patterns


def file(
    path: str = "app.py", lines: tuple[int, ...] = (1, 2, 4, 5), cohort: str = "production"
) -> FileEvidence:
    return FileEvidence.model_validate(
        {
            "path": path,
            "language": "python",
            "cohort": cohort,
            "sloc": len(lines),
            "sloc_lines": lines,
            "parse_state": "parsed",
        }
    )


def finding(start: int, end: int, *, path: str = "app.py", rule_id: str = "rule") -> PatternFinding:
    return PatternFinding.model_validate(
        {
            "path": path,
            "rule_id": rule_id,
            "category": "redundancy",
            "severity": "warning",
            "message": "Redundant source.",
            "span": {"start_line": start, "end_line": end},
        }
    )


def test_m2_counts_overlapping_sloc_once_and_omits_non_source_lines() -> None:
    scope = ProjectMetricScope(cohort=Cohort.PRODUCTION)
    result = measure_patterns((file(),), (finding(1, 3), finding(2, 4, rule_id="other")), scope)
    assert isinstance(result, MeasuredMetric)
    assert result.metric_id == "m2.pattern-verbosity"
    assert result.scope == scope
    assert result.raw.numerator == 3
    assert result.raw.denominator == 4
    assert result.raw.value == 0.75
    assert result.score is None


def test_project_m2_uses_totals_not_average_file_ratios() -> None:
    files = (file("small.py", (1,)), file("large.py", tuple(range(1, 10))))
    result = measure_patterns(
        files, (finding(1, 1, path="small.py"),), ProjectMetricScope(cohort=Cohort.PRODUCTION)
    )
    assert isinstance(result, MeasuredMetric)
    assert result.raw.numerator == 1 and result.raw.denominator == 10
    assert result.raw.value == 0.1


def test_same_line_number_in_different_files_counts_separately() -> None:
    result = measure_patterns(
        (file("a.py", (1,)), file("b.py", (1,))),
        (finding(1, 1, path="a.py"), finding(1, 1, path="b.py")),
        ProjectMetricScope(cohort=Cohort.PRODUCTION),
    )
    assert isinstance(result, MeasuredMetric)
    assert result.raw.numerator == result.raw.denominator == 2
    assert result.raw.value == 1


def test_no_findings_is_measured_zero_when_source_exists() -> None:
    result = measure_patterns((file(),), (), ProjectMetricScope(cohort=Cohort.PRODUCTION))
    assert isinstance(result, MeasuredMetric)
    assert result.raw.value == result.raw.numerator == 0
    assert result.raw.denominator == 4


@pytest.mark.parametrize("files", [(), (file(lines=()),)])
def test_no_source_is_unavailable(files: tuple[FileEvidence, ...]) -> None:
    result = measure_patterns(files, (), ProjectMetricScope(cohort=Cohort.PRODUCTION))
    assert isinstance(result, UnavailableMetric)
    assert result.reason is UnavailableReason.NO_SOURCE_LINES


@pytest.mark.parametrize(
    "change",
    [
        "unknown-path",
        "no-intersection",
        "duplicate-file",
        "wrong-cohort",
        "failed-file",
        "wrong-file-scope",
    ],
)
def test_m2_rejects_inconsistent_input_scope(change: str) -> None:
    files = (file(),)
    findings = (finding(1, 2),)
    scope = ProjectMetricScope(cohort=Cohort.PRODUCTION)
    if change == "unknown-path":
        findings = (finding(1, 2, path="unknown.py"),)
    elif change == "no-intersection":
        findings = (finding(3, 3),)
    elif change == "duplicate-file":
        files *= 2
    elif change == "wrong-cohort":
        files = (file(cohort="test"),)
    elif change == "failed-file":
        files = (FileEvidence.model_validate({**file().model_dump(), "parse_state": "failed"}),)
    else:
        scope = FileMetricScope(path=ProjectPath("other.py"), cohort=Cohort.PRODUCTION)
    with pytest.raises(ValueError):
        measure_patterns(files, findings, scope)


def test_file_scope_preserves_path_and_test_cohort() -> None:
    scope = FileMetricScope(path=ProjectPath("app.py"), cohort=Cohort.TEST)
    result = measure_patterns((file(cohort="test"),), (finding(1, 2),), scope)
    assert isinstance(result, MeasuredMetric)
    assert result.scope == scope
    assert result.raw.value == 0.5

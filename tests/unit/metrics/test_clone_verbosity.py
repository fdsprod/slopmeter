"""M3 and combined verbosity count owned physical line unions, not averages."""

import pytest

from slop_measure.domain.evidence import CloneGroup, FileEvidence, PatternFinding
from slop_measure.domain.metrics import (
    FileMetricScope,
    MeasuredMetric,
    ProjectMetricScope,
    UnavailableMetric,
    UnavailableReason,
)
from slop_measure.domain.source import Cohort, ProjectPath
from slop_measure.metrics.verbosity import measure_clones, measure_combined_verbosity


def file(path: str, lines: tuple[int, ...] = (1, 2, 3, 4, 5, 6)) -> FileEvidence:
    return FileEvidence.model_validate(
        dict(
            path=path,
            language="python",
            cohort="production",
            parse_state="parsed",
            sloc=len(lines),
            sloc_lines=lines,
        )
    )


def group(start: int = 1, end: int = 3) -> CloneGroup:
    return CloneGroup.model_validate(
        dict(
            language="python",
            cohort="production",
            normalization_version="v1",
            fingerprint="a" * 64,
            members=[
                dict(
                    path=path,
                    span=dict(start_line=start, end_line=end),
                    sloc_lines=tuple(range(start, end + 1)),
                )
                for path in ("a.py", "b.py")
            ],
        )
    )


def finding(path: str, start: int, end: int) -> PatternFinding:
    return PatternFinding.model_validate(
        dict(
            path=path,
            rule_id="rule",
            category="redundancy",
            severity="warning",
            message="Redundant source.",
            span=dict(start_line=start, end_line=end),
        )
    )


def test_clone_union_counts_overlapping_groups_once_in_each_file() -> None:
    result = measure_clones(
        (file("a.py"), file("b.py")),
        (group(), group(3, 4)),
        ProjectMetricScope(cohort=Cohort.PRODUCTION),
    )
    assert isinstance(result, MeasuredMetric)
    assert result.metric_id == "m3.clone-verbosity"
    assert result.raw.numerator == 8
    assert result.raw.denominator == 12
    assert result.raw.value == pytest.approx(2 / 3)
    assert result.score is None


def test_combined_unions_pattern_and_clone_lines_instead_of_adding_ratios() -> None:
    result = measure_combined_verbosity(
        (file("a.py"), file("b.py")),
        (finding("a.py", 2, 4), finding("b.py", 6, 6)),
        (group(),),
        ProjectMetricScope(cohort=Cohort.PRODUCTION),
    )
    assert isinstance(result, MeasuredMetric)
    assert result.metric_id == "verbosity.combined"
    assert result.raw.numerator == 8
    assert result.raw.denominator == 12
    assert result.raw.value == pytest.approx(2 / 3)


def test_project_ratio_uses_population_totals() -> None:
    result = measure_clones(
        (file("a.py", (1, 2, 3)), file("b.py", tuple(range(1, 10)))),
        (group(),),
        ProjectMetricScope(cohort=Cohort.PRODUCTION),
    )
    assert isinstance(result, MeasuredMetric)
    assert result.raw.numerator == 6 and result.raw.denominator == 12
    assert result.raw.value == 0.5


def test_file_scope_accepts_cross_file_group_and_counts_only_selected_members() -> None:
    scope = FileMetricScope(path=ProjectPath("a.py"), cohort=Cohort.PRODUCTION)
    result = measure_clones((file("a.py"),), (group(),), scope)
    combined = measure_combined_verbosity(
        (file("a.py"),), (finding("a.py", 3, 4),), (group(),), scope
    )
    assert isinstance(result, MeasuredMetric) and isinstance(combined, MeasuredMetric)
    assert result.scope == combined.scope == scope
    assert result.raw.numerator == 3 and result.raw.denominator == 6
    assert combined.raw.numerator == 4 and combined.raw.denominator == 6


@pytest.mark.parametrize("combined", [False, True])
def test_empty_matches_is_zero_but_empty_population_is_unavailable(combined: bool) -> None:
    scope = ProjectMetricScope(cohort=Cohort.PRODUCTION)
    result = (
        measure_combined_verbosity((file("a.py"),), (), (), scope)
        if combined
        else measure_clones((file("a.py"),), (), scope)
    )
    assert isinstance(result, MeasuredMetric)
    assert result.raw.value == result.raw.numerator == 0
    assert result.raw.denominator == 6
    empty = (
        measure_combined_verbosity((), (), (), scope) if combined else measure_clones((), (), scope)
    )
    assert (
        isinstance(empty, UnavailableMetric) and empty.reason is UnavailableReason.NO_SOURCE_LINES
    )


@pytest.mark.parametrize("combined", [False, True])
@pytest.mark.parametrize(
    "change",
    [
        "missing-member",
        "wrong-lines",
        "duplicate-file",
        "failed-file",
        "wrong-cohort",
        "wrong-language",
        "wrong-file-scope",
    ],
)
def test_measurements_reject_inconsistent_population(combined: bool, change: str) -> None:
    files = (file("a.py"), file("b.py"))
    scope = ProjectMetricScope(cohort=Cohort.PRODUCTION)
    if change == "missing-member":
        files = files[:1]
    elif change == "wrong-lines":
        files = (file("a.py", (1, 3, 4, 5, 6)), files[1])
    elif change == "duplicate-file":
        files += files[:1]
    elif change in ("failed-file", "wrong-cohort", "wrong-language"):
        field, value = {
            "failed-file": ("parse_state", "failed"),
            "wrong-cohort": ("cohort", "test"),
            "wrong-language": ("language", "other"),
        }[change]
        files = (FileEvidence.model_validate({**files[0].model_dump(), field: value}), files[1])
    else:
        scope = FileMetricScope(path=ProjectPath("other.py"), cohort=Cohort.PRODUCTION)
    with pytest.raises(ValueError):
        if combined:
            measure_combined_verbosity(files, (), (group(),), scope)
        else:
            measure_clones(files, (group(),), scope)


@pytest.mark.parametrize("bad_finding", [finding("missing.py", 1, 1), finding("a.py", 7, 8)])
def test_combined_rejects_unowned_pattern_evidence(bad_finding: PatternFinding) -> None:
    with pytest.raises(ValueError):
        measure_combined_verbosity(
            (file("a.py"), file("b.py")),
            (bad_finding,),
            (group(),),
            ProjectMetricScope(cohort=Cohort.PRODUCTION),
        )

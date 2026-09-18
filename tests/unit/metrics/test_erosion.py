"""M4 uses callable mass totals and a strict complexity threshold."""

import math

import pytest

from slop_measure.domain.evidence import FunctionEvidence
from slop_measure.domain.metrics import (
    FileMetricScope,
    MeasuredMetric,
    ProjectMetricScope,
    UnavailableMetric,
    UnavailableReason,
)
from slop_measure.domain.source import Cohort, ProjectPath
from slop_measure.metrics.erosion import measure_erosion


def function(name: str, cc: int, sloc: int, path: str = "app.py") -> FunctionEvidence:
    return FunctionEvidence.model_validate(
        {
            "path": path,
            "qualified_name": name,
            "cyclomatic_complexity": cc,
            "sloc_lines": tuple(range(1, sloc + 1)),
            "span": {"start_line": 1, "end_line": sloc},
        }
    )


def test_erosion_sums_sqrt_line_mass_and_excludes_exact_threshold_from_numerator() -> None:
    functions = (function("boundary", 10, 4), function("eroded", 11, 9), function("simple", 1, 2))
    scope = ProjectMetricScope(cohort=Cohort.PRODUCTION)
    result = measure_erosion(functions, scope, 10)
    assert isinstance(result, MeasuredMetric)
    assert result.metric_id == "m4.erosion"
    assert result.scope == scope
    assert result.raw.numerator == 33
    assert result.raw.denominator == pytest.approx(20 + 33 + math.sqrt(2))
    assert result.raw.value == pytest.approx(33 / (53 + math.sqrt(2)))
    assert result.score is None


def test_no_eroded_functions_is_measured_zero() -> None:
    result = measure_erosion((function("f", 10, 1),), ProjectMetricScope(cohort=Cohort.TEST), 10)
    assert isinstance(result, MeasuredMetric)
    assert result.raw.numerator == result.raw.value == 0
    assert result.raw.denominator == 10


def test_no_functions_is_unavailable_without_a_fabricated_zero() -> None:
    result = measure_erosion((), ProjectMetricScope(cohort=Cohort.PRODUCTION), 10)
    assert isinstance(result, UnavailableMetric)
    assert result.reason is UnavailableReason.NO_FUNCTIONS


def test_project_erosion_uses_mass_totals_instead_of_averaging_file_ratios() -> None:
    functions = (function("high", 11, 1, "small.py"), function("low", 1, 100, "large.py"))
    result = measure_erosion(functions, ProjectMetricScope(cohort=Cohort.PRODUCTION), 10)
    assert isinstance(result, MeasuredMetric)
    assert result.raw.numerator == 11
    assert result.raw.denominator == 21
    assert result.raw.value == pytest.approx(11 / 21)
    assert result.raw.value != 0.5


@pytest.mark.parametrize("threshold", [True, False, 0, -1, 1.5])
def test_erosion_rejects_invalid_thresholds(threshold: object) -> None:
    with pytest.raises((ValueError, TypeError)):
        measure_erosion((), ProjectMetricScope(cohort=Cohort.PRODUCTION), threshold)  # type: ignore[arg-type]


def test_file_scope_rejects_functions_from_another_path() -> None:
    scope = FileMetricScope(path=ProjectPath("app.py"), cohort=Cohort.PRODUCTION)
    with pytest.raises(ValueError):
        measure_erosion((function("f", 1, 1, "other.py"),), scope, 10)


def test_file_scope_preserves_cohort_and_path() -> None:
    scope = FileMetricScope(path=ProjectPath("app.py"), cohort=Cohort.TEST)
    result = measure_erosion((function("f", 11, 1),), scope, 10)
    assert isinstance(result, MeasuredMetric)
    assert result.scope == scope
    assert result.raw.value == 1

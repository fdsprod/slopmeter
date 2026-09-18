"""Behavioral tests for metric scopes and result-state contracts."""

import pytest
from pydantic import TypeAdapter, ValidationError

from slop_measure.domain.metrics import (
    CalibratedScore,
    FileMetricScope,
    MeasuredMetric,
    MetricMeasurement,
    MetricResult,
    MetricUnit,
    ProjectMetricScope,
    UnavailableMetric,
    UnavailableReason,
)
from slop_measure.domain.source import Cohort, ProjectPath


def test_metric_scope_is_an_explicit_tagged_union() -> None:
    adapter = TypeAdapter(MetricResult)

    project_result = adapter.validate_python(
        {
            "state": "unavailable",
            "metric_id": "m1.loc-delta",
            "scope": {"kind": "project", "cohort": "production"},
            "reason": "no-baseline",
        }
    )
    file_result = adapter.validate_python(
        {
            "state": "unavailable",
            "metric_id": "m4.erosion",
            "scope": {
                "kind": "file",
                "path": "src/parser.py",
                "cohort": "test",
            },
            "reason": "no-functions",
        }
    )

    assert isinstance(project_result.scope, ProjectMetricScope)
    assert project_result.scope.cohort is Cohort.PRODUCTION
    assert isinstance(file_result.scope, FileMetricScope)
    assert file_result.scope.path == ProjectPath("src/parser.py")
    assert file_result.scope.cohort is Cohort.TEST


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "project", "path": "src/app.py", "cohort": "production"},
        {"kind": "file", "cohort": "production"},
        {"kind": "workspace", "cohort": "production"},
    ],
)
def test_metric_scope_rejects_mixed_or_unknown_variants(payload: object) -> None:
    with pytest.raises(ValidationError):
        UnavailableMetric(
            metric_id="m4.erosion",
            scope=payload,  # type: ignore[arg-type]
            reason=UnavailableReason.NO_FUNCTIONS,
        )


def test_metric_measurement_preserves_raw_inputs_and_value() -> None:
    measurement = MetricMeasurement(
        numerator=27.5,
        denominator=604.25,
        value=27.5 / 604.25,
        unit=MetricUnit.RATIO,
    )

    assert measurement.model_dump(mode="json") == {
        "numerator": 27.5,
        "denominator": 604.25,
        "value": 27.5 / 604.25,
        "unit": "ratio",
    }


@pytest.mark.parametrize("denominator", [0, -2])
def test_ratio_measurement_requires_a_positive_denominator(denominator: float) -> None:
    with pytest.raises(ValidationError):
        MetricMeasurement(numerator=1, denominator=denominator, value=0.5, unit=MetricUnit.RATIO)


def test_ratio_measurement_rejects_a_value_that_disagrees_with_its_inputs() -> None:
    with pytest.raises(ValidationError):
        MetricMeasurement(numerator=1, denominator=4, value=0.5, unit=MetricUnit.RATIO)


@pytest.mark.parametrize("numerator", [-3, 7])
def test_ratio_measurement_allows_signed_and_unbounded_ratios(numerator: float) -> None:
    measurement = MetricMeasurement(
        numerator=numerator, denominator=2, value=numerator / 2, unit=MetricUnit.RATIO
    )

    assert measurement.value == numerator / 2


def test_ratio_measurement_tolerates_floating_point_roundoff() -> None:
    measurement = MetricMeasurement(
        numerator=0.1 + 0.2, denominator=1, value=0.3, unit=MetricUnit.RATIO
    )

    assert measurement.value == 0.3


def test_line_measurement_preserves_negative_net_changes_without_a_baseline() -> None:
    measurement = MetricMeasurement(numerator=-3, denominator=0, value=-3, unit=MetricUnit.LINES)

    assert measurement.value == -3
    assert measurement.denominator == 0


@pytest.mark.parametrize("unit", ["ratio", "lines"])
def test_metric_unit_accepts_supported_raw_value_units(unit: str) -> None:
    assert MetricUnit(unit).value == unit


def test_metric_unit_rejects_an_unknown_unit() -> None:
    with pytest.raises(ValueError):
        MetricUnit("percent")


@pytest.mark.parametrize("field", ["numerator", "denominator", "value"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_metric_measurement_rejects_nonfinite_numbers(field: str, value: float) -> None:
    payload: dict[str, object] = {
        "numerator": 1,
        "denominator": 2,
        "value": 0.5,
        "unit": "ratio",
    }
    payload[field] = value

    with pytest.raises(ValidationError):
        MetricMeasurement.model_validate(payload)


@pytest.mark.parametrize("points", [float("nan"), float("inf"), float("-inf")])
def test_calibrated_score_rejects_nonfinite_points(points: float) -> None:
    with pytest.raises(ValidationError):
        CalibratedScore(points=points, profile_id="py-2026.1")


@pytest.mark.parametrize("points", [0, 37.5, 100])
def test_calibrated_score_accepts_the_closed_points_range(points: float) -> None:
    score = CalibratedScore(points=points, profile_id="py-2026.1")

    assert score.points == points
    assert score.profile_id == "py-2026.1"


@pytest.mark.parametrize("points", [-0.01, 100.01])
def test_calibrated_score_rejects_points_outside_the_closed_range(
    points: float,
) -> None:
    with pytest.raises(ValidationError):
        CalibratedScore(points=points, profile_id="py-2026.1")


@pytest.mark.parametrize("profile_id", ["", " ", "\t\n"])
def test_calibrated_score_requires_a_nonempty_profile_id(profile_id: str) -> None:
    with pytest.raises(ValidationError):
        CalibratedScore(points=50, profile_id=profile_id)


def test_zero_is_a_measured_value_and_not_an_unavailable_state() -> None:
    result = TypeAdapter(MetricResult).validate_python(
        {
            "state": "measured",
            "metric_id": "m2.pattern-verbosity",
            "scope": {"kind": "project", "cohort": "production"},
            "raw": {
                "numerator": 0,
                "denominator": 100,
                "value": 0,
                "unit": "ratio",
            },
        }
    )

    assert isinstance(result, MeasuredMetric)
    assert result.raw.value == 0
    assert result.score is None
    assert result.model_dump(mode="json")["state"] == "measured"


@pytest.mark.parametrize(
    "reason",
    [
        "no-baseline",
        "no-source-lines",
        "no-functions",
        "unsupported-language",
        "unsupported-capability",
        "parse-failed",
        "analyzer-failed",
        "calibration-missing",
        "calibration-incompatible",
    ],
)
def test_unavailable_reason_is_a_closed_set(reason: str) -> None:
    assert UnavailableReason(reason).value == reason


def test_unavailable_reason_rejects_an_unknown_reason() -> None:
    with pytest.raises(ValueError):
        UnavailableReason("not-applicable")


def test_unavailable_metric_carries_no_raw_value_or_score() -> None:
    result = UnavailableMetric(
        metric_id="m1.loc-delta",
        scope=ProjectMetricScope(cohort=Cohort.PRODUCTION),
        reason=UnavailableReason.NO_BASELINE,
        diagnostic_id="diagnostic-17",
    )

    assert result.model_dump(mode="json") == {
        "state": "unavailable",
        "metric_id": "m1.loc-delta",
        "scope": {"kind": "project", "cohort": "production"},
        "reason": "no-baseline",
        "diagnostic_id": "diagnostic-17",
    }


@pytest.mark.parametrize(
    "payload",
    [
        {
            "state": "measured",
            "metric_id": "m4.erosion",
            "scope": {"kind": "project", "cohort": "production"},
            "raw": {
                "numerator": 0,
                "denominator": 10,
                "value": 0,
                "unit": "ratio",
            },
            "reason": "no-functions",
        },
        {
            "state": "unavailable",
            "metric_id": "m4.erosion",
            "scope": {"kind": "project", "cohort": "production"},
            "reason": "no-functions",
            "raw": {
                "numerator": 0,
                "denominator": 10,
                "value": 0,
                "unit": "ratio",
            },
        },
        {
            "state": "unavailable",
            "metric_id": "m4.erosion",
            "scope": {"kind": "project", "cohort": "production"},
            "reason": "no-functions",
            "score": {"points": 0, "profile_id": "py-2026.1"},
        },
    ],
)
def test_metric_result_rejects_fields_from_the_other_state(payload: object) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(MetricResult).validate_python(payload)


@pytest.mark.parametrize("metric_id", ["", " ", "\r\n"])
def test_metric_results_require_a_nonempty_metric_id(metric_id: str) -> None:
    with pytest.raises(ValidationError):
        UnavailableMetric(
            metric_id=metric_id,
            scope=ProjectMetricScope(cohort=Cohort.PRODUCTION),
            reason=UnavailableReason.NO_BASELINE,
        )


@pytest.mark.parametrize(
    "value",
    [
        ProjectMetricScope(cohort=Cohort.PRODUCTION),
        FileMetricScope(path=ProjectPath("src/app.py"), cohort=Cohort.PRODUCTION),
        MetricMeasurement(numerator=0, denominator=10, value=0, unit=MetricUnit.RATIO),
        CalibratedScore(points=25, profile_id="py-2026.1"),
        MeasuredMetric(
            metric_id="m2.pattern-verbosity",
            scope=ProjectMetricScope(cohort=Cohort.PRODUCTION),
            raw=MetricMeasurement(
                numerator=0,
                denominator=10,
                value=0,
                unit=MetricUnit.RATIO,
            ),
        ),
        UnavailableMetric(
            metric_id="m1.loc-delta",
            scope=ProjectMetricScope(cohort=Cohort.PRODUCTION),
            reason=UnavailableReason.NO_BASELINE,
        ),
    ],
)
def test_metric_contracts_are_immutable(value: object) -> None:
    with pytest.raises(ValidationError):
        value.metric_id = "changed"  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (
            ProjectMetricScope,
            {"cohort": "production", "unexpected": True},
        ),
        (
            FileMetricScope,
            {
                "path": "src/app.py",
                "cohort": "production",
                "unexpected": True,
            },
        ),
        (
            MetricMeasurement,
            {
                "numerator": 1,
                "denominator": 10,
                "value": 0.1,
                "unit": "ratio",
                "unexpected": True,
            },
        ),
        (
            CalibratedScore,
            {"points": 10, "profile_id": "py-2026.1", "unexpected": True},
        ),
        (
            UnavailableMetric,
            {
                "metric_id": "m1.loc-delta",
                "scope": {"kind": "project", "cohort": "production"},
                "reason": "no-baseline",
                "unexpected": True,
            },
        ),
    ],
)
def test_metric_contracts_forbid_extra_fields(
    model: type[object], payload: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        model(**payload)  # type: ignore[operator]
